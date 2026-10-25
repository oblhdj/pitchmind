"""Event-sourced live match statistics.

Feed ``MatchEvent``s in order with ``apply``; it returns a ``StatSnapshot`` whenever
one should be published (every ``snapshot_every_s`` of match time, and immediately
after goals, shots, cards, substitutions and phase changes). The whole state is a
fold over the event stream, so replaying a match reproduces every snapshot exactly.

Delivery is at-least-once (Event Hubs), so ``apply`` is idempotent: an event whose
id is not newer than the last applied one is ignored.

Metric definitions
------------------
possession_pct      share of ball-in-play time each team had the ball; the clock stops
                    after goals, fouls, offsides, cards, substitutions and phase changes
                    until the next on-ball action
pass_difficulty     length + pressure + progression + target zone (pitchmind_football)
xg                  distance/angle logistic model, summed over shots
xt                  sum of xT-surface gains from completed passes and carries
pressure_index      1 - exp(-n / k), n = pressing actions (pressures, tackles, interceptions)
                    in the last 5 min, each weighted by how high up the pitch it happened
momentum            (home - away) / (home + away + c) of exponentially decayed threat
                    (xT gained + shot xG + final-third entries), half-life ~3 min
control_chaos       last 5 min: possession fragility (turnovers per on-ball action) and
                    foul rate, mapped to 0..1 (normal play ~0.2-0.4, scrappy spells > 0.7)
rhythm_epm          events per minute over the last 5 min
distance_covered_m  minutes on the pitch x a stamina-based running rate (model estimate;
                    event data alone cannot measure off-ball running)
touches             passes, carries, shots, won tackles and interceptions; receiving the
                    ball is not an event, so receptions are not counted
pass_accuracy_pct   0.0 when a team or player has made no passes (show as "-" in a UI)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from pitchmind_contracts import (
    EventType,
    MatchEvent,
    MatchMeta,
    Outcome,
    Phase,
    Player,
    PlayerStats,
    Score,
    StatSnapshot,
    TeamSide,
    TeamStats,
)
from pitchmind_football import clamp, expected_goals, expected_threat, pass_difficulty, running_rate_m_per_min

HOME, AWAY = TeamSide.HOME, TeamSide.AWAY

WINDOW_S = 300.0
MOMENTUM_TAU_S = 260.0  # decay time constant; half-life ~ 3 min
MOMENTUM_DAMPING = 0.4  # keeps momentum near 0 when neither side creates much
PRESS_SCALE = 18.0  # weighted pressing actions in 5 min that give pressure_index ~ 0.63
FINAL_THIRD_X = 70.0
FINAL_THIRD_ENTRY_THREAT = 0.01  # momentum credit for completing a pass into the final third

ON_BALL = {EventType.PASS, EventType.CARRY, EventType.SHOT}
DEAD_BALL = {
    EventType.GOAL,
    EventType.FOUL,
    EventType.OFFSIDE,
    EventType.CARD,
    EventType.SUBSTITUTION,
    EventType.PHASE_CHANGE,
}
PUBLISH_NOW = {EventType.GOAL, EventType.SHOT, EventType.CARD, EventType.SUBSTITUTION, EventType.PHASE_CHANGE}


@dataclass
class _TeamState:
    passes: int = 0
    passes_completed: int = 0
    difficulty_sum: float = 0.0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    xt: float = 0.0
    tackles_won: int = 0
    possession_s: float = 0.0
    threat: float = 0.0  # exponentially decayed
    pressing: deque[tuple[float, float]] = field(default_factory=deque)  # (t, height weight)


@dataclass
class _PlayerState:
    player: Player
    side: TeamSide
    on_since: float | None = None
    played_s: float = 0.0
    touches: int = 0
    passes: int = 0
    passes_completed: int = 0
    shots: int = 0
    xg: float = 0.0
    tackles_won: int = 0
    top_speed_kmh: float = 0.0
    sprints: int = 0

    def minutes(self, now: float) -> float:
        live = now - self.on_since if self.on_since is not None else 0.0
        return (self.played_s + live) / 60

    @property
    def appeared(self) -> bool:
        return self.on_since is not None or self.played_s > 0


class StatsEngine:
    def __init__(self, meta: MatchMeta, *, snapshot_every_s: float = 60.0) -> None:
        self.meta = meta
        self.snapshot_every_s = snapshot_every_s
        self.t = 0.0
        self.minute = 0
        self.phase = Phase.PRE_MATCH
        self.last_event_id = 0
        self.score = {HOME: 0, AWAY: 0}
        self.possessor: TeamSide | None = None
        self.teams = {HOME: _TeamState(), AWAY: _TeamState()}
        self.players: dict[str, _PlayerState] = {}
        for team in (meta.home, meta.away):
            xi = set(team.starting_xi)
            for p in team.players:
                self.players[p.id] = _PlayerState(p, team.side, on_since=0.0 if p.id in xi else None)
        self._window: deque[tuple[float, EventType]] = deque()  # last WINDOW_S of events
        self._last_snapshot_t: float | None = None
        self._last_applied_id: int | None = None

    # ------------------------------------------------------------------ API

    def apply(self, event: MatchEvent) -> StatSnapshot | None:
        """Fold one event into the state; return a snapshot if one is due.

        Redelivered events (id not newer than the last applied) are ignored and return None.
        """
        if event.match_id != self.meta.match_id:
            raise ValueError(f"event for match {event.match_id}, engine is tracking {self.meta.match_id}")
        if self._last_applied_id is not None and event.id <= self._last_applied_id:
            return None
        if event.t < self.t:
            raise ValueError(f"out-of-order event {event.id}: t={event.t} < {self.t}")

        self._last_applied_id = event.id
        self._advance_clock(event.t)
        self.minute, self.phase, self.last_event_id = event.minute, event.phase, event.id
        self._handle(event)

        due = self._last_snapshot_t is None or event.t - self._last_snapshot_t >= self.snapshot_every_s
        if event.type in PUBLISH_NOW or due:
            self._last_snapshot_t = event.t
            return self.snapshot()
        return None

    def snapshot(self) -> StatSnapshot:
        total_possession = sum(ts.possession_s for ts in self.teams.values())
        players = [self._player_stats(ps) for ps in self.players.values() if ps.appeared]
        distance = {side: sum(p.distance_covered_m for p in players if p.team is side) for side in TeamSide}

        def team_stats(side: TeamSide) -> TeamStats:
            ts = self.teams[side]
            return TeamStats(
                possession_pct=round(100 * ts.possession_s / total_possession, 1) if total_possession else 50.0,
                passes=ts.passes,
                pass_accuracy_pct=round(100 * ts.passes_completed / ts.passes, 1) if ts.passes else 0.0,
                avg_pass_difficulty=round(ts.difficulty_sum / ts.passes, 2) if ts.passes else 0.0,
                shots=ts.shots,
                shots_on_target=ts.shots_on_target,
                xg=round(ts.xg, 2),
                xt=round(ts.xt, 2),
                tackles_won=ts.tackles_won,
                pressure_index=self.pressure_index(side),
                distance_covered_m=round(distance[side]),
            )

        return StatSnapshot(
            match_id=self.meta.match_id,
            t=self.t,
            minute=self.minute,
            phase=self.phase,
            last_event_id=self.last_event_id,
            score=Score(home=self.score[HOME], away=self.score[AWAY]),
            home=team_stats(HOME),
            away=team_stats(AWAY),
            momentum=self.momentum(),
            control_chaos=self.control_chaos(),
            rhythm_epm=self.rhythm_epm(),
            players=players,
        )

    # -------------------------------------------------------------- metrics

    def pressure_index(self, side: TeamSide) -> float:
        weighted = sum(w for _, w in self.teams[side].pressing)
        return round(1 - math.exp(-weighted / PRESS_SCALE), 2)

    def momentum(self) -> float:
        home, away = self.teams[HOME].threat, self.teams[AWAY].threat
        return round(clamp((home - away) / (home + away + MOMENTUM_DAMPING), -1.0, 1.0), 2)

    def _window_minutes(self) -> float:
        return max(60.0, min(WINDOW_S, self.t)) / 60

    def rhythm_epm(self) -> float:
        return round(len(self._window) / self._window_minutes(), 1)

    def _window_count(self, *types: EventType) -> int:
        return sum(kind in types for _, kind in self._window)

    def possession_fragility(self) -> float:
        """Turnovers per on-ball action in the window (0.2 is typical, 0.35+ is scrappy)."""
        on_ball = self._window_count(*ON_BALL)
        return self._window_count(EventType.POSSESSION_CHANGE) / on_ball if on_ball else 0.0

    def control_chaos(self) -> float:
        if self._window_count(*ON_BALL) < 10:  # too little play to judge (kick-off, restarts)
            return 0.0
        fragility_part = clamp((self.possession_fragility() - 0.15) / 0.2, 0.0, 1.0)
        foul_part = clamp((self._window_count(EventType.FOUL, EventType.CARD) - 1) / 5, 0.0, 1.0)
        return round(0.65 * fragility_part + 0.35 * foul_part, 2)

    # ------------------------------------------------------------ internals

    def _advance_clock(self, t: float) -> None:
        dt = t - self.t
        if dt > 0:
            if self.possessor is not None:
                self.teams[self.possessor].possession_s += dt
            decay = math.exp(-dt / MOMENTUM_TAU_S)
            for ts in self.teams.values():
                ts.threat *= decay
        self.t = t
        horizon = t - WINDOW_S
        while self._window and self._window[0][0] < horizon:
            self._window.popleft()
        for ts in self.teams.values():
            while ts.pressing and ts.pressing[0][0] < horizon:
                ts.pressing.popleft()

    def _handle(self, e: MatchEvent) -> None:
        if e.type is not EventType.PHASE_CHANGE:
            self._window.append((e.t, e.type))

        team = self.teams[e.team] if e.team else None
        player = self.players.get(e.player) if e.player else None

        if e.type in ON_BALL and e.team is not None:
            self.possessor = e.team
            if player:
                player.touches += 1

        match e.type:
            case EventType.POSSESSION_CHANGE:
                self.possessor = e.team
            case EventType.PASS:
                self._on_pass(e, team, player)
            case EventType.CARRY:
                self._gain_threat(e, team)
                if player and e.player_speed_kmh:
                    player.top_speed_kmh = max(player.top_speed_kmh, e.player_speed_kmh)
            case EventType.SHOT:
                self._on_shot(e, team, player)
            case EventType.GOAL if e.team is not None:
                self.score[e.team] += 1
            case EventType.TACKLE | EventType.INTERCEPTION | EventType.PRESSURE:
                self._on_defensive(e, team, player)
            case EventType.SPRINT if player:
                player.sprints += 1
                player.top_speed_kmh = max(player.top_speed_kmh, e.player_speed_kmh or 0.0)
            case EventType.SUBSTITUTION:
                self._take_off(player)
                incoming = self.players.get(e.receiver) if e.receiver else None
                if incoming:
                    incoming.on_since = e.t
            case EventType.CARD if e.outcome is Outcome.RED:
                self._take_off(player)
            case _:
                pass

        if e.type in DEAD_BALL:
            self.possessor = None  # possession clock stops until the next on-ball action

    def _on_pass(self, e: MatchEvent, team: _TeamState | None, player: _PlayerState | None) -> None:
        if team is None or e.start is None:
            return
        completed = e.outcome is Outcome.SUCCESS
        team.passes += 1
        team.passes_completed += completed
        end = e.end or e.start
        team.difficulty_sum += pass_difficulty(e.start, end, under_pressure=e.under_pressure)
        if player:
            player.passes += 1
            player.passes_completed += completed
        if completed:
            self._gain_threat(e, team)
            if e.start[0] < FINAL_THIRD_X <= end[0]:
                team.threat += FINAL_THIRD_ENTRY_THREAT

    def _gain_threat(self, e: MatchEvent, team: _TeamState | None) -> None:
        if team is None or e.start is None or e.end is None:
            return
        gain = expected_threat(e.end) - expected_threat(e.start)
        team.xt += gain
        team.threat += max(0.0, gain)

    def _on_shot(self, e: MatchEvent, team: _TeamState | None, player: _PlayerState | None) -> None:
        if team is None or e.start is None:
            return
        xg = expected_goals(e.start, under_pressure=e.under_pressure)
        team.shots += 1
        team.shots_on_target += e.outcome in (Outcome.ON_TARGET, Outcome.GOAL)
        team.xg += xg
        team.threat += xg
        if player:
            player.shots += 1
            player.xg += xg

    def _on_defensive(self, e: MatchEvent, team: _TeamState | None, player: _PlayerState | None) -> None:
        if team is None:
            return
        tackle_won = e.type is EventType.TACKLE and e.outcome is Outcome.SUCCESS
        if tackle_won:
            team.tackles_won += 1
        if player and (tackle_won or e.type is EventType.INTERCEPTION):
            player.touches += 1
            player.tackles_won += tackle_won
        if e.start is not None:
            # 0.3 deep in your own half, 1.0 at the opponent's goal line.
            team.pressing.append((e.t, 0.3 + 0.7 * e.start[0] / 105))

    def _take_off(self, player: _PlayerState | None) -> None:
        if player and player.on_since is not None:
            player.played_s += self.t - player.on_since
            player.on_since = None

    def _player_stats(self, ps: _PlayerState) -> PlayerStats:
        minutes = ps.minutes(self.t)
        rate = running_rate_m_per_min(ps.player.position, ps.player.attributes.stamina)
        return PlayerStats(
            player_id=ps.player.id,
            team=ps.side,
            touches=ps.touches,
            passes=ps.passes,
            pass_accuracy_pct=round(100 * ps.passes_completed / ps.passes, 1) if ps.passes else 0.0,
            shots=ps.shots,
            xg=round(ps.xg, 2),
            tackles_won=ps.tackles_won,
            distance_covered_m=round(minutes * rate),
            top_speed_kmh=round(min(ps.top_speed_kmh, 45.0), 1),
            sprints=ps.sprints,
        )


def replay(meta: MatchMeta, events: list[MatchEvent], *, snapshot_every_s: float = 60.0) -> list[StatSnapshot]:
    """Run a whole match through a fresh engine and return every published snapshot."""
    engine = StatsEngine(meta, snapshot_every_s=snapshot_every_s)
    return [snap for event in events if (snap := engine.apply(event)) is not None]

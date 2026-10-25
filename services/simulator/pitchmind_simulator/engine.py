"""Possession-based synthetic football match engine.

One step = one on-ball action by the team in possession (pass, carry, shot,
clearance), possibly preceded by a press from the defending team. Probabilities
come from player attributes, pressure, fatigue, score state, home advantage and
the active scenario. Output is a stream of contract ``MatchEvent``s.

Internally the ball position is kept in the possessing team's frame (attacking
towards x = 105), which is also the wire convention, so a turnover is just a flip.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pitchmind_contracts import (
    EventType,
    MatchEvent,
    MatchMeta,
    Outcome,
    Phase,
    Player,
    Position,
    TeamSide,
)
from pitchmind_football import (
    GOAL_Y,
    clamp,
    clamp_point,
    distance,
    distance_to_goal,
    expected_goals,
    flip,
    pass_difficulty,
    zone,
)

from .scenario import ORGANIC, Beat, BeatKind, Scenario, ScheduledSub

HOME, AWAY = TeamSide.HOME, TeamSide.AWAY
ORGANIC_SPRINT_CAP_KMH = 34.5  # scenario sprints may exceed this, so they stand out

# Likelihood a position is on the ball in each zone: (own, mid, final)
ZONE_WEIGHTS: dict[Position, tuple[float, float, float]] = {
    Position.GK: (0.5, 0.0, 0.0),
    Position.CB: (1.0, 0.3, 0.05),
    Position.FB: (0.8, 0.8, 0.4),
    Position.DM: (0.7, 0.9, 0.2),
    Position.CM: (0.5, 1.0, 0.5),
    Position.AM: (0.1, 0.8, 1.0),
    Position.W: (0.1, 0.7, 1.1),
    Position.ST: (0.02, 0.4, 1.3),
}
ZONE_INDEX = {"own": 0, "mid": 1, "final": 2}
MIRROR_ZONE = {"own": "final", "mid": "mid", "final": "own"}


def other(side: TeamSide) -> TeamSide:
    return AWAY if side is HOME else HOME


@dataclass
class PlayerState:
    player: Player
    side: TeamSide
    on_pitch: bool
    entered_t: float = 0.0
    yellows: int = 0
    used: bool = False  # has appeared (bench players become used when subbed on)

    def fatigue(self, t: float) -> float:
        """0 = fresh, up to ~0.3 for a low-stamina player at 90 minutes."""
        minutes = max(0.0, t - self.entered_t) / 60
        return clamp(minutes / 90 * (1.15 - self.player.attributes.stamina / 100) * 0.6, 0.0, 0.35)


class MatchEngine:
    def __init__(self, meta: MatchMeta, scenario: Scenario = ORGANIC, seed: int | None = None) -> None:
        self.meta = meta
        self.sc = scenario
        self.rng = random.Random(meta.seed if seed is None else seed)
        # Stoppage time comes from the scenario, or is drawn from the seed (1-4 / 2-6 minutes).
        self.first_half_s = scenario.first_half_s or 2700.0 + self.rng.uniform(60, 240)
        self.second_half_s = scenario.second_half_s or 2700.0 + self.rng.uniform(120, 360)
        self.players: dict[str, PlayerState] = {}
        for team in (meta.home, meta.away):
            xi = set(team.starting_xi)
            for p in team.players:
                self.players[p.id] = PlayerState(p, team.side, on_pitch=p.id in xi, used=p.id in xi)

        self.t = 0.0
        self.phase = Phase.PRE_MATCH
        self.first_half_end: float | None = None
        self.score = {HOME: 0, AWAY: 0}
        self.possession = HOME
        self.ball: tuple[float, float] = (52.5, 34.0)
        self.carrier: str | None = None
        self.pressured = False

        self._started = False
        self._next_id = 0
        self._out: list[MatchEvent] = []
        self._beats: list[Beat] = sorted(scenario.beats, key=lambda b: b.t)
        self._subs: list[ScheduledSub] = sorted(scenario.subs, key=lambda s: s.t)
        self._organic_subs = not scenario.subs
        self._subs_made = {HOME: 0, AWAY: 0}

    # ------------------------------------------------------------------ run

    def run(self) -> Iterator[MatchMeta | MatchEvent]:
        """Play the match. An engine is single-use: create a new one for each match."""
        if self._started:
            raise RuntimeError("MatchEngine.run() can only be called once; create a new engine")
        self._started = True
        yield self.meta

        self.phase = Phase.FIRST_HALF
        self._emit(EventType.PHASE_CHANGE)
        self._kickoff(HOME)
        yield from self._play_until(self.first_half_s)

        self.t = max(self.t, self.first_half_s)
        self.phase = Phase.HALF_TIME
        self._emit(EventType.PHASE_CHANGE)
        self.first_half_end = self.t

        self.phase = Phase.SECOND_HALF
        self._emit(EventType.PHASE_CHANGE)
        if self._organic_subs:
            self._plan_organic_subs(self.first_half_end)
        self._kickoff(AWAY)
        yield from self._play_until(self.first_half_end + self.second_half_s)

        self.t = max(self.t, self.first_half_end + self.second_half_s)
        self.phase = Phase.FULL_TIME
        self._emit(EventType.PHASE_CHANGE)
        yield from self._drain()

    def _play_until(self, end: float) -> Iterator[MatchEvent]:
        while self.t < end:
            self._step()
            yield from self._drain()

    def _drain(self) -> Iterator[MatchEvent]:
        out, self._out = self._out, []
        yield from out

    # ------------------------------------------------------------- helpers

    def _emit(self, type: EventType, **fields: Any) -> MatchEvent:
        event = MatchEvent(
            id=self._next_id,
            match_id=self.meta.match_id,
            t=round(self.t, 1),
            minute=self.minute,
            phase=self.phase,
            type=type,
            **fields,
        )
        self._next_id += 1
        self._out.append(event)
        return event

    def _advance(self, seconds: float) -> None:
        self.t += max(0.1, seconds)

    @property
    def minute(self) -> int:
        if self.first_half_end is None or self.phase in (Phase.FIRST_HALF, Phase.HALF_TIME):
            return min(130, int(self.t // 60))
        return min(130, 45 + int((self.t - self.first_half_end) // 60))

    def _state(self, pid: str) -> PlayerState:
        return self.players[pid]

    def _on_pitch(self, side: TeamSide) -> list[PlayerState]:
        return [s for s in self.players.values() if s.side is side and s.on_pitch]

    def _pick(self, side: TeamSide, zone_name: str, exclude: str | None = None) -> str:
        candidates = [s for s in self._on_pitch(side) if s.player.id != exclude]
        idx = ZONE_INDEX[zone_name]
        weights = [ZONE_WEIGHTS[s.player.position][idx] for s in candidates]
        if sum(weights) == 0:
            weights = [1.0] * len(candidates)
        return self.rng.choices(candidates, weights=weights)[0].player.id

    def _defender(self) -> str:
        return self._pick(other(self.possession), MIRROR_ZONE[zone(self.ball[0])])

    def _goalkeeper(self, side: TeamSide) -> str:
        keepers = [s for s in self._on_pitch(side) if s.player.position is Position.GK]
        return (keepers or self._on_pitch(side))[0].player.id

    def _late_and_trailing(self, side: TeamSide) -> bool:
        return self.phase is Phase.SECOND_HALF and self.minute >= 55 and self.score[side] < self.score[other(side)]

    def _chaos(self) -> float:
        return max((w.chaos for w in self.sc.windows if w.start <= self.t < w.end), default=0.0)

    def _press_intensity(self, side: TeamSide) -> float:
        value = 1.05 if side is HOME else 1.0
        if self._late_and_trailing(side):
            value += 0.3
        elif self._late_and_trailing(other(side)):
            value -= 0.15
        for w in self.sc.windows:
            if w.start <= self.t < w.end and (w.team is None or w.team is side):
                value *= w.press
        return value

    def _press_penalty(self) -> float:
        """Extra failure chance when an above-normal press is on the ball carrier."""
        if not self.pressured:
            return 0.0
        return max(0.0, self._press_intensity(other(self.possession)) - 1.0) * 0.08

    # ---------------------------------------------------------- game flow

    def _kickoff(self, side: TeamSide) -> None:
        if side is not self.possession:
            self.possession = side
            self._emit(EventType.POSSESSION_CHANGE, team=side, start=(52.5, 34.0))
        self.ball = (52.5, 34.0)
        self.carrier = self._pick(side, "mid")
        self.pressured = False

    def _turnover(
        self,
        point: tuple[float, float],
        actor: str | None = None,
        event: EventType | None = None,
        outcome: Outcome | None = None,
    ) -> None:
        """Possession passes to the defending team at ``point`` (given in the old frame)."""
        new_side = other(self.possession)
        new_point = flip(point)
        if event is not None:
            self._emit(event, team=new_side, player=actor, start=new_point, outcome=outcome)
        self.possession = new_side
        self.ball = new_point
        self.carrier = actor or self._pick(new_side, zone(new_point[0]))
        self.pressured = False
        self._emit(EventType.POSSESSION_CHANGE, team=new_side, start=new_point)

    def _restart_with_keeper(self, side: TeamSide) -> None:
        if side is not self.possession:
            self.possession = side
            self._emit(EventType.POSSESSION_CHANGE, team=side, start=(6.0, 34.0))
        self.ball = (6.0, 34.0)
        self.carrier = self._goalkeeper(side)
        self.pressured = False

    def _step(self) -> None:
        self._apply_subs()
        if self._beats and self._beats[0].t <= self.t:
            self._play_beat(self._beats.pop(0))
            return
        carrier = self.carrier
        if carrier is None or not self._state(carrier).on_pitch:
            self.carrier = self._pick(self.possession, zone(self.ball[0]))

        self._maybe_sprint()
        self._maybe_press()

        z = zone(self.ball[0])
        if z == "final":
            xg = expected_goals(self.ball, under_pressure=self.pressured)
            p_shot = clamp(0.016 + xg * 0.2, 0.016, 0.22)
            if self._late_and_trailing(self.possession):
                p_shot *= 1.2
            weights = {"shot": p_shot, "pass": (1 - p_shot) * 0.62, "carry": (1 - p_shot) * 0.38}
        elif z == "mid":
            weights = {"pass": 0.70, "carry": 0.296, "shot": 0.004 if self.ball[0] > 62 else 0.0}
        else:
            weights = {"pass": 0.80, "carry": 0.14, "clear": 0.06 if self.pressured else 0.0}

        action = self.rng.choices(list(weights), weights=list(weights.values()))[0]
        {"pass": self._pass, "carry": self._carry, "shot": self._shoot, "clear": self._clear}[action]()

    # ------------------------------------------------------------- actions

    def _maybe_press(self) -> None:
        defending = other(self.possession)
        intensity = self._press_intensity(defending)
        # A pressing team presses *high*: intensity counts twice in the opponent's own half.
        zone_factor = 1.25 * intensity if self.ball[0] < 52.5 else 0.85
        if self.rng.random() < min(0.85, 0.16 * intensity * zone_factor):
            self._emit(EventType.PRESSURE, team=defending, player=self._defender(), start=flip(self.ball))
            self.pressured = True
            self._advance(0.8)
        else:
            self.pressured = False

    def _maybe_sprint(self) -> None:
        if self.rng.random() >= 0.035:
            return
        runner = self._state(self._pick(self.possession, "final"))
        speed = 21 + runner.player.attributes.pace * 0.13 * (1 - runner.fatigue(self.t))
        speed = round(clamp(speed + self.rng.gauss(0, 1.2), 18.0, ORGANIC_SPRINT_CAP_KMH), 1)
        start = clamp_point(self.ball[0] - self.rng.uniform(5, 25), self.rng.uniform(5, 63))
        length = self.rng.uniform(15, 45)
        end = clamp_point(start[0] + length, start[1] + self.rng.gauss(0, 4))
        self._emit(
            EventType.SPRINT,
            team=self.possession,
            player=runner.player.id,
            start=start,
            end=end,
            player_speed_kmh=speed,
            distance_m=round(distance(start, end), 1),
        )

    def _pass(self) -> None:
        passer = self._state(self.carrier or self._pick(self.possession, zone(self.ball[0])))
        start = self.ball
        attacking = self._late_and_trailing(self.possession)
        long_bias = 0.15 if self.pressured and zone(start[0]) == "own" else 0.0

        r = self.rng.random()
        if r < 0.62 - long_bias:
            length = self.rng.uniform(7, 18)
        elif r < 0.90:
            length = self.rng.uniform(18, 30)
        else:
            length = self.rng.uniform(30, 55)

        angle = self.rng.gauss(0.4 if attacking else 0.25, 0.95)
        angle = angle if self.rng.random() < 0.5 else -angle
        if start[1] < 8:
            angle = abs(angle)
        elif start[1] > 60:
            angle = -abs(angle)

        end = clamp_point(start[0] + length * math.cos(angle) + 3, start[1] + length * math.sin(angle))
        length = distance(start, end)
        difficulty = pass_difficulty(start, end, under_pressure=self.pressured)
        attrs = passer.player.attributes
        p_success = (
            1.11
            - 0.52 * difficulty
            + (attrs.passing - 70) / 250
            - passer.fatigue(self.t) * 0.25
            + (0.01 if self.possession is HOME else 0.0)
            - self._chaos() * 0.28
            - self._press_penalty()
        )
        success = self.rng.random() < clamp(p_success, 0.25, 0.97)
        ball_speed = round(clamp(25 + length * 1.25 + self.rng.gauss(0, 4), 15, 110), 1)
        common = dict(
            team=self.possession,
            player=passer.player.id,
            start=start,
            end=end,
            under_pressure=self.pressured,
            ball_speed_kmh=ball_speed,
            distance_m=round(length, 1),
        )

        if success:
            receiver = self._pick(self.possession, zone(end[0]), exclude=passer.player.id)
            if end[0] > 85 and self.rng.random() < 0.012:
                self._emit(EventType.PASS, receiver=receiver, outcome=Outcome.FAILURE, **common)
                self._emit(EventType.OFFSIDE, team=self.possession, player=receiver, start=end)
                self._advance(12 + self.rng.uniform(0, 8))
                self._turnover(end)
                return
            self._emit(EventType.PASS, receiver=receiver, outcome=Outcome.SUCCESS, **common)
            self.ball, self.carrier = end, receiver
            self._advance(1.2 + length / 14 + self.rng.random() * 1.5)
            return

        self._emit(EventType.PASS, outcome=Outcome.FAILURE, **common)
        self._advance(1.0 + length / 14)
        if self.rng.random() < 0.7:
            interceptor = self._pick(other(self.possession), MIRROR_ZONE[zone(end[0])])
            self._turnover(end, interceptor, EventType.INTERCEPTION)
        else:
            self._advance(8 + self.rng.uniform(0, 10))  # out of play
            self._turnover(end)

    def _carry(self) -> None:
        carrier = self._state(self.carrier or self._pick(self.possession, zone(self.ball[0])))
        attrs = carrier.player.attributes
        start = self.ball
        length = self.rng.uniform(4, 10 + attrs.pace / 8)
        angle = self.rng.gauss(0.15, 0.6) * (1 if self.rng.random() < 0.5 else -1)
        end = clamp_point(start[0] + length * math.cos(angle), start[1] + length * math.sin(angle))
        speed = round(clamp(14 + attrs.pace * 0.11 * (1 - carrier.fatigue(self.t)) + self.rng.gauss(0, 1.5), 8, 34), 1)
        chaos = self._chaos()

        if self.rng.random() < 0.2 + (0.18 if self.pressured else 0.0) + chaos * 0.3 + 2 * self._press_penalty():
            defender = self._state(self._defender())
            if self.rng.random() < 0.27 + chaos * 0.25:
                self._foul(defender)
                return
            p_tackle = clamp(
                0.48 + (defender.player.attributes.defending - attrs.dribbling) / 180 + chaos * 0.1, 0.2, 0.8
            )
            mid = clamp_point((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            if self.rng.random() < p_tackle:
                self._emit(
                    EventType.CARRY,
                    team=self.possession,
                    player=carrier.player.id,
                    start=start,
                    end=mid,
                    under_pressure=True,
                    player_speed_kmh=speed,
                    distance_m=round(distance(start, mid), 1),
                )
                self._advance(1.5)
                self._turnover(mid, defender.player.id, EventType.TACKLE, Outcome.SUCCESS)
                return
            self._emit(
                EventType.TACKLE,
                team=other(self.possession),
                player=defender.player.id,
                start=flip(start),
                outcome=Outcome.FAILURE,
            )

        self._emit(
            EventType.CARRY,
            team=self.possession,
            player=carrier.player.id,
            start=start,
            end=end,
            under_pressure=self.pressured,
            player_speed_kmh=speed,
            distance_m=round(distance(start, end), 1),
        )
        self.ball = end
        self._advance(distance(start, end) / (speed / 3.6) + 0.5)

    def _clear(self) -> None:
        player = self.carrier or self._pick(self.possession, "own")
        start = self.ball
        end = clamp_point(start[0] + self.rng.uniform(30, 55), start[1] + self.rng.gauss(0, 12))
        self._emit(EventType.CLEARANCE, team=self.possession, player=player, start=start, end=end)
        self._advance(3)
        if self.rng.random() < 0.55:
            self._turnover(end)
        else:
            self.ball, self.carrier = end, self._pick(self.possession, zone(end[0]))

    def _foul(self, fouler: PlayerState) -> None:
        self._emit(EventType.FOUL, team=fouler.side, player=fouler.player.id, start=flip(self.ball))
        if self.rng.random() < 0.14 + self._chaos() * 0.1:
            fouler.yellows += 1
            if fouler.yellows >= 2:
                self._emit(EventType.CARD, team=fouler.side, player=fouler.player.id, outcome=Outcome.RED)
                fouler.on_pitch = False
            else:
                self._emit(EventType.CARD, team=fouler.side, player=fouler.player.id, outcome=Outcome.YELLOW)
        self._advance(12 + self.rng.uniform(0, 15))
        self.pressured = False

    def _shoot(self, forced: Outcome | None = None) -> None:
        shooter = self._state(self.carrier or self._pick(self.possession, "final"))
        attrs = shooter.player.attributes
        start = self.ball
        xg = expected_goals(start, under_pressure=self.pressured)
        speed = round(
            clamp(55 + attrs.finishing * 0.4 + distance_to_goal(start) * 0.6 + self.rng.gauss(0, 7), 40, 128), 1
        )

        if forced is not None:
            outcome = forced
        else:
            # Calibrated so goals ~= xG on average; good finishers beat their xG slightly.
            p_goal = clamp(xg * (0.97 + (attrs.finishing - 75) / 200) * (1 - shooter.fatigue(self.t) * 0.3), 0.005, 0.8)
            r = self.rng.random()
            if r < p_goal:
                outcome = Outcome.ON_TARGET if self.sc.lock_score else Outcome.GOAL
            elif r < p_goal + 0.27:
                outcome = Outcome.ON_TARGET
            elif r < p_goal + 0.52:
                outcome = Outcome.BLOCKED
            else:
                outcome = Outcome.OFF_TARGET

        if outcome in (Outcome.GOAL, Outcome.ON_TARGET):
            end = clamp_point(105, GOAL_Y + self.rng.gauss(0, 2.2))
        elif outcome is Outcome.OFF_TARGET:
            end = clamp_point(105, GOAL_Y + self.rng.choice((-1, 1)) * self.rng.uniform(4.5, 12))
        else:
            end = clamp_point(start[0] + 2, start[1])

        shot = self._emit(
            EventType.SHOT,
            team=self.possession,
            player=shooter.player.id,
            start=start,
            end=end,
            outcome=outcome,
            under_pressure=self.pressured,
            ball_speed_kmh=speed,
        )
        self._advance(1.5)
        attacking, defending = self.possession, other(self.possession)

        if outcome is Outcome.GOAL:
            self._emit(EventType.GOAL, team=attacking, player=shooter.player.id, related_event_id=shot.id)
            self.score[attacking] += 1
            self._advance(45 + self.rng.uniform(0, 25))
            self._kickoff(defending)
        elif outcome is Outcome.ON_TARGET:
            keeper = self._goalkeeper(defending)
            self._emit(
                EventType.SAVE,
                team=defending,
                player=keeper,
                start=clamp_point(1.0, GOAL_Y + self.rng.gauss(0, 1.5)),
                related_event_id=shot.id,
            )
            self._advance(4 + self.rng.uniform(0, 4))
            self._restart_with_keeper(defending)
        elif outcome is Outcome.BLOCKED:
            if self.rng.random() < 0.5:
                self.ball = clamp_point(start[0] - 8, start[1])
                self.carrier = self._pick(attacking, zone(self.ball[0]))
            else:
                blocker = self._pick(defending, "own")
                self._emit(EventType.CLEARANCE, team=defending, player=blocker, start=flip(start))
                self._turnover(start)
        else:
            self._advance(15 + self.rng.uniform(0, 10))
            self._restart_with_keeper(defending)

    # -------------------------------------------------------- scenario/subs

    def _play_beat(self, beat: Beat) -> None:
        if beat.kind is BeatKind.SPRINT:
            start, end = (40.0, 60.0), (88.0, 62.0)
            self._emit(
                EventType.SPRINT,
                team=beat.team,
                player=beat.player,
                start=start,
                end=end,
                player_speed_kmh=beat.speed_kmh,
                distance_m=round(distance(start, end), 1),
            )
            self._advance(6)
            return

        if self.possession is not beat.team:
            self._turnover(self.ball)
        self.ball = beat.pass_from
        if beat.assist:
            self._emit(
                EventType.PASS,
                team=beat.team,
                player=beat.assist,
                receiver=beat.player,
                start=beat.pass_from,
                end=beat.shot_from,
                outcome=Outcome.SUCCESS,
                under_pressure=beat.under_pressure,
                ball_speed_kmh=round(55 + self.rng.uniform(0, 12), 1),
                distance_m=round(distance(beat.pass_from, beat.shot_from), 1),
            )
        else:
            self._emit(
                EventType.CARRY,
                team=beat.team,
                player=beat.player,
                start=beat.pass_from,
                end=beat.shot_from,
                player_speed_kmh=27.0,
                distance_m=round(distance(beat.pass_from, beat.shot_from), 1),
            )
        self._advance(2.5)
        self.ball, self.carrier, self.pressured = beat.shot_from, beat.player, beat.under_pressure
        forced = {
            BeatKind.GOAL: Outcome.GOAL,
            BeatKind.SAVED_CHANCE: Outcome.ON_TARGET,
            BeatKind.MISSED_CHANCE: Outcome.OFF_TARGET,
        }[beat.kind]
        self._shoot(forced)

    def _plan_organic_subs(self, second_half_start: float) -> None:
        for side in (HOME, AWAY):
            for minute in sorted(self.rng.sample(range(58, 86), 3)):
                t = second_half_start + (minute - 45) * 60
                self._subs.append(ScheduledSub(t, side, off="", on=""))
        self._subs.sort(key=lambda s: s.t)

    def _apply_subs(self) -> None:
        while self._subs and self._subs[0].t <= self.t:
            sub = self._subs.pop(0)
            if self._subs_made[sub.team] >= 5:
                continue
            off = self._state(sub.off) if sub.off else self._most_tired(sub.team)
            on = self._state(sub.on) if sub.on else self._bench_for(off)
            if off is None or on is None or not off.on_pitch or on.used:
                continue
            off.on_pitch = False
            on.on_pitch, on.used, on.entered_t = True, True, self.t
            self._subs_made[sub.team] += 1
            self._emit(EventType.SUBSTITUTION, team=sub.team, player=off.player.id, receiver=on.player.id)
            if self.carrier == off.player.id:
                self.carrier = on.player.id
            self._advance(20)

    def _most_tired(self, side: TeamSide) -> PlayerState | None:
        outfield = [s for s in self._on_pitch(side) if s.player.position is not Position.GK]
        return max(outfield, key=lambda s: s.fatigue(self.t), default=None)

    def _bench_for(self, off: PlayerState | None) -> PlayerState | None:
        if off is None:
            return None
        bench = [
            s
            for s in self.players.values()
            if s.side is off.side and not s.used and s.player.position is not Position.GK
        ]
        same = [s for s in bench if s.player.position is off.player.position]
        candidates = same or bench
        return candidates[0] if candidates else None


def simulate(meta: MatchMeta, scenario: Scenario = ORGANIC, seed: int | None = None) -> list[MatchMeta | MatchEvent]:
    """Run a whole match and return [MatchMeta, *events]."""
    return list(MatchEngine(meta, scenario, seed).run())

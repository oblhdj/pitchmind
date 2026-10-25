"""Shared match state (blackboard) and the facts each agent is allowed to use.

Every agent reads the same ``Facts`` for a moment. They are built by code from the
contracts, never by an LLM, and they bound what the Verifier accepts: every number
in an insight must appear here.
"""

from __future__ import annotations

from collections import OrderedDict

from pitchmind_contracts import MatchEvent, MatchMeta, Moment, MomentKind, Phase, Player, StatSnapshot, TeamSide
from pydantic import BaseModel, ConfigDict

from .numbers import numbers_in

# Stat-alert moments are rendered straight from the numbers; recaps summarise everything else,
# including the half-time score at full time.
_NOT_KEY_MOMENTS = {MomentKind.SPEED_THRESHOLD, MomentKind.DISTANCE_MILESTONE}
_MAX_KEY_MOMENTS = 8


class _Fact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlayerFact(_Fact):
    id: str
    name: str
    full_name: str
    team: str
    position: str


class EventFact(_Fact):
    id: int
    minute: int
    type: str
    team: str | None = None
    player: str | None = None
    receiver: str | None = None
    outcome: str | None = None


class KeyMoment(_Fact):
    minute: int
    kind: str
    team: str | None
    players: list[str]
    summary: str


class Facts(_Fact):
    moment_id: str
    kind: MomentKind
    minute: int
    phase: Phase | None
    team: str | None
    teams: dict[str, str]
    score: dict[str, int] | None
    players: list[PlayerFact]
    evidence: list[int]
    evidence_events: list[EventFact]
    metrics: dict[str, float]
    summary: str
    key_moments: list[KeyMoment]

    def allowed_numbers(self) -> frozenset[float]:
        """Numbers an insight may state: metrics, clock, score and deterministic summaries."""
        allowed = {float(self.minute), 45.0, 90.0, *self.metrics.values()}
        for name in self.metrics:  # windows live in the names: turnovers_last_5min
            allowed.update(numbers_in(name))
        if self.score:
            allowed.update(float(v) for v in self.score.values())
        allowed.update(float(e.minute) for e in self.evidence_events)
        allowed.update(numbers_in(self.summary))
        for km in self.key_moments:
            allowed.add(float(km.minute))
            allowed.update(numbers_in(km.summary))
        names = [*self.teams.values(), *(n for p in self.players for n in (p.name, p.full_name))]
        for name in names:  # "Schalke 04"
            allowed.update(numbers_in(name))
        return frozenset(allowed)


class MatchContext:
    """Everything the agents service has seen for one match."""

    def __init__(self, match_id: str, *, max_events: int = 5000) -> None:
        self.match_id = match_id
        self.meta: MatchMeta | None = None
        self.snapshot: StatSnapshot | None = None
        self.moments: list[Moment] = []
        self._moment_ids: set[str] = set()
        self._players: dict[str, Player] = {}
        self._events: OrderedDict[int, MatchEvent] = OrderedDict()
        self._max_events = max_events

    def observe(self, msg: MatchMeta | MatchEvent | StatSnapshot | Moment) -> None:
        match msg:
            case MatchMeta():
                self.meta = msg
                self._players = {p.id: p for team in (msg.home, msg.away) for p in team.players}
            case MatchEvent():
                self._events[msg.id] = msg
                while len(self._events) > self._max_events:
                    self._events.popitem(last=False)
            case StatSnapshot():
                if self.snapshot is None or msg.t >= self.snapshot.t:
                    self.snapshot = msg
            case Moment():
                if msg.id not in self._moment_ids:
                    self._moment_ids.add(msg.id)
                    self.moments.append(msg)

    def seen(self, moment_id: str) -> bool:
        return moment_id in self._moment_ids

    def player_name(self, pid: str) -> str:
        player = self._players.get(pid)
        return player.short_name if player else pid

    def team_name(self, side: TeamSide) -> str:
        if self.meta is None:
            return "home team" if side is TeamSide.HOME else "away team"
        return (self.meta.home if side is TeamSide.HOME else self.meta.away).name

    def _player_fact(self, pid: str) -> PlayerFact:
        player = self._players.get(pid)
        team = self.team_name(TeamSide.HOME if pid.startswith("H") else TeamSide.AWAY)
        if player is None:
            return PlayerFact(id=pid, name=pid, full_name=pid, team=team, position="unknown")
        return PlayerFact(
            id=pid, name=player.short_name, full_name=player.name, team=team, position=player.position.value
        )

    def _event_fact(self, eid: int) -> EventFact | None:
        event = self._events.get(eid)
        if event is None:
            return None
        return EventFact(
            id=event.id,
            minute=event.minute,
            type=event.type.value,
            team=self.team_name(event.team) if event.team else None,
            player=self.player_name(event.player) if event.player else None,
            receiver=self.player_name(event.receiver) if event.receiver else None,
            outcome=event.outcome.value if event.outcome else None,
        )

    def _phase(self, moment: Moment) -> Phase | None:
        phase = self.snapshot.phase if self.snapshot else None
        if moment.kind is MomentKind.PHASE and phase not in {Phase.HALF_TIME, Phase.FULL_TIME}:
            # Phase moments are only emitted at half-time and full-time.
            return Phase.FULL_TIME if moment.minute >= 90 else Phase.HALF_TIME
        return phase

    def _score(self, moment: Moment) -> dict[str, int] | None:
        if "home_goals" in moment.metrics and "away_goals" in moment.metrics:
            return {"home": int(moment.metrics["home_goals"]), "away": int(moment.metrics["away_goals"])}
        if self.snapshot is not None:
            return {"home": self.snapshot.score.home, "away": self.snapshot.score.away}
        return None

    def _key_moments(self, moment: Moment) -> list[Moment]:
        if moment.kind is not MomentKind.PHASE:
            return []
        earlier = [m for m in self.moments if m.t <= moment.t and m.id != moment.id and m.kind not in _NOT_KEY_MOMENTS]
        top = sorted(earlier, key=lambda m: m.importance, reverse=True)[:_MAX_KEY_MOMENTS]
        return sorted(top, key=lambda m: m.t)

    def facts_for(self, moment: Moment) -> Facts:
        key_moments = self._key_moments(moment)
        player_ids = dict.fromkeys([*moment.players, *(p for m in key_moments for p in m.players)])
        events = [self._event_fact(eid) for eid in moment.evidence]
        return Facts(
            moment_id=moment.id,
            kind=moment.kind,
            minute=moment.minute,
            phase=self._phase(moment),
            team=self.team_name(moment.team) if moment.team else None,
            teams={side.value: self.team_name(side) for side in TeamSide},
            score=self._score(moment),
            players=[self._player_fact(pid) for pid in player_ids],
            evidence=list(moment.evidence),
            evidence_events=[e for e in events if e is not None],
            metrics=dict(moment.metrics),
            summary=moment.fallback_text,
            key_moments=[
                KeyMoment(
                    minute=m.minute,
                    kind=m.kind.value,
                    team=self.team_name(m.team) if m.team else None,
                    players=[self.player_name(p) for p in m.players],
                    summary=m.fallback_text,
                )
                for m in key_moments
            ],
        )

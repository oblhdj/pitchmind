"""Shared match context the detection rules read from."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable
from typing import Any

from pitchmind_contracts import EventType, MatchEvent, MatchMeta, Moment, MomentKind, StatSnapshot, TeamSide

HISTORY_S = 600.0  # how far back rules may look


class MatchContext:
    def __init__(self, meta: MatchMeta) -> None:
        self.meta = meta
        self.now = 0.0
        self.minute = 0
        self.score = {TeamSide.HOME: 0, TeamSide.AWAY: 0}
        self.goal_ids: list[int] = []
        self.events: deque[MatchEvent] = deque()
        self.snapshots: deque[StatSnapshot] = deque()
        self._by_id: dict[int, MatchEvent] = {}
        self._names = {p.id: p.short_name for team in (meta.home, meta.away) for p in team.players}
        self._next_n = 1
        self.emitted: list[Moment] = []

    # ------------------------------------------------------------ updates

    def add_event(self, e: MatchEvent) -> None:
        self.now, self.minute = e.t, e.minute
        self.events.append(e)
        self._by_id[e.id] = e
        if e.type is EventType.GOAL and e.team is not None:
            self.score[e.team] += 1
            self.goal_ids.append(e.id)
        self._prune()

    def add_snapshot(self, s: StatSnapshot) -> None:
        self.now, self.minute = max(self.now, s.t), s.minute
        self.snapshots.append(s)
        self._prune()

    def _prune(self) -> None:
        horizon = self.now - HISTORY_S
        while self.events and self.events[0].t < horizon:
            self._by_id.pop(self.events.popleft().id, None)
        while self.snapshots and self.snapshots[0].t < horizon:
            self.snapshots.popleft()

    # ------------------------------------------------------------ queries

    def event(self, event_id: int | None) -> MatchEvent | None:
        return self._by_id.get(event_id) if event_id is not None else None

    def recent(
        self, types: Iterable[EventType], *, team: TeamSide | None = None, within_s: float = 300.0
    ) -> list[MatchEvent]:
        wanted = set(types)
        since = self.now - within_s
        return [e for e in self.events if e.t >= since and e.type in wanted and (team is None or e.team is team)]

    def history(self, within_s: float) -> list[StatSnapshot]:
        since = self.now - within_s
        return [s for s in self.snapshots if s.t >= since]

    def name(self, player_id: str | None) -> str:
        return self._names.get(player_id or "", player_id or "?")

    def team_name(self, side: TeamSide | None) -> str:
        if side is None:
            return "?"
        return self.meta.home.name if side is TeamSide.HOME else self.meta.away.name

    def score_line(self) -> str:
        home, away = self.meta.home.short_name, self.meta.away.short_name
        return f"{home} {self.score[TeamSide.HOME]}-{self.score[TeamSide.AWAY]} {away}"

    def emitted_since(self, kind: MomentKind, within_s: float) -> bool:
        """Was a moment of this kind already announced recently?"""
        return any(m.kind is kind and m.t >= self.now - within_s for m in self.emitted)

    @staticmethod
    def top_players(events: Iterable[MatchEvent], n: int = 3) -> list[str]:
        counts = Counter(e.player for e in events if e.player)
        return [pid for pid, _ in counts.most_common(n)]

    # ------------------------------------------------------------ output

    def moment(self, *, t: float | None = None, minute: int | None = None, **fields: Any) -> Moment:
        moment = Moment(
            id=f"mom-{self.meta.match_id}-{self._next_n}",
            match_id=self.meta.match_id,
            t=self.now if t is None else t,
            minute=self.minute if minute is None else minute,
            **fields,
        )
        self._next_n += 1
        self.emitted.append(moment)
        return moment

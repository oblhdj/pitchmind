"""Moment detector: consumes match events and stat snapshots, emits Moments."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence

from pitchmind_contracts import MatchEvent, MatchMeta, Moment, StatSnapshot

from .context import MatchContext
from .rules import Rule, default_rules

log = logging.getLogger(__name__)

MAX_HELD_SNAPSHOTS = 500  # ~8 h of snapshots; beyond this the events feed is considered stalled


class MomentDetector:
    """Feed it ``match-events`` and ``match-stats``.

    Live, the two topics are consumed independently, so a snapshot can arrive before the
    events it summarises. Such a snapshot is held back and released right after the event
    with id ``last_event_id`` is applied, so live detection matches an offline replay exactly.

    Both inputs are idempotent: a redelivered event (id not newer) or snapshot (not newer
    than the last one processed or held) is ignored.
    """

    def __init__(self, meta: MatchMeta, rules: Sequence[Rule] | None = None) -> None:
        self.ctx = MatchContext(meta)
        self.rules = list(rules) if rules is not None else default_rules()
        self._last_event_id: int | None = None
        self._last_snapshot_key: tuple[float, int] | None = None
        self._held: list[StatSnapshot] = []  # snapshots waiting for their events, oldest first

    def on_event(self, event: MatchEvent) -> list[Moment]:
        if self._last_event_id is not None and event.id <= self._last_event_id:
            return []
        self._last_event_id = event.id
        self.ctx.add_event(event)
        moments = [m for rule in self.rules for m in rule.on_event(self.ctx, event)]
        while self._held and self._held[0].last_event_id <= event.id:
            moments += self._process_snapshot(self._held.pop(0))
        return moments

    def on_snapshot(self, snapshot: StatSnapshot) -> list[Moment]:
        key = (snapshot.t, snapshot.last_event_id)
        newest = self._held[-1] if self._held else None
        latest_key = (newest.t, newest.last_event_id) if newest else self._last_snapshot_key
        if latest_key is not None and key <= latest_key:
            return []
        if self._last_event_id is None or snapshot.last_event_id > self._last_event_id:
            self._held.append(snapshot)
            if len(self._held) <= MAX_HELD_SNAPSHOTS:
                return []
            # The events feed looks stalled: process the oldest snapshot anyway rather than grow forever.
            log.warning(
                "events feed stalled: %d snapshots held for match %s; processing the oldest without its events",
                len(self._held),
                self.ctx.meta.match_id,
            )
            return self._process_snapshot(self._held.pop(0))
        return self._process_snapshot(snapshot)

    @property
    def held_snapshots(self) -> int:
        return len(self._held)

    def _process_snapshot(self, snapshot: StatSnapshot) -> list[Moment]:
        self._last_snapshot_key = (snapshot.t, snapshot.last_event_id)
        self.ctx.add_snapshot(snapshot)
        return [m for rule in self.rules for m in rule.on_snapshot(self.ctx, snapshot)]


def detect(meta: MatchMeta, events: Iterable[MatchEvent], snapshots: Iterable[StatSnapshot]) -> list[Moment]:
    """Replay a match: each snapshot is applied right after the event it reflects."""
    by_event: dict[int, list[StatSnapshot]] = defaultdict(list)
    for snap in snapshots:
        by_event[snap.last_event_id].append(snap)
    detector = MomentDetector(meta)
    moments: list[Moment] = []
    for event in events:
        moments += detector.on_event(event)
        for snap in by_event.pop(event.id, []):
            moments += detector.on_snapshot(snap)
    return moments

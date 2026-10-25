"""The Orchestrator's routing table: which writer handles a moment, and for whom."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pitchmind_contracts import AgentName, InsightKind, Moment, MomentKind, Segment

from .segments import applies

WRITERS = (AgentName.EXPLAIN, AgentName.NARRATIVE, AgentName.RECAP)

ROUTES: dict[MomentKind, tuple[AgentName, InsightKind]] = {
    MomentKind.GOAL: (AgentName.NARRATIVE, InsightKind.COMMENTARY),
    MomentKind.SAVE: (AgentName.NARRATIVE, InsightKind.COMMENTARY),
    MomentKind.CARD: (AgentName.NARRATIVE, InsightKind.COMMENTARY),
    MomentKind.MILESTONE: (AgentName.NARRATIVE, InsightKind.MILESTONE),
    MomentKind.BIG_CHANCE: (AgentName.EXPLAIN, InsightKind.EXPLANATION),
    MomentKind.MOMENTUM_SWING: (AgentName.EXPLAIN, InsightKind.EXPLANATION),
    MomentKind.PRESSURE_SURGE: (AgentName.EXPLAIN, InsightKind.EXPLANATION),
    MomentKind.CONTROL_SHIFT: (AgentName.EXPLAIN, InsightKind.EXPLANATION),
    MomentKind.RHYTHM_CHANGE: (AgentName.EXPLAIN, InsightKind.EXPLANATION),
    MomentKind.SUBSTITUTION_IMPACT: (AgentName.EXPLAIN, InsightKind.EXPLANATION),
    MomentKind.PHASE: (AgentName.RECAP, InsightKind.RECAP),
}

# Speed and distance tags are rendered straight from the numbers within 2 s; no LLM involved.
STAT_ALERTS = frozenset({MomentKind.SPEED_THRESHOLD, MomentKind.DISTANCE_MILESTONE})


@dataclass(frozen=True, slots=True)
class Route:
    writer: AgentName | None
    kind: InsightKind
    reason: str

    @property
    def skip(self) -> bool:
        return self.writer is None


@dataclass(frozen=True, slots=True)
class Plan:
    route: Route
    segments: tuple[Segment, ...]


def route(moment: Moment, *, min_importance: float = 0.0) -> Route:
    if moment.kind in STAT_ALERTS:
        return Route(None, InsightKind.STAT_ALERT, "stat alert: rendered from the numbers, no LLM")
    # A kind added to the contract later still gets commentary rather than crashing the stream.
    writer, kind = ROUTES.get(moment.kind, (AgentName.NARRATIVE, InsightKind.COMMENTARY))
    if moment.importance < min_importance:
        return Route(None, kind, f"importance {moment.importance} below {min_importance}")
    return Route(writer, kind, f"{moment.kind} -> {writer}")


def plan(moment: Moment, segments: Sequence[Segment], *, min_importance: float = 0.0) -> Plan:
    chosen = route(moment, min_importance=min_importance)
    if chosen.skip:
        return Plan(chosen, ())
    return Plan(chosen, tuple(s for s in segments if applies(s, moment)))

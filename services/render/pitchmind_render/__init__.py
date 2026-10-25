"""Render: insights (and LLM-free stat alerts) -> timed overlays for each audience segment.

Stage 4 of the pipeline. It decides *where* (slot), *when* (``show_at`` in match time),
*how long* and *how important* each graphic is, and keeps graphics in the same slot from
overlapping: a new lower third waits for the previous one to clear, unless it is a goal.
"""

from __future__ import annotations

from collections.abc import Sequence

from pitchmind_contracts import (
    Insight,
    InsightKind,
    Language,
    MatchEvent,
    MatchMeta,
    MetricName,
    Moment,
    MomentKind,
    Overlay,
    OverlayMetric,
    OverlaySlot,
    Segment,
    StatSnapshot,
)

# (slot, seconds on screen) per insight kind.
SLOTS: dict[InsightKind, tuple[OverlaySlot, float]] = {
    InsightKind.RECAP: (OverlaySlot.RECAP_CARD, 20.0),
    InsightKind.COMMENTARY: (OverlaySlot.LOWER_THIRD, 8.0),
    InsightKind.EXPLANATION: (OverlaySlot.LOWER_THIRD, 7.0),
    InsightKind.MILESTONE: (OverlaySlot.LOWER_THIRD, 7.0),
    InsightKind.STAT_ALERT: (OverlaySlot.PLAYER_TAG, 5.0),
}

# The one number shown next to the text: (metric, key in moment.metrics, unit).
PRIMARY_METRIC: dict[MomentKind, tuple[MetricName, str, str | None]] = {
    MomentKind.GOAL: (MetricName.XG, "xg", None),
    MomentKind.BIG_CHANCE: (MetricName.XG, "xg", None),
    MomentKind.PRESSURE_SURGE: (MetricName.PRESSURE_INDEX, "pressure_index_after", None),
    MomentKind.MOMENTUM_SWING: (MetricName.MOMENTUM, "momentum_after", None),
    MomentKind.CONTROL_SHIFT: (MetricName.CONTROL_CHAOS, "control_chaos_after", None),
    MomentKind.SPEED_THRESHOLD: (MetricName.PLAYER_SPEED_KMH, "player_speed_kmh", "km/h"),
    MomentKind.DISTANCE_MILESTONE: (MetricName.DISTANCE_COVERED_M, "distance_covered_m", "m"),
}

STAT_ALERTS = frozenset({MomentKind.SPEED_THRESHOLD, MomentKind.DISTANCE_MILESTONE})
SPEED_TITLES = {
    Language.EN: "Top speed",
    Language.FR: "Vitesse de pointe",
    Language.AR: "أعلى سرعة",
    Language.ES: "Velocidad máxima",
}
SPEED_UNITS = {Language.EN: "km/h", Language.FR: "km/h", Language.AR: "كم/س", Language.ES: "km/h"}
DECIMAL_COMMA = frozenset({Language.FR, Language.ES})

LEAD_S = 1.0  # a graphic appears this long (match time) after it is rendered
GAP_S = 2.0  # minimum clear time between two graphics in the same slot
PREEMPT_PRIORITY = 95  # goals and full-time cut in immediately
TITLE_MAX, BODY_MAX = 60, 600  # Overlay contract limits


def priority_for(importance: float) -> int:
    return max(0, min(100, round(40 + 60 * importance)))


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def format_number(value: float, language: Language) -> str:
    text = f"{value:g}"
    return text.replace(".", ",") if language in DECIMAL_COMMA else text


class OverlayRenderer:
    """Feed it every wire message in order; it returns the overlays to publish."""

    def __init__(self, segments: Sequence[Segment]) -> None:
        self.segments = tuple(segments)
        self.clock = 0.0
        self.meta: MatchMeta | None = None
        self._moments: dict[str, Moment] = {}
        self._slot_free_at: dict[tuple[str, OverlaySlot], float] = {}
        self._rendered: set[str] = set()

    def observe(self, message: MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay) -> list[Overlay]:
        match message:
            case MatchMeta():
                self.meta = message
            case MatchEvent() | StatSnapshot():
                self.clock = max(self.clock, message.t)
            case Moment():
                self.clock = max(self.clock, message.t)
                self._moments[message.id] = message
                if message.kind in STAT_ALERTS:
                    return self._stat_alerts(message)
            case Insight():
                overlay = self._from_insight(message)
                return [overlay] if overlay else []
            case _:
                pass
        return []

    # ------------------------------------------------------------- scheduling

    def _schedule(self, segment_key: str, slot: OverlaySlot, duration: float, priority: int) -> float:
        start = self.clock + LEAD_S
        free_at = self._slot_free_at.get((segment_key, slot), 0.0)
        show_at = start if priority >= PREEMPT_PRIORITY else max(start, free_at + GAP_S)
        self._slot_free_at[(segment_key, slot)] = max(free_at, show_at + duration)
        return round(show_at, 1)

    # --------------------------------------------------------------- overlays

    def _from_insight(self, insight: Insight) -> Overlay | None:
        overlay_id = f"ov-{insight.id}"
        if overlay_id in self._rendered:
            return None  # redelivered insight
        self._rendered.add(overlay_id)
        moment = self._moments.get(insight.moment_id or "")
        slot, duration = SLOTS.get(insight.kind, (OverlaySlot.LOWER_THIRD, 7.0))
        priority = priority_for(moment.importance if moment else 0.5)
        evidence = sorted({e for claim in insight.claims for e in claim.evidence})
        return Overlay(
            overlay_id=overlay_id,
            match_id=insight.match_id,
            insight_id=insight.id,
            show_at=self._schedule(insight.segment.key, slot, duration, priority),
            duration_s=duration,
            slot=slot,
            priority=priority,
            segment_key=insight.segment.key,
            language=insight.segment.language,
            title=clip(insight.headline, TITLE_MAX),
            body=clip(insight.body, BODY_MAX),
            team=moment.team if moment else None,
            player_id=insight.segment.player,
            metric=self._metric(moment),
            evidence=evidence or (list(moment.evidence) if moment else []),
        )

    def _stat_alerts(self, moment: Moment) -> list[Overlay]:
        """Speed records go straight from the numbers to the screen: no agent, within 2 s."""
        if moment.kind is not MomentKind.SPEED_THRESHOLD or "player_speed_kmh" not in moment.metrics:
            return []
        player = moment.players[0] if moment.players else None
        speed = moment.metrics["player_speed_kmh"]
        slot, duration = SLOTS[InsightKind.STAT_ALERT]
        priority = priority_for(moment.importance)
        overlays: list[Overlay] = []
        for segment in self.segments:
            if segment.player is not None and segment.player != player:
                continue  # a player-focus fan only gets tags for their player
            overlay_id = f"ov-{moment.id}-{segment.key}"
            if overlay_id in self._rendered:
                continue
            self._rendered.add(overlay_id)
            lang = segment.language
            overlays.append(
                Overlay(
                    overlay_id=overlay_id,
                    match_id=moment.match_id,
                    show_at=self._schedule(segment.key, slot, duration, priority),
                    duration_s=duration,
                    slot=slot,
                    priority=priority,
                    segment_key=segment.key,
                    language=lang,
                    title=SPEED_TITLES[lang],
                    body=f"{self._player_name(player)} — {format_number(speed, lang)} {SPEED_UNITS[lang]}",
                    team=moment.team,
                    player_id=player,
                    metric=self._metric(moment),
                    evidence=list(moment.evidence),
                )
            )
        return overlays

    def _metric(self, moment: Moment | None) -> OverlayMetric | None:
        if moment is None or moment.kind not in PRIMARY_METRIC:
            return None
        name, key, unit = PRIMARY_METRIC[moment.kind]
        if key not in moment.metrics:
            return None
        return OverlayMetric(name=name, value=moment.metrics[key], unit=unit)

    def _player_name(self, player_id: str | None) -> str:
        if self.meta is not None and player_id is not None:
            for team in (self.meta.home, self.meta.away):
                for p in team.players:
                    if p.id == player_id:
                        return p.name
        return player_id or "?"


__all__ = ["OverlayRenderer", "clip", "format_number", "priority_for"]

"""Audience segments: who an insight variant is written for.

Personalising per segment, not per fan, keeps the LLM bill flat: 10,000 fans share a
few dozen segments.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pitchmind_contracts import Language, Moment, Persona, Segment

DEMO_SEGMENTS: tuple[Segment, ...] = tuple(
    Segment.from_key(key)
    for key in (
        "analyst|en|club:*|player:*|metric:*",
        "casual|ar|club:home|player:*|metric:*",
        "beginner|fr|club:*|player:*|metric:*",
        "casual|en|club:*|player:H10|metric:*",
    )
)


def matrix_segments(focus_players: Iterable[str] = ()) -> tuple[Segment, ...]:
    """Every persona x language, plus a casual English player-focus segment per given player."""
    base = [Segment(persona=p, language=lang) for p in Persona for lang in Language]
    focus = [Segment(persona=Persona.CASUAL, language=Language.EN, player=pid) for pid in focus_players]
    return (*base, *focus)


def parse_segments(spec: str) -> tuple[Segment, ...]:
    """``demo``, ``all`` or segment keys separated by ``;``."""
    if spec == "demo":
        return DEMO_SEGMENTS
    if spec == "all":
        return matrix_segments(["H10"])
    return tuple(Segment.from_key(key.strip()) for key in spec.split(";") if key.strip())


def applies(segment: Segment, moment: Moment) -> bool:
    """Player-focus and one-metric fans only get moments about their player or metric."""
    if segment.player is not None and segment.player not in moment.players:
        return False
    if segment.metric_focus is None:
        return True
    # Whole words of the metric name: "xg" matches "home_xg" but "xt" does not match "next_pass".
    word = re.compile(rf"(?:^|_){re.escape(segment.metric_focus.value)}(?:_|$)")
    return any(word.search(name) for name in moment.metrics)


def slug(segment: Segment) -> str:
    parts = [segment.persona.value, segment.language.value]
    if segment.club is not None:
        parts.append(segment.club.value)
    if segment.player is not None:
        parts.append(segment.player.lower())
    if segment.metric_focus is not None:
        parts.append(segment.metric_focus.value)
    return "_".join(parts)

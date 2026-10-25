"""Turn verified drafts, or the template fallback, into ``Insight`` contracts."""

from __future__ import annotations

from collections.abc import Sequence

from pitchmind_contracts import AgentName, Claim, Insight, InsightKind, Language, Moment, MomentKind, Phase, Segment

from .schemas import Draft
from .segments import slug

_DEFAULT = "default"

# Template headlines, so a fallback still speaks the fan's language. The body is moment.fallback_text.
_HEADLINES: dict[Language, dict[str, str]] = {
    Language.EN: {
        MomentKind.GOAL: "Goal!",
        MomentKind.BIG_CHANCE: "Big chance",
        MomentKind.SAVE: "Big save",
        MomentKind.MOMENTUM_SWING: "Momentum shift",
        MomentKind.PRESSURE_SURGE: "Pressure building",
        MomentKind.CARD: "Card",
        Phase.HALF_TIME: "Half-time",
        Phase.FULL_TIME: "Full-time",
        _DEFAULT: "Match update",
    },
    Language.FR: {
        MomentKind.GOAL: "But !",
        MomentKind.BIG_CHANCE: "Grosse occasion",
        MomentKind.SAVE: "Bel arrêt",
        MomentKind.MOMENTUM_SWING: "Le match bascule",
        MomentKind.PRESSURE_SURGE: "La pression monte",
        MomentKind.CARD: "Carton",
        Phase.HALF_TIME: "Mi-temps",
        Phase.FULL_TIME: "Fin du match",
        _DEFAULT: "Point du match",
    },
    Language.AR: {
        MomentKind.GOAL: "هدف!",
        MomentKind.BIG_CHANCE: "فرصة خطيرة",
        MomentKind.SAVE: "تصدٍّ رائع",
        MomentKind.MOMENTUM_SWING: "تحوّل في مجرى المباراة",
        MomentKind.PRESSURE_SURGE: "ضغط متصاعد",
        MomentKind.CARD: "بطاقة",
        Phase.HALF_TIME: "نهاية الشوط الأول",
        Phase.FULL_TIME: "نهاية المباراة",
        _DEFAULT: "تحديث المباراة",
    },
    Language.ES: {
        MomentKind.GOAL: "¡Gol!",
        MomentKind.BIG_CHANCE: "Ocasión clarísima",
        MomentKind.SAVE: "Gran parada",
        MomentKind.MOMENTUM_SWING: "Cambia el partido",
        MomentKind.PRESSURE_SURGE: "Aprieta la presión",
        MomentKind.CARD: "Tarjeta",
        Phase.HALF_TIME: "Descanso",
        Phase.FULL_TIME: "Final del partido",
        _DEFAULT: "Novedad del partido",
    },
}


BODY_MAX = 1500  # Insight.body limit in the contract


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def template_headline(language: Language, kind: MomentKind, phase: Phase | None = None) -> str:
    table = _HEADLINES[language]
    if kind is MomentKind.PHASE and phase in table:
        return table[phase]
    return table.get(kind, table[_DEFAULT])


def insight_id(moment: Moment, segment: Segment) -> str:
    stem = moment.id.removeprefix("mom-")
    return f"ins-{stem}-{slug(segment)}"


def build_insight(
    *,
    moment: Moment,
    segment: Segment,
    kind: InsightKind,
    draft: Draft,
    trace: Sequence[AgentName],
    model: str | None,
    latency_ms: int,
) -> Insight:
    """An insight from a draft that passed the Verifier."""
    claims = [
        Claim(
            text=c.text.strip(),
            evidence=sorted(set(c.evidence)),
            metrics={name: moment.metrics[name] for name in dict.fromkeys(c.metrics)},
        )
        for c in draft.claims
    ]
    return Insight(
        id=insight_id(moment, segment),
        match_id=moment.match_id,
        moment_id=moment.id,
        t=moment.t,
        kind=kind,
        segment=segment,
        headline=draft.headline.strip(),
        body=draft.body.strip(),
        claims=claims,
        verified=True,
        fallback=False,
        agent_trace=list(trace),
        model=model,
        latency_ms=latency_ms,
    )


def fallback_insight(
    *,
    moment: Moment,
    segment: Segment,
    kind: InsightKind,
    trace: Sequence[AgentName],
    latency_ms: int,
    phase: Phase | None = None,
) -> Insight:
    """Template text from the moment detector, so the overlay never goes blank.

    ``fallback_text`` is deterministic and built from the same metrics, so it counts as verified.
    It stays in English; only the headline is localised.
    """
    trace = list(trace)
    if trace[-1:] != [AgentName.TEMPLATE]:
        trace.append(AgentName.TEMPLATE)
    return Insight(
        id=insight_id(moment, segment),
        match_id=moment.match_id,
        moment_id=moment.id,
        t=moment.t,
        kind=kind,
        segment=segment,
        headline=template_headline(segment.language, moment.kind, phase),
        body=_clip(moment.fallback_text, BODY_MAX),
        claims=[Claim(text=moment.fallback_text, evidence=list(moment.evidence), metrics=dict(moment.metrics))],
        verified=True,
        fallback=True,
        agent_trace=trace,
        model=None,
        latency_ms=latency_ms,
    )

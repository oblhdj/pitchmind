"""Turn verified drafts, or the template fallback, into ``Insight`` contracts."""

from __future__ import annotations

from collections.abc import Sequence

from pitchmind_contracts import AgentName, Claim, Insight, InsightKind, Language, Moment, MomentKind, Phase, Segment

from .context import Facts
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

# Template bodies for the other languages: the detector's fallback_text is English only.
# {what} is the headline, {team} the " for <team>" part, {score} the score sentence.
_BODIES: dict[Language, tuple[str, str, str]] = {
    Language.FR: ("{what} à la {minute}e minute{team}.{score}", " pour {name}", " Score : {line}."),
    Language.AR: ("{what} في الدقيقة {minute}{team}.{score}", " لصالح {name}", " النتيجة: {line}."),
    Language.ES: ("{what} en el minuto {minute}{team}.{score}", " para {name}", " Marcador: {line}."),
}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def template_headline(language: Language, kind: MomentKind, phase: Phase | None = None) -> str:
    table = _HEADLINES[language]
    if kind is MomentKind.PHASE and phase in table:
        return table[phase]
    return table.get(kind, table[_DEFAULT])


def template_body(language: Language, moment: Moment, facts: Facts | None, phase: Phase | None = None) -> str:
    """The fallback body in the fan's language, from facts the pipeline produced (no new numbers)."""
    if language not in _BODIES or facts is None:
        return moment.fallback_text
    sentence, for_team, score = _BODIES[language]
    what = template_headline(language, moment.kind, phase).strip("!¡ ")
    team = for_team.format(name=facts.team) if facts.team else ""
    line = ""
    if facts.score is not None:
        home, away = facts.teams.get("home", ""), facts.teams.get("away", "")
        line = score.format(line=f"{home} {facts.score['home']}-{facts.score['away']} {away}")
    return sentence.format(what=what, minute=facts.minute, team=team, score=line)


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
    facts: Facts | None = None,
) -> Insight:
    """Template text, so the overlay never goes blank.

    English uses the detector's ``fallback_text``; other languages get a short localised
    sentence built from ``facts`` (headline, minute, team, score). Both are deterministic and
    built from pipeline data, so they count as verified. The claim keeps the detector's text.
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
        body=_clip(template_body(segment.language, moment, facts, phase), BODY_MAX),
        claims=[Claim(text=moment.fallback_text, evidence=list(moment.evidence), metrics=dict(moment.metrics))],
        verified=True,
        fallback=True,
        agent_trace=trace,
        model=None,
        latency_ms=latency_ms,
    )

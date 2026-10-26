"""Agent instructions and per-run prompts.

A prompt is a list of ``## NAME`` sections. Data sections hold one fenced JSON block,
so the offline mock model (and anyone debugging a trace) can read them back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from pitchmind_contracts import AgentName, InsightKind, Language, Persona, Phase, Segment

from .context import Facts
from .schemas import Draft

GROUNDING_RULES = """\
Grounding rules. A code Verifier enforces them and rejects any answer that breaks one.
- Use only the supplied FACTS. Do not invent players, statistics, events or tactical conclusions.
- Every factual claim cites one or more event ids in "evidence", taken only from FACTS.evidence. Event ids \
belong only in "evidence": never write them in the headline, body or claim text.
- Every number you write must appear in FACTS (metrics, minute, score, summaries). Do not compute, \
convert or round to new numbers; no percentages unless the metric already is one.
- Write every number as digits, ordinals too ("9th minute", "4 shots"); never spell numbers out. Name the halves \
in words ("first half", "second half"). No thousands separators.
- Plain text only: no HTML, Markdown, links or URLs.
- In each claim, "metrics" lists the FACTS.metrics names the claim relies on (it may be empty).
- Keep player and team names exactly as written in FACTS. Never add first names, nicknames, competitions, \
venues or other proper names that FACTS does not contain.
- If FACTS are not enough to say anything useful, set status to "INSUFFICIENT_EVIDENCE" with empty \
headline, body and claims.
- Return JSON only, matching the response schema."""

STYLE = """\
Format: headline at most 60 characters, no full stop. Body at most 2 sentences and 280 characters \
(recaps: 4 sentences, 500 characters). One to three claims, each one short sentence."""

_ROLE = {
    AgentName.EXPLAIN: (
        "You are the Explain agent of PitchMind, a live football intelligence system. Explain why this "
        "moment matters: what changed, what caused it and what it means for the match, using the metrics "
        "as evidence. Neutral, precise English."
    ),
    AgentName.NARRATIVE: (
        "You are the Narrative agent of PitchMind, a live football intelligence system. Write live "
        "commentary for this moment: what happened and the storyline it creates (a lead, a comeback, a "
        "spell of pressure). Vivid but strictly factual English."
    ),
    AgentName.RECAP: (
        "You are the Recap agent of PitchMind, a live football intelligence system. Write the half-time or "
        "full-time recap in English with this skeleton: 1) the score and phase, 2) the key moments in "
        "order, 3) the standout player, 4) a one-line verdict backed by the metrics."
    ),
    AgentName.PERSONA: (
        "You are the Persona agent of PitchMind. Rewrite DRAFT for one audience SEGMENT, in English. Keep "
        "its facts; you may drop claims or merge sentences but never add a fact. Keep each kept claim's "
        "evidence ids and metric names."
    ),
    AgentName.LANGUAGE: (
        "You are the Language agent of PitchMind. Translate and adapt DRAFT into the target language. Adapt "
        "tone and idiom for the persona instead of translating word for word. Keep player and team names "
        "unchanged, in Latin script. Keep every number exactly; you may use the language's decimal "
        "separator. Use Western digits 0-9. Keep each claim's evidence ids and metric names unchanged."
    ),
    AgentName.VERIFIER: (
        "You are the judge inside PitchMind's Verifier. Check DRAFT against FACTS only. Set supported to "
        "false if any statement is not backed by FACTS: an invented event, player, cause or number, or a "
        "claim whose cited events do not fit it. List each problem in issues as one short line. Otherwise "
        "return supported true with no issues."
    ),
}

INSTRUCTIONS: dict[AgentName, str] = {
    role: text if role is AgentName.VERIFIER else f"{text}\n\n{STYLE}\n\n{GROUNDING_RULES}"
    for role, text in _ROLE.items()
}

PERSONA_GUIDES: dict[Persona, str] = {
    Persona.ANALYST: "Analyst: precise and tactical. Use metric names and exact values. No hype.",
    Persona.CASUAL: "Casual fan: warm and conversational, a little emotion. At most two numbers. No jargon.",
    Persona.BEGINNER: (
        "Beginner, new to football: explain any term in plain words (for example, xG is how likely a chance "
        "was to be scored). Short sentences, at most one number."
    ),
}

LANGUAGE_NAMES: dict[Language, str] = {
    Language.EN: "English",
    Language.FR: "French",
    Language.AR: "Modern Standard Arabic",
    Language.ES: "Spanish",
}

_SECTION = re.compile(r"^## (?P<name>[A-Z_]+)\n```json\n(?P<body>.*?)\n```", re.MULTILINE | re.DOTALL)


def _json(name: str, payload: Any) -> str:
    return f"## {name}\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _text(name: str, text: str) -> str:
    return f"## {name}\n{text}"


def _feedback(rejected: Draft | None, issues: Sequence[str]) -> list[str]:
    if not issues:
        return []
    lines = "\n".join(f"- {issue}" for issue in issues)
    parts = [_text("FEEDBACK", f"The Verifier rejected your previous answer:\n{lines}\nFix every issue.")]
    if rejected is not None:
        parts.append(_json("REJECTED", rejected.model_dump(mode="json")))
    return parts


def read_sections(prompt: str) -> dict[str, Any]:
    """The JSON sections of a prompt, by name."""
    return {m["name"]: json.loads(m["body"]) for m in _SECTION.finditer(prompt)}


def writer_prompt(facts: Facts, kind: InsightKind, *, rejected: Draft | None = None, issues: Sequence[str] = ()) -> str:
    if kind is InsightKind.RECAP:
        label = "full-time" if facts.phase is Phase.FULL_TIME else "half-time"
        task = f"Write the {label} recap."
    else:
        task = f"Moment: {facts.kind.value} in minute {facts.minute}. Write the {kind.value}."
    sections = [_text("TASK", task), _json("FACTS", facts.model_dump(mode="json")), *_feedback(rejected, issues)]
    return "\n\n".join(sections)


def _audience(facts: Facts, segment: Segment) -> str:
    lines = [PERSONA_GUIDES[segment.persona]]
    if segment.club is not None:
        team = facts.teams.get(segment.club.value, segment.club.value)
        lines.append(f"The fan supports {team}. Speak from their side where natural, without changing facts.")
    if segment.player is not None:
        name = next((p.full_name for p in facts.players if p.id == segment.player), segment.player)
        lines.append(f"The fan follows {name}. Put that player at the centre of the text.")
    if segment.metric_focus is not None:
        lines.append(f"The fan follows one metric, {segment.metric_focus.value}. Lead with it.")
    return "\n".join(lines)


def persona_prompt(
    facts: Facts, draft: Draft, segment: Segment, *, rejected: Draft | None = None, issues: Sequence[str] = ()
) -> str:
    sections = [
        _text("TASK", _audience(facts, segment)),
        _json("SEGMENT", segment.model_dump(mode="json")),
        _json("FACTS", facts.model_dump(mode="json")),
        _json("DRAFT", draft.model_dump(mode="json")),
        *_feedback(rejected, issues),
    ]
    return "\n\n".join(sections)


def language_prompt(draft: Draft, segment: Segment, *, issues: Sequence[str] = ()) -> str:
    target = LANGUAGE_NAMES[segment.language]
    task = (
        f"Target language: {target} ({segment.language.value}). Persona: {segment.persona.value}. "
        f"Write the headline, the body and every claim text entirely in {target}: "
        "no sentence may stay in English. Only player and team names stay as they are."
    )
    sections = [_text("TASK", task), _json("DRAFT", draft.model_dump(mode="json")), *_feedback(None, issues)]
    return "\n\n".join(sections)


def judge_prompt(facts: Facts, draft: Draft) -> str:
    return "\n\n".join([_json("FACTS", facts.model_dump(mode="json")), _json("DRAFT", draft.model_dump(mode="json"))])

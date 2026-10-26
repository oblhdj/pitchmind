"""The Verifier: code checks on every draft, plus an optional LLM judge.

Prompts ask the agents to stay grounded; this module enforces it. A draft passes only
if every cited event id comes from the moment's evidence, every metric name exists,
every number in the text (digits or words) appears in the facts, and the text is
plain: no markup, links or control characters reach an overlay.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pitchmind_contracts import AgentName, Language

from .agents import AgentCallError, AgentTeam
from .context import Facts
from .numbers import unsupported_numbers
from .prompts import judge_prompt
from .schemas import Draft, JudgeVerdict
from .telemetry import record_judge_unavailable

logger = logging.getLogger(__name__)

# Insight contract limits.
HEADLINE_MAX = 90
BODY_MAX = 1500

_MARKUP = re.compile(r"[<>]|https?://|www\.|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    issues: tuple[str, ...] = ()
    insufficient: bool = False  # the agent said the facts are not enough; retrying will not help


def check(draft: Draft, facts: Facts, language: Language = Language.EN, *, check_language: bool = True) -> Verdict:
    """Deterministic grounding checks. Never calls an LLM.

    ``check_language`` rejects text left in English for a non-English segment; it is off for
    clients that cannot translate (the offline mock).
    """
    if draft.status != "ok":
        return Verdict(False, ("the agent reported insufficient evidence",), insufficient=True)
    issues: list[str] = []
    headline, body = draft.headline.strip(), draft.body.strip()
    if not headline:
        issues.append("headline is empty")
    elif len(headline) > HEADLINE_MAX:
        issues.append(f"headline has {len(headline)} characters, the limit is {HEADLINE_MAX}")
    if not body:
        issues.append("body is empty")
    elif len(body) > BODY_MAX:
        issues.append(f"body has {len(body)} characters, the limit is {BODY_MAX}")
    if not draft.claims:
        issues.append("there are no claims; cite at least one")

    evidence = set(facts.evidence)
    for n, claim in enumerate(draft.claims, 1):
        if not claim.text.strip():
            issues.append(f"claim {n} has no text")
        if not claim.evidence:
            issues.append(f"claim {n} cites no event id")
        if bad_ids := sorted(set(claim.evidence) - evidence):
            issues.append(f"claim {n} cites event ids {bad_ids} that are not in FACTS.evidence")
        if unknown := [name for name in claim.metrics if name not in facts.metrics]:
            issues.append(f"claim {n} names metrics {unknown} that are not in FACTS.metrics")

    allowed = facts.allowed_numbers()
    texts = [("headline", headline), ("body", body), *((f"claim {n}", c.text) for n, c in enumerate(draft.claims, 1))]
    for where, text in texts:
        if _MARKUP.search(text):
            issues.append(f"{where} contains markup, a link or control characters; write plain text")
        if bad_numbers := unsupported_numbers(text, allowed, language):
            # Writers often copy event ids into the prose; "not in FACTS" alone does not tell them
            # why, so the retry repeats the mistake. Name them for what they are.
            ids = [n for n in bad_numbers if n.isdigit() and int(n) in evidence]
            if ids:
                issues.append(
                    f"{where} writes event ids {', '.join(ids)}: event ids belong only in a claim's "
                    "evidence, never in the headline, body or claim text"
                )
            if others := [n for n in bad_numbers if n not in ids]:
                issues.append(f"{where} states {', '.join(others)}, which is not in FACTS")
        if bad_names := invented_first_names(text, facts):
            issues.append(f"{where} names {', '.join(bad_names)}, which does not match FACTS.players")
    if check_language:
        shown = [("headline and body", f"{headline} {body}"), ("claims", " ".join(c.text for c in draft.claims))]
        issues.extend(f"{where}: {wrong}" for where, text in shown if (wrong := wrong_language(text, language)))
    return Verdict(not issues, tuple(issues))


_APOSTROPHES = "'" + chr(0x2019)  # straight and typographic
_WORD_RE = re.compile(rf"[^\W\d_]+(?:[{_APOSTROPHES}-][^\W\d_]+)*")
_ENGLISH_MARKERS = frozenset(
    [
        "the",
        "and",
        "of",
        "was",
        "with",
        "his",
        "her",
        "this",
        "that",
        "from",
        "scored",
        "into",
        "after",
        "before",
        "their",
        "they",
        "were",
        "is",
        "are",
        "has",
        "have",
        "for",
        "scores",
        "by",
        "to",
        "against",
        "shot",
        "goal",
    ]
)
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
# Capitalised words that may precede a surname without being a first name.
_SENTENCE_STARTERS = frozenset(
    [
        "The",
        "A",
        "An",
        "When",
        "After",
        "Before",
        "Then",
        "And",
        "But",
        "So",
        "Now",
        "Here",
        "There",
        "Le",
        "La",
        "Les",
        "Un",
        "Une",
        "El",
        "Los",
        "Las",
        "Una",
        "Pour",
        "Par",
        "Para",
        "Por",
        "Con",
        "Avec",
        "Sur",
        "Dans",
        "En",
        "Et",
        "Mais",
        "Puis",
        "Goal",
        "Gol",
        "Captain",
        "Keeper",
        "Striker",
        "Winger",
        "Defender",
        "As",
        "While",
        "With",
        "Forward",
        "Midfielder",
        "Goalkeeper",
        "Substitute",
        "Coach",
        "Attaquant",
        "Milieu",
        "Défenseur",
        "Gardien",
        "Delantero",
        "Portero",
        "Centrocampista",
        "Defensa",
    ]
)


def wrong_language(text: str, language: Language) -> str | None:
    """Catch a translation that never happened: English left in a French, Spanish or Arabic text."""
    if language is Language.EN or not text.strip():
        return None
    if language is Language.AR:
        arabic, latin = len(_ARABIC_LETTER.findall(text)), len(_LATIN_LETTER.findall(text))
        # Player and team names stay in Latin script, so a minority of Latin letters is fine.
        return None if arabic >= latin else "the text is not in Arabic; translate it (names stay in Latin script)"
    words = [w.lower() for w in _WORD_RE.findall(text)]
    english = sum(w in _ENGLISH_MARKERS for w in words)
    if english >= 3 and english / max(len(words), 1) >= 0.08:
        return f"the text is still in English; write it in {language.value}"
    return None


def _title_case(text: str) -> bool:
    """Most words capitalised, as in many headlines ("Early Strike From Halvorsen")."""
    words = _WORD_RE.findall(text)
    return len(words) >= 3 and sum(w[0].isupper() for w in words) / len(words) >= 0.6


def invented_first_names(text: str, facts: Facts) -> list[str]:
    """A capitalised word glued to a known surname that is not the player's real name ("Johan Halvorsen").

    To avoid rejecting good text, it skips Title Case text (capitals carry no signal there) and the
    first word of a sentence, so an invented name opening a sentence goes unnoticed: a known gap.
    """
    if _title_case(text):
        return []
    found: list[str] = []
    for player in facts.players:
        for match in re.finditer(rf"\b([A-Z][a-zà-ÿ]+)\s+{re.escape(player.name)}\b", text):
            word, before = match.group(1), text[: match.start()].rstrip()
            phrase = f"{word} {player.name}"
            sentence_start = not before or before[-1] in ".!?:"
            if phrase not in player.full_name and word not in _SENTENCE_STARTERS and not sentence_start:
                found.append(phrase)
    return found


class Verifier:
    def __init__(self, team: AgentTeam) -> None:
        self._team = team

    async def verify(
        self, draft: Draft, facts: Facts, *, language: Language = Language.EN, judge: bool = False
    ) -> Verdict:
        """Code checks first; the LLM judge only looks at drafts that already pass them.

        The judge is advisory: if it cannot be reached, the code verdict stands (logged and
        traced), so a judge outage never blanks the overlay.
        """
        verdict = check(draft, facts, language, check_language=self._team.translates)
        if not verdict.ok or not judge or not self._team.judge_enabled:
            return verdict
        try:
            ruling = await self._team.ask(AgentName.VERIFIER, judge_prompt(facts, draft), JudgeVerdict)
        except AgentCallError as exc:
            logger.warning("judge unavailable, keeping the code verdict: %s", exc.reason)
            record_judge_unavailable(exc.reason)
            return verdict
        if ruling.supported:
            return verdict
        return Verdict(False, tuple(f"judge: {issue}" for issue in ruling.issues) or ("judge: unsupported statement",))

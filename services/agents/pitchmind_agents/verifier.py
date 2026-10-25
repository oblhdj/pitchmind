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


def check(draft: Draft, facts: Facts, language: Language = Language.EN) -> Verdict:
    """Deterministic grounding checks. Never calls an LLM."""
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
            issues.append(f"{where} states {', '.join(bad_numbers)}, which is not in FACTS")
    return Verdict(not issues, tuple(issues))


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
        verdict = check(draft, facts, language)
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

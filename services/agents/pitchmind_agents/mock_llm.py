"""Offline chat clients: a deterministic grounded mock, and a function-backed client for tests.

The mock runs the full Agent Framework pipeline without Foundry. Writers echo the
moment's deterministic summary as one fully cited claim; Persona and Language pass the
draft through unchanged (so non-English segments stay in English); the judge approves.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from agent_framework import BaseChatClient, ChatResponse, FunctionInvocationLayer, Message
from pitchmind_contracts import AgentName, Language

from .agents import LLM_AGENTS, ClientSet
from .context import Facts
from .insights import template_headline
from .prompts import read_sections
from .routing import WRITERS
from .schemas import ClaimDraft, Draft, JudgeVerdict

Responder = Callable[[str], Awaitable[str]]
"""Prompt text in, JSON reply out."""


class FunctionChatClient(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    """A chat client whose replies come from a Python function."""

    OTEL_PROVIDER_NAME = "pitchmind.mock"

    def __init__(self, respond: Responder, *, model: str = "mock") -> None:
        super().__init__()
        self._respond = respond
        self.model = model

    async def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool, options: Mapping[str, Any], **kwargs: Any
    ) -> ChatResponse:
        if stream:
            raise NotImplementedError("FunctionChatClient does not stream")
        reply = await self._respond("\n".join(m.text for m in messages))
        return ChatResponse(messages=[Message(role="assistant", contents=[reply])], model=self.model)


def mock_draft(facts: Facts) -> Draft:
    """A draft that passes the Verifier by construction: the detector's own sentence, fully cited."""
    return Draft(
        status="ok",
        headline=template_headline(Language.EN, facts.kind, facts.phase),
        body=facts.summary,
        claims=[ClaimDraft(text=facts.summary, evidence=list(facts.evidence), metrics=list(facts.metrics))],
    )


def grounded_responder(role: AgentName, *, delay_s: float = 0.0) -> Responder:
    async def respond(prompt: str) -> str:
        if delay_s:
            await asyncio.sleep(delay_s)
        sections = read_sections(prompt)
        if role is AgentName.VERIFIER:
            return JudgeVerdict(supported=True, issues=[]).model_dump_json()
        if role in WRITERS:
            return mock_draft(Facts.model_validate(sections["FACTS"])).model_dump_json()
        return Draft.model_validate(sections["DRAFT"]).model_dump_json()

    return respond


def mock_client_set(*, delay_s: float = 0.0, overrides: Mapping[AgentName, Responder] | None = None) -> ClientSet:
    """Offline clients for every agent; ``overrides`` replaces the responder of chosen agents."""
    overrides = overrides or {}
    clients = {
        role: FunctionChatClient(overrides.get(role) or grounded_responder(role, delay_s=delay_s))
        for role in LLM_AGENTS
    }
    return ClientSet(clients=clients, models=dict.fromkeys(LLM_AGENTS, "mock"), translates=False)

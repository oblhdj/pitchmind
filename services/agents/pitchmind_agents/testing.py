"""Offline helpers for tests and experiments: the mock demo match and scripted agents.

Nothing here talks to Foundry. ``MOCK_STREAM`` points into the repository checkout, so
these helpers are for development installs, not deployed services.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import cache
from pathlib import Path

from pitchmind_contracts import AgentName, Insight, Moment, Overlay

from .mock_llm import grounded_responder
from .runtime import read_wire
from .schemas import Draft
from .service import AgentsService, WireIn

MOCK_STREAM = Path(__file__).resolve().parents[3] / "data" / "mock" / "stream.jsonl"

Edit = Callable[[Draft, str, int], Draft]
"""Rewrites a grounded reply: (draft, prompt, call number starting at 1) -> draft."""


@cache
def mock_messages() -> tuple[WireIn, ...]:
    return tuple(read_wire(MOCK_STREAM))


def mock_moments() -> list[Moment]:
    return [m for m in mock_messages() if isinstance(m, Moment)]


def hand_written_insights() -> list[Insight]:
    """The insights written by hand into the mock stream (not produced by the agents)."""
    return [m for m in mock_messages() if isinstance(m, Insight)]


def prime(service: AgentsService, moment_id: str) -> Moment:
    """Feed the shared state everything before ``moment_id`` without running earlier moments."""
    for msg in mock_messages():
        if isinstance(msg, Insight | Overlay):
            continue
        if isinstance(msg, Moment) and msg.id == moment_id:
            return msg
        service.context(msg.match_id).observe(msg)
    raise KeyError(moment_id)


def run_moment(service: AgentsService, moment_id: str) -> dict[str, Insight]:
    """Process one mock moment; insights by segment key."""
    moment = prime(service, moment_id)
    return {i.segment.key: i for i in asyncio.run(service.process(moment))}


def plant(number: str) -> Callable[[Draft], Draft]:
    """Append a number that is not in the facts."""
    return lambda d: d.model_copy(update={"body": f"{d.body} The xG was {number}."})


class Scripted:
    """Grounded mock replies, passed through ``edit`` so a test can plant mistakes or slow an agent."""

    def __init__(
        self, role: AgentName, edit: Edit | None = None, *, delay_s: float = 0.0, error: Exception | None = None
    ) -> None:
        self.prompts: list[str] = []
        self._grounded = grounded_responder(role)
        self._edit = edit
        self._delay_s = delay_s
        self._error = error

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._error is not None:
            raise self._error
        reply = await self._grounded(prompt)
        if self._edit is None:
            return reply
        return self._edit(Draft.model_validate_json(reply), prompt, len(self.prompts)).model_dump_json()

"""The LLM agents: one Microsoft Agent Framework ``Agent`` per role.

``AgentTeam.ask`` wraps every call with what a live broadcast needs: a timeout, a
circuit breaker per agent and a kill switch (for the failure-recovery demo). Any
failure surfaces as ``AgentCallError`` so the workflow can retry or fall back.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agent_framework import Agent, SupportsChatGetResponse
from pitchmind_contracts import AgentName
from pydantic import BaseModel

from .config import AgentsConfig
from .prompts import INSTRUCTIONS

logger = logging.getLogger(__name__)

LLM_AGENTS = (
    AgentName.EXPLAIN,
    AgentName.NARRATIVE,
    AgentName.RECAP,
    AgentName.PERSONA,
    AgentName.LANGUAGE,
    AgentName.VERIFIER,
)


class AgentCallError(RuntimeError):
    def __init__(self, agent: AgentName, reason: str, *, called: bool = True) -> None:
        super().__init__(f"{agent}: {reason}")
        self.agent = agent
        self.reason = reason
        self.called = called  # False when the kill switch or an open circuit stopped the call before the model


@dataclass(frozen=True, slots=True)
class ClientSet:
    """The chat client and model deployment behind each agent."""

    clients: Mapping[AgentName, SupportsChatGetResponse[Any]]
    models: Mapping[AgentName, str]


class CircuitBreaker:
    """Closed: calls pass. Open after ``threshold`` consecutive failures: calls fail fast.

    Once ``cooldown_s`` has passed the circuit is half-open: exactly one probe call goes
    through. Its success closes the circuit; its failure re-opens it for another cooldown.
    """

    def __init__(self, threshold: int, cooldown_s: float, clock: Callable[[], float]) -> None:
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures = 0
        self._open_until: float | None = None
        self._probing = False

    @property
    def state(self) -> str:
        if self._open_until is None:
            return "closed"
        return "half-open" if self._probing or self._clock() >= self._open_until else "open"

    def allow(self) -> bool:
        if self._open_until is None:
            return True
        if self._probing or self._clock() < self._open_until:
            return False
        self._probing = True  # this caller is the probe
        return True

    def success(self) -> None:
        self._failures = 0
        self._open_until = None
        self._probing = False

    def failure(self) -> None:
        if self._open_until is not None:  # the probe failed
            self._open_until = self._clock() + self._cooldown_s
            self._probing = False
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = self._clock() + self._cooldown_s
            self._failures = 0

    def abandon(self) -> None:
        """A cancelled call proves nothing; let the next caller probe."""
        self._probing = False


class AgentTeam:
    def __init__(
        self,
        clients: ClientSet,
        config: AgentsConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or AgentsConfig()
        self.disabled: set[AgentName] = set(self.config.disabled_agents)
        self._models = dict(clients.models)
        self._agents: dict[AgentName, Agent[Any]] = {
            role: Agent(clients.clients[role], INSTRUCTIONS[role], name=role.value) for role in LLM_AGENTS
        }
        self._breakers = {
            role: CircuitBreaker(self.config.breaker_threshold, self.config.breaker_cooldown_s, clock)
            for role in LLM_AGENTS
        }

    def model(self, role: AgentName) -> str | None:
        return self._models.get(role)

    @property
    def judge_enabled(self) -> bool:
        return self.config.judge and AgentName.VERIFIER not in self.disabled

    def disable(self, role: AgentName) -> None:
        self.disabled.add(role)

    def enable(self, role: AgentName) -> None:
        self.disabled.discard(role)

    async def ask[T: BaseModel](self, role: AgentName, prompt: str, schema: type[T]) -> T:
        """Run one agent and return its structured output, or raise ``AgentCallError``."""
        if role in self.disabled:
            raise AgentCallError(role, "disabled", called=False)
        breaker = self._breakers[role]
        if not breaker.allow():
            raise AgentCallError(role, "circuit open", called=False)
        timeout_s = self.config.agent_timeout_s
        try:
            async with asyncio.timeout(timeout_s):
                response = await self._agents[role].run(prompt, options={"response_format": schema})
        except TimeoutError:
            breaker.failure()
            logger.warning("%s timed out after %.1fs", role, timeout_s)
            raise AgentCallError(role, f"timed out after {timeout_s}s") from None
        except asyncio.CancelledError:
            breaker.abandon()
            raise
        except Exception as exc:
            # SDK, network or quota failures all mean the same thing here: fall back.
            breaker.failure()
            logger.warning("%s failed: %s: %s", role, type(exc).__name__, exc)
            raise AgentCallError(role, f"{type(exc).__name__}: {exc}") from exc
        # The service answered, so the circuit is healthy even if this reply turns out unreadable.
        breaker.success()
        try:
            value = response.value
            return value if isinstance(value, schema) else schema.model_validate_json(response.text)
        except Exception as exc:
            logger.warning("%s returned an unreadable reply: %s", role, exc)
            raise AgentCallError(role, f"unreadable reply: {type(exc).__name__}") from exc

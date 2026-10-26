"""The LLM agents: one Microsoft Agent Framework ``Agent`` per role.

``AgentTeam.ask`` wraps every call with what a live broadcast needs: a timeout, a
circuit breaker per agent and a kill switch (for the failure-recovery demo). Any
failure surfaces as ``AgentCallError`` so the workflow can retry or fall back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
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


def with_schema(prompt: str, schema: type[BaseModel]) -> str:
    """The prompt plus an explicit JSON contract, for models without native structured output."""
    return (
        f"{prompt}\n\n## OUTPUT FORMAT\n"
        "Reply with ONLY one JSON object: no prose before or after it, no code fences. "
        "It must validate against this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema(), separators=(',', ':'))}"
    )


def extract_json(text: str) -> str:
    """The JSON object inside a reply that may carry code fences or a sentence around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


_INPUT_VALUE = re.compile(r"input_value=['\"]\s*(.)")


def ignores_response_format(error: BaseException) -> bool:
    """Did the model answer in prose where a structured reply was requested?

    Matches the SDK's pydantic error text. A reply that starts with ``{`` is JSON cut short
    (e.g. by the length limit), not prose, so it does not count.
    """
    message = str(error)
    lowered = message.lower()
    if "json_invalid" not in lowered and not ("validation error" in lowered and "invalid json" in lowered):
        return False
    first = _INPUT_VALUE.search(message)
    return first is None or first.group(1) != "{"


DEFAULT_RATE_LIMIT_WAIT_S = 10.0
MAX_RATE_LIMIT_WAIT_S = 60.0


def rate_limit_wait(error: BaseException) -> float | None:
    """Seconds to wait if ``error`` (or any error it wraps) is an HTTP 429, else ``None``.

    Uses the ``Retry-After`` header when the SDK error carries one.
    """
    stack, seen, limited = [error], set[int](), False
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        text = str(current)
        if getattr(current, "status_code", None) == 429 or "rate_limit_exceeded" in text or "429 Too Many" in text:
            limited = True
            headers = getattr(getattr(current, "response", None), "headers", None)
            raw = headers.get("retry-after") if headers is not None else None
            try:
                return (
                    min(max(float(raw), 1.0), MAX_RATE_LIMIT_WAIT_S) if raw is not None else DEFAULT_RATE_LIMIT_WAIT_S
                )
            except (TypeError, ValueError):
                pass
        stack.extend(e for e in (current.__cause__, current.__context__, *current.args) if isinstance(e, BaseException))
    return DEFAULT_RATE_LIMIT_WAIT_S if limited else None


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
    translates: bool = True  # False for the offline mock, whose Language agent passes text through unchanged


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


class RateLimiter:
    """At most ``per_minute`` calls in any 60-second window, across all agents (0 = unlimited).

    Callers wait for a free slot instead of being rejected with HTTP 429, so a burst of
    insights (a goal fans out to every segment) queues politely under the deployment's limit.
    """

    def __init__(
        self,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._per_minute <= 0:
            return
        async with self._lock:
            while True:
                now = self._clock()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self._per_minute:
                    self._calls.append(now)
                    return
                await self._sleep(60.0 - (now - self._calls[0]))


class AgentTeam:
    def __init__(
        self,
        clients: ClientSet,
        config: AgentsConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config or AgentsConfig()
        self._sleep = sleep
        self.disabled: set[AgentName] = set(self.config.disabled_agents)
        self._models = dict(clients.models)
        self.translates = clients.translates
        self._agents: dict[AgentName, Agent[Any]] = {
            role: Agent(clients.clients[role], INSTRUCTIONS[role], name=role.value) for role in LLM_AGENTS
        }
        self._breakers = {
            role: CircuitBreaker(self.config.breaker_threshold, self.config.breaker_cooldown_s, clock)
            for role in LLM_AGENTS
        }
        self._schema_in_prompt: set[str] = set()  # models seen ignoring response_format
        self._limiter = RateLimiter(self.config.requests_per_minute, clock, sleep)

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
        model = self._models.get(role, role.value)
        timeout_s = self.config.agent_timeout_s
        rate_limited = False
        while True:
            await self._limiter.acquire()  # waiting for a slot does not count against the timeout
            in_prompt = model in self._schema_in_prompt
            try:
                async with asyncio.timeout(timeout_s):
                    if in_prompt:
                        response = await self._agents[role].run(with_schema(prompt, schema))
                    else:
                        response = await self._agents[role].run(prompt, options={"response_format": schema})
                break
            except TimeoutError:
                breaker.failure()
                logger.warning("%s timed out after %.1fs", role, timeout_s)
                raise AgentCallError(role, f"timed out after {timeout_s}s") from None
            except asyncio.CancelledError:
                breaker.abandon()
                raise
            except Exception as exc:
                if not in_prompt and ignores_response_format(exc):
                    # Some Foundry models (e.g. Phi on serverless) answer in prose despite response_format:
                    # from now on, put the JSON schema in this model's prompts. Not a service failure.
                    logger.info("%s: %s ignores response_format; switching to schema-in-prompt", role, model)
                    self._schema_in_prompt.add(model)
                    continue
                if not rate_limited and (wait_s := rate_limit_wait(exc)) is not None:
                    # A quota (429) is the deployment saying "later", not a broken agent: wait once, retry.
                    rate_limited = True
                    logger.info("%s: rate limited by %s; retrying in %.0fs", role, model, wait_s)
                    await self._sleep(wait_s)
                    continue
                # SDK, network or persistent quota failures all mean the same thing here: fall back.
                breaker.failure()
                logger.warning("%s failed: %s: %s", role, type(exc).__name__, exc)
                raise AgentCallError(role, f"{type(exc).__name__}: {exc}") from exc
        # The service answered, so the circuit is healthy even if this reply turns out unreadable.
        breaker.success()
        try:
            value = response.value
            return value if isinstance(value, schema) else schema.model_validate_json(extract_json(response.text))
        except Exception as exc:
            logger.warning("%s returned an unreadable reply: %s", role, exc)
            raise AgentCallError(role, f"unreadable reply: {type(exc).__name__}") from exc

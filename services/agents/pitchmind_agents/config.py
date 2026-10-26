"""Runtime settings for the agents service."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pitchmind_contracts import AgentName


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    agent_timeout_s: float = 8.0  # one agent call
    moment_deadline_s: float = 12.0  # a whole moment; segments still running then get the template
    max_retries: int = 1
    judge: bool = False  # LLM judge on top of the code checks, for writer and segment drafts
    min_importance: float = 0.0
    disabled_agents: frozenset[AgentName] = field(default_factory=frozenset)  # failure-recovery demo switch
    demo_plant: bool = False  # Verifier demo: plant a wrong number in each writer's first draft
    breaker_threshold: int = 3  # consecutive failures that open an agent's circuit
    breaker_cooldown_s: float = 30.0
    requests_per_minute: int = 0  # 0 = unlimited; set below the model deployment's RPM limit

    def __post_init__(self) -> None:
        checks = [
            (self.agent_timeout_s > 0, "agent_timeout_s must be positive"),
            (self.moment_deadline_s > 0, "moment_deadline_s must be positive"),
            (self.max_retries >= 0, "max_retries must be 0 or more"),
            (0 <= self.min_importance <= 1, "min_importance must be between 0 and 1"),
            (self.breaker_threshold >= 1, "breaker_threshold must be at least 1"),
            (self.breaker_cooldown_s >= 0, "breaker_cooldown_s must be 0 or more"),
            (self.requests_per_minute >= 0, "requests_per_minute must be 0 or more"),
        ]
        for ok, message in checks:
            if not ok:
                raise ValueError(message)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgentsConfig:
        """Read ``PITCHMIND_*`` variables; a bad value raises ``ValueError`` naming the variable."""
        env = os.environ if env is None else env
        defaults = cls()

        def read[T](name: str, cast: Callable[[str], T], default: T) -> T:
            raw = env.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                return cast(raw.strip())
            except ValueError:
                raise ValueError(f"{name} must be a {cast.__name__}, got {raw!r}") from None

        known = {a.value for a in AgentName}
        disabled = {n.strip().lower() for n in env.get("PITCHMIND_DISABLED_AGENTS", "").split(",") if n.strip()}
        if unknown := sorted(disabled - known):
            raise ValueError(f"PITCHMIND_DISABLED_AGENTS: unknown agents {unknown}; expected some of {sorted(known)}")
        try:
            return cls(
                agent_timeout_s=read("PITCHMIND_AGENT_TIMEOUT_S", float, defaults.agent_timeout_s),
                moment_deadline_s=read("PITCHMIND_MOMENT_DEADLINE_S", float, defaults.moment_deadline_s),
                max_retries=read("PITCHMIND_MAX_RETRIES", int, defaults.max_retries),
                judge=env.get("PITCHMIND_JUDGE", "0").strip().lower() in {"1", "true", "yes"},
                demo_plant=env.get("PITCHMIND_DEMO_PLANT", "0").strip().lower() in {"1", "true", "yes"},
                min_importance=read("PITCHMIND_MIN_IMPORTANCE", float, defaults.min_importance),
                requests_per_minute=read("PITCHMIND_RPM", int, defaults.requests_per_minute),
                disabled_agents=frozenset(AgentName(name) for name in disabled),
            )
        except ValueError as exc:
            raise ValueError(f"invalid PITCHMIND_* setting: {exc}") from None

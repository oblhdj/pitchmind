"""Chat clients backed by models deployed in Microsoft Foundry.

The writers (Explain, Narrative, Recap) use the stronger deployment; Persona, Language
and the Verifier's judge use the fast one, which keeps per-segment fan-out cheap.
Authentication is Entra ID only: Managed Identity in Azure, ``az login`` locally.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from agent_framework import SupportsChatGetResponse
from agent_framework.foundry import FoundryChatClient
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from pitchmind_contracts import AgentName

from .agents import LLM_AGENTS, ClientSet

STRONG_AGENTS = frozenset({AgentName.EXPLAIN, AgentName.NARRATIVE, AgentName.RECAP})


def foundry_client_set(
    *,
    endpoint: str | None = None,
    strong_model: str | None = None,
    fast_model: str | None = None,
    credential: TokenCredential | None = None,
    env: Mapping[str, str] | None = None,
) -> ClientSet:
    env = os.environ if env is None else env
    endpoint = endpoint or env.get("FOUNDRY_PROJECT_ENDPOINT")
    strong = strong_model or env.get("FOUNDRY_MODEL_STRONG") or env.get("FOUNDRY_MODEL")
    fast = fast_model or env.get("FOUNDRY_MODEL_FAST") or strong
    if not endpoint or not strong or not fast:
        raise ValueError("set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL_STRONG (optionally FOUNDRY_MODEL_FAST)")
    credential = credential or DefaultAzureCredential()

    by_model: dict[str, SupportsChatGetResponse[Any]] = {}
    for model in {strong, fast}:
        by_model[model] = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
    models = {role: strong if role in STRONG_AGENTS else fast for role in LLM_AGENTS}
    return ClientSet(clients={role: by_model[model] for role, model in models.items()}, models=models)

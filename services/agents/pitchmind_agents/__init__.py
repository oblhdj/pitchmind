"""PitchMind agents: moments in, verified and personalised insights out.

Microsoft Agent Framework workflow: Orchestrator -> Explain / Narrative / Recap ->
Persona -> Language -> Verifier, with models from Microsoft Foundry.
"""

from .agents import LLM_AGENTS, AgentCallError, AgentTeam, ClientSet
from .config import AgentsConfig
from .context import Facts, MatchContext
from .mock_llm import FunctionChatClient, mock_client_set
from .routing import Plan, Route, plan, route
from .schemas import ClaimDraft, Draft, JudgeVerdict
from .segments import DEMO_SEGMENTS, matrix_segments, parse_segments
from .service import AgentsService
from .telemetry import configure_tracing
from .verifier import Verdict, Verifier, check
from .workflow import build_workflow

__all__ = [
    "DEMO_SEGMENTS",
    "LLM_AGENTS",
    "AgentCallError",
    "AgentTeam",
    "AgentsConfig",
    "AgentsService",
    "ClaimDraft",
    "ClientSet",
    "Draft",
    "Facts",
    "FunctionChatClient",
    "JudgeVerdict",
    "MatchContext",
    "Plan",
    "Route",
    "Verdict",
    "Verifier",
    "build_workflow",
    "check",
    "configure_tracing",
    "matrix_segments",
    "mock_client_set",
    "parse_segments",
    "plan",
    "route",
]

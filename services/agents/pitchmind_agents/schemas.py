"""Structured outputs of the LLM agents (JSON-schema structured output, parsed by Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    evidence: list[int] = Field(description="Event ids from FACTS.evidence that support this claim")
    metrics: list[str] = Field(description="Names of the FACTS.metrics entries this claim relies on")


class Draft(BaseModel):
    """An insight in progress. Writers create it; Persona and Language rewrite it."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "INSUFFICIENT_EVIDENCE"]
    headline: str
    body: str
    claims: list[ClaimDraft]


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    issues: list[str] = Field(description="One short line per unsupported statement")

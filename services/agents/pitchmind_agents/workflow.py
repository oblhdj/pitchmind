"""The insight workflow, built with Microsoft Agent Framework. One run per moment::

    orchestrator --switch--> explain | narrative | recap --fan-out--> segment[seg] (sub-workflow)

    segment[seg]:  persona --> language (non-English only) --> verifier --> Insight
                      ^                                            |
                      +------------------ retry -------------------+

The writer's draft is verified once (code checks, plus the LLM judge if enabled) and
retried once with the Verifier's feedback before it fans out. Each segment runs as its
own sub-workflow, so a slow or retrying segment never holds the others back: an insight
is published the moment its own Verifier passes it. A rejection goes back to Persona once
with feedback, then to the template. Every segment yields exactly one ``Insight``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from agent_framework import (
    Case,
    Default,
    Executor,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowExecutor,
    handler,
)
from pitchmind_contracts import AgentName, Insight, Language, Moment, Segment

from .agents import AgentCallError, AgentTeam
from .context import Facts
from .insights import build_insight, fallback_insight
from .prompts import language_prompt, persona_prompt, writer_prompt
from .routing import WRITERS, Route
from .schemas import Draft
from .segments import slug
from .telemetry import record_fallback, record_rejection
from .verifier import Verifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MomentJob:
    moment: Moment
    facts: Facts
    route: Route
    segments: tuple[Segment, ...]
    started: float

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def fallback(self, segment: Segment, trace: Sequence[AgentName]) -> Insight:
        insight = fallback_insight(
            moment=self.moment,
            segment=segment,
            kind=self.route.kind,
            trace=trace,
            latency_ms=self.elapsed_ms(),
            phase=self.facts.phase,
        )
        record_fallback(segment.key, insight.agent_trace)
        return insight


@dataclass(frozen=True, slots=True)
class BaseDraft:
    """The writer's verified draft, fanned out to every segment."""

    job: MomentJob
    draft: Draft
    trace: tuple[AgentName, ...]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One segment's draft on its way to the Verifier."""

    base: BaseDraft
    draft: Draft
    trace: tuple[AgentName, ...]
    attempt: int = 0
    feedback: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Retry:
    candidate: Candidate
    issues: tuple[str, ...]


DEMO_WRONG_XG = "0.99"  # an xG the demo match never reaches, so it is not in the facts


def plant_demo_mistake(draft: Draft) -> Draft:
    """The Verifier demo: a hallucinated number the Verifier must catch before fans see it."""
    return draft.model_copy(update={"body": f"{draft.body} The xG was {DEMO_WRONG_XG}."})


def _with(trace: Sequence[AgentName], role: AgentName, error: AgentCallError) -> tuple[AgentName, ...]:
    """The trace after a failed call: the agent counts as having handled it only if it was called."""
    return (*trace, role) if error.called else tuple(trace)


async def _guarded(
    step: str,
    work: Awaitable[None],
    ctx: WorkflowContext[Any, Insight],
    job: MomentJob,
    segments: Sequence[Segment],
    trace: Sequence[AgentName],
) -> None:
    """Last line of defence: an unexpected error costs only this step's segments, never the run."""
    try:
        await work
    except Exception:
        logger.exception("%s failed unexpectedly; publishing the template", step)
        for segment in segments:
            await ctx.yield_output(job.fallback(segment, trace))


class Orchestrator(Executor):
    """Entry point. The switch-case edges after it route the moment to its writer."""

    def __init__(self) -> None:
        super().__init__(id=AgentName.ORCHESTRATOR.value)

    @handler
    async def dispatch(self, job: MomentJob, ctx: WorkflowContext[MomentJob]) -> None:
        logger.info("%s %s: %s, %d segments", job.moment.id, job.moment.kind, job.route.reason, len(job.segments))
        await ctx.send_message(job)


class Writer(Executor):
    """Explain, Narrative or Recap: writes the base English draft for the moment."""

    def __init__(self, role: AgentName, team: AgentTeam, verifier: Verifier) -> None:
        super().__init__(id=role.value)
        self._role = role
        self._team = team
        self._verifier = verifier

    @handler
    async def write(self, job: MomentJob, ctx: WorkflowContext[BaseDraft, Insight]) -> None:
        trace = [AgentName.ORCHESTRATOR]
        await _guarded(self.id, self._write(job, trace, ctx), ctx, job, job.segments, trace)

    async def _write(self, job: MomentJob, trace: list[AgentName], ctx: WorkflowContext[BaseDraft, Insight]) -> None:
        rejected: Draft | None = None
        issues: tuple[str, ...] = ()
        for attempt in range(self._team.config.max_retries + 1):
            prompt = writer_prompt(job.facts, job.route.kind, rejected=rejected, issues=issues)
            try:
                draft = await self._team.ask(self._role, prompt, Draft)
            except AgentCallError as exc:
                trace[:] = _with(trace, self._role, exc)
                break
            # Only when a retry can follow: the demo shows the Verifier catching and recovering.
            if attempt == 0 and self._team.config.demo_plant and self._team.config.max_retries > 0:
                draft = plant_demo_mistake(draft)
                logger.warning("demo: planted xG %s in the %s draft for %s", DEMO_WRONG_XG, self._role, job.moment.id)
            trace += [self._role, AgentName.VERIFIER]
            verdict = await self._verifier.verify(draft, job.facts, judge=True)
            if verdict.ok:
                await ctx.send_message(BaseDraft(job, draft, tuple(trace)))
                return
            logger.info("%s draft rejected: %s", self._role, "; ".join(verdict.issues))
            record_rejection(self.id, attempt, verdict.issues)
            if verdict.insufficient:
                break
            rejected, issues = draft, verdict.issues
        for segment in job.segments:
            await ctx.yield_output(job.fallback(segment, trace))


class PersonaStep(Executor):
    """Rewrites the base draft for one segment: persona, club perspective, player or metric focus."""

    def __init__(self, segment: Segment, team: AgentTeam) -> None:
        super().__init__(id=f"persona_{slug(segment)}")
        self._segment = segment
        self._team = team

    @handler
    async def adapt(self, base: BaseDraft, ctx: WorkflowContext[Candidate, Insight]) -> None:
        candidate = Candidate(base=base, draft=base.draft, trace=base.trace)
        await _guarded(self.id, self._rewrite(candidate, None, ctx), ctx, base.job, [self._segment], base.trace)

    @handler
    async def revise(self, retry: Retry, ctx: WorkflowContext[Candidate, Insight]) -> None:
        candidate = retry.candidate
        revised = replace(candidate, attempt=candidate.attempt + 1, feedback=retry.issues)
        work = self._rewrite(revised, candidate.draft, ctx)
        await _guarded(self.id, work, ctx, candidate.base.job, [self._segment], candidate.trace)

    async def _rewrite(
        self, candidate: Candidate, rejected: Draft | None, ctx: WorkflowContext[Candidate, Insight]
    ) -> None:
        job = candidate.base.job
        prompt = persona_prompt(
            job.facts, candidate.base.draft, self._segment, rejected=rejected, issues=candidate.feedback
        )
        try:
            draft = await self._team.ask(AgentName.PERSONA, prompt, Draft)
        except AgentCallError as exc:
            await ctx.yield_output(job.fallback(self._segment, _with(candidate.trace, AgentName.PERSONA, exc)))
            return
        await ctx.send_message(replace(candidate, draft=draft, trace=(*candidate.trace, AgentName.PERSONA)))


class LanguageStep(Executor):
    """Translates and adapts the segment's draft into its language."""

    def __init__(self, segment: Segment, team: AgentTeam) -> None:
        super().__init__(id=f"language_{slug(segment)}")
        self._segment = segment
        self._team = team

    @handler
    async def translate(self, candidate: Candidate, ctx: WorkflowContext[Candidate, Insight]) -> None:
        job = candidate.base.job
        await _guarded(self.id, self._translate(candidate, ctx), ctx, job, [self._segment], candidate.trace)

    async def _translate(self, candidate: Candidate, ctx: WorkflowContext[Candidate, Insight]) -> None:
        job = candidate.base.job
        prompt = language_prompt(candidate.draft, self._segment, issues=candidate.feedback)
        try:
            draft = await self._team.ask(AgentName.LANGUAGE, prompt, Draft)
        except AgentCallError as exc:
            await ctx.yield_output(job.fallback(self._segment, _with(candidate.trace, AgentName.LANGUAGE, exc)))
            return
        await ctx.send_message(replace(candidate, draft=draft, trace=(*candidate.trace, AgentName.LANGUAGE)))


class VerifierStep(Executor):
    """Gate before publishing: pass, send back to Persona once, or fall back to the template."""

    def __init__(self, segment: Segment, team: AgentTeam, verifier: Verifier) -> None:
        super().__init__(id=f"verifier_{slug(segment)}")
        self._segment = segment
        self._team = team
        self._verifier = verifier
        # The model that wrote the text fans will read.
        self._author = AgentName.PERSONA if segment.language is Language.EN else AgentName.LANGUAGE

    @handler
    async def check(self, candidate: Candidate, ctx: WorkflowContext[Retry, Insight]) -> None:
        job = candidate.base.job
        trace = (*candidate.trace, AgentName.VERIFIER)
        await _guarded(self.id, self._check(candidate, trace, ctx), ctx, job, [self._segment], trace)

    async def _check(
        self, candidate: Candidate, trace: tuple[AgentName, ...], ctx: WorkflowContext[Retry, Insight]
    ) -> None:
        job = candidate.base.job
        verdict = await self._verifier.verify(candidate.draft, job.facts, language=self._segment.language, judge=True)
        if verdict.ok:
            insight = build_insight(
                moment=job.moment,
                segment=self._segment,
                kind=job.route.kind,
                draft=candidate.draft,
                trace=trace,
                model=self._team.model(self._author),
                latency_ms=job.elapsed_ms(),
            )
            await ctx.yield_output(insight)
            return
        logger.info("%s rejected (attempt %d): %s", self.id, candidate.attempt, "; ".join(verdict.issues))
        record_rejection(self.id, candidate.attempt, verdict.issues)
        if candidate.attempt < self._team.config.max_retries and not verdict.insufficient:
            await ctx.send_message(Retry(replace(candidate, trace=trace), verdict.issues))
            return
        await ctx.yield_output(job.fallback(self._segment, trace))


def _routes_to(role: AgentName) -> Callable[[Any], bool]:
    return lambda job: isinstance(job, MomentJob) and job.route.writer is role


def segment_workflow(segment: Segment, team: AgentTeam, verifier: Verifier) -> Workflow:
    """Persona -> Language (non-English) -> Verifier, with the retry edge back to Persona."""
    persona = PersonaStep(segment, team)
    gate = VerifierStep(segment, team, verifier)
    builder = WorkflowBuilder(name=f"segment-{slug(segment)}", start_executor=persona)
    if segment.language is Language.EN:
        builder.add_edge(persona, gate)
    else:
        language = LanguageStep(segment, team)
        builder.add_edge(persona, language)
        builder.add_edge(language, gate)
    builder.add_edge(gate, persona)
    return builder.build()


def build_workflow(team: AgentTeam, segments: Sequence[Segment]) -> Workflow:
    """The graph for one moment: shared writers, then one sub-workflow per segment."""
    if not segments:
        raise ValueError("a workflow needs at least one segment")
    verifier = Verifier(team)
    orchestrator = Orchestrator()
    writers = {role: Writer(role, team, verifier) for role in WRITERS}
    builder = WorkflowBuilder(
        name="pitchmind-insights",
        description="Moment -> writer -> per-segment persona, language and verifier -> insights",
        start_executor=orchestrator,
    )
    builder.add_switch_case_edge_group(
        orchestrator,
        [
            Case(condition=_routes_to(AgentName.EXPLAIN), target=writers[AgentName.EXPLAIN]),
            Case(condition=_routes_to(AgentName.RECAP), target=writers[AgentName.RECAP]),
            Default(target=writers[AgentName.NARRATIVE]),
        ],
    )
    branches = [
        WorkflowExecutor(segment_workflow(s, team, verifier), id=f"segment_{slug(s)}", allow_direct_output=True)
        for s in segments
    ]
    for writer in writers.values():
        if len(branches) == 1:
            builder.add_edge(writer, branches[0])
        else:
            builder.add_fan_out_edges(writer, branches)
    return builder.build()

"""The agents service: wire messages in, insights out."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from pitchmind_contracts import AgentName, Insight, MatchEvent, MatchMeta, Moment, Overlay, Segment, StatSnapshot

from .agents import AgentTeam
from .context import MatchContext
from .routing import plan
from .segments import DEMO_SEGMENTS
from .telemetry import tracer
from .workflow import MomentJob, build_workflow

logger = logging.getLogger(__name__)

WireIn = MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay
KEEP_MATCHES = 2  # the live match plus the previous one (its late recap, redeliveries)


@dataclass
class _Run:
    """A moment being processed; a redelivery that arrives meanwhile waits for it."""

    done: asyncio.Event = field(default_factory=asyncio.Event)
    insights: tuple[Insight, ...] | None = None  # None if the run was interrupted


class AgentsService:
    """Keeps the shared match state and turns each moment into one insight per active segment."""

    def __init__(self, team: AgentTeam, segments: Sequence[Segment] = DEMO_SEGMENTS) -> None:
        self.team = team
        self.segments = tuple({s.key: s for s in segments}.values())
        self._contexts: dict[str, MatchContext] = {}
        self._published: dict[str, dict[str, tuple[Insight, ...]]] = {}  # match id -> moment id -> insights
        self._running: dict[tuple[str, str], _Run] = {}

    def context(self, match_id: str) -> MatchContext:
        if match_id not in self._contexts:
            self._contexts[match_id] = MatchContext(match_id)
            self._forget_old_matches()
        return self._contexts[match_id]

    def _forget_old_matches(self) -> None:
        """Bound memory when matches never stop (the cloud simulator loops M001, M002, ...).

        Not done at full time: the recap moment and redeliveries can still arrive after it.
        A match with a moment still being processed is kept.
        """
        busy = {match_id for match_id, _ in self._running}
        for old in list(self._contexts)[:-KEEP_MATCHES]:
            if old not in busy:
                self.close_match(old)

    def close_match(self, match_id: str) -> None:
        """Forget a finished match's state and published insights."""
        self._contexts.pop(match_id, None)
        self._published.pop(match_id, None)

    async def handle(self, msg: WireIn) -> list[Insight]:
        match msg:
            case Moment():
                return await self.process(msg)
            case Insight() | Overlay():
                return []  # downstream messages, not ours
            case _:
                self.context(msg.match_id).observe(msg)
                return []

    async def process(self, moment: Moment) -> list[Insight]:
        """All insights for a moment, in segment order."""
        order = {s.key: n for n, s in enumerate(self.segments)}
        insights = [insight async for insight in self.stream(moment)]
        return sorted(insights, key=lambda i: order.get(i.segment.key, len(order)))

    async def stream(self, moment: Moment) -> AsyncGenerator[Insight]:
        """Insights for one moment, each as soon as its segment is ready.

        A redelivered moment (at-least-once transport) replays the insights already published,
        with the same ids, instead of calling the agents again. A run that was interrupted
        before finishing is not remembered, so its redelivery runs the moment again.
        """
        published = self._published.setdefault(moment.match_id, {})
        if (done := published.get(moment.id)) is not None:
            for insight in done:
                yield insight
            return
        key = (moment.match_id, moment.id)
        if (running := self._running.get(key)) is not None:
            await running.done.wait()
            source = self.stream(moment) if running.insights is None else _replay(running.insights)
            async for insight in source:
                yield insight
            return

        run = self._running[key] = _Run()
        produced: list[Insight] = []
        try:
            async for insight in self._run(moment):
                produced.append(insight)
                yield insight
            run.insights = tuple(produced)
            published[moment.id] = run.insights
        finally:
            del self._running[key]
            run.done.set()

    async def _run(self, moment: Moment) -> AsyncGenerator[Insight]:
        ctx = self.context(moment.match_id)
        facts = ctx.facts_for(moment)
        ctx.observe(moment)
        chosen = plan(moment, self.segments, min_importance=self.team.config.min_importance)
        if not chosen.segments:
            logger.info("%s %s: skipped (%s)", moment.id, moment.kind, chosen.route.reason)
            return

        job = MomentJob(moment, facts, chosen.route, chosen.segments, time.perf_counter())
        span = tracer.start_span(
            "pitchmind.moment",
            attributes={
                "pitchmind.match_id": moment.match_id,
                "pitchmind.moment_id": moment.id,
                "pitchmind.moment_kind": moment.kind.value,
                "pitchmind.minute": moment.minute,
                "pitchmind.writer": str(chosen.route.writer),
                "pitchmind.segments": len(chosen.segments),
            },
        )
        queue: asyncio.Queue[Insight | None] = asyncio.Queue()
        with trace.use_span(span, end_on_exit=False):  # the workflow's spans become children of this one
            producer = asyncio.create_task(self._produce(job, queue, span))
        pending = {s.key: s for s in chosen.segments}
        fallbacks = 0
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.team.config.moment_deadline_s
            while pending:
                try:
                    insight = await asyncio.wait_for(queue.get(), timeout=max(deadline - loop.time(), 0))
                except TimeoutError:
                    logger.warning("%s missed its %gs deadline", moment.id, self.team.config.moment_deadline_s)
                    span.add_event("pitchmind.deadline", {"pitchmind.pending_segments": list(pending)})
                    break
                if insight is None:  # the workflow ended
                    break
                if pending.pop(insight.segment.key, None) is not None:  # the first insight per segment wins
                    fallbacks += insight.fallback
                    yield insight
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            # Every segment gets an insight, even if the workflow broke or ran out of time.
            with trace.use_span(span, end_on_exit=False):
                late = [job.fallback(segment, [AgentName.ORCHESTRATOR]) for segment in pending.values()]
            for insight in late:
                fallbacks += 1
                yield insight
        finally:
            producer.cancel()
            span.set_attribute("pitchmind.fallbacks", fallbacks)
            span.set_attribute("pitchmind.latency_ms", job.elapsed_ms())
            span.end()

    async def _produce(self, job: MomentJob, queue: asyncio.Queue[Insight | None], span: Span) -> None:
        try:
            async for event in build_workflow(self.team, job.segments).run(job, stream=True):
                if event.type == "output" and isinstance(event.data, Insight):
                    queue.put_nowait(event.data)
        except Exception as exc:
            logger.exception("workflow failed for %s; publishing templates for unfinished segments", job.moment.id)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"))
        finally:
            queue.put_nowait(None)


async def _replay(insights: Sequence[Insight]) -> AsyncGenerator[Insight]:
    for insight in insights:
        yield insight

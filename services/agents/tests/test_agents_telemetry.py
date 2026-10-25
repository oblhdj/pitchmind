"""OpenTelemetry spans and events, captured in memory."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from agent_framework.observability import OBSERVABILITY_SETTINGS, enable_instrumentation
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pitchmind_agents import AgentsConfig, AgentsService, AgentTeam, configure_tracing, mock_client_set
from pitchmind_agents import service as service_module
from pitchmind_agents import telemetry as telemetry_module
from pitchmind_agents.mock_llm import Responder
from pitchmind_agents.prompts import read_sections
from pitchmind_agents.testing import Scripted, plant, prime
from pitchmind_contracts import AgentName

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _in_memory_tracing() -> Iterator[None]:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    enable_instrumentation()
    yield
    EXPORTER.shutdown()  # later tests' spans are dropped instead of piling up here


def run_goal(overrides: dict[AgentName, Responder] | None = None, **config: Any) -> list[ReadableSpan]:
    EXPORTER.clear()
    service = AgentsService(AgentTeam(mock_client_set(overrides=overrides), AgentsConfig(**config)))
    asyncio.run(service.process(prime(service, "mom-M001-1")))  # Halvorsen's goal
    return list(EXPORTER.get_finished_spans())


def events(spans: list[ReadableSpan], name: str) -> list[dict[str, Any]]:
    return [dict(e.attributes or {}) for s in spans for e in s.events if e.name == name]


def moment_span(spans: list[ReadableSpan]) -> ReadableSpan:
    (span,) = [s for s in spans if s.name == "pitchmind.moment"]
    return span


def test_one_moment_is_one_trace_with_agent_spans() -> None:
    spans = run_goal()
    moment = moment_span(spans)
    attrs = dict(moment.attributes or {})
    assert attrs["pitchmind.moment_id"] == "mom-M001-1"
    assert attrs["pitchmind.writer"] == "narrative"
    assert (attrs["pitchmind.segments"], attrs["pitchmind.fallbacks"]) == (3, 0)
    assert {s.context.trace_id for s in spans} == {moment.context.trace_id}
    runs = [s for s in spans if s.name == "workflow.run"]
    assert any(r.parent is not None and r.parent.span_id == moment.context.span_id for r in runs)
    names = {s.name for s in spans}
    assert {"invoke_agent narrative", "invoke_agent persona", "invoke_agent language"} <= names
    assert {"executor.process segment_casual_ar_home", "executor.process verifier_casual_ar_home"} <= names


def test_verifier_rejections_are_span_events() -> None:
    writer = Scripted(AgentName.NARRATIVE, lambda d, _, n: plant("0.83")(d) if n == 1 else d)
    (rejected,) = events(run_goal({AgentName.NARRATIVE: writer}), "pitchmind.verifier.rejected")
    assert rejected["pitchmind.step"] == "narrative"
    assert rejected["pitchmind.issues"] == ("body states 0.83, which is not in FACTS",)


def test_judge_comments_stay_out_of_traces_unless_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = ["body states 0.83, which is not in FACTS", "judge: says Halvorsen scored a header"]
    tracer = trace.get_tracer("test")
    EXPORTER.clear()
    with tracer.start_as_current_span("step"):
        telemetry_module.record_rejection("persona", 0, issues)
    monkeypatch.setattr(OBSERVABILITY_SETTINGS, "enable_sensitive_data", True)
    with tracer.start_as_current_span("step"):
        telemetry_module.record_rejection("persona", 0, issues)
    plain, sensitive = events(list(EXPORTER.get_finished_spans()), "pitchmind.verifier.rejected")
    assert plain["pitchmind.issues"] == ("body states 0.83, which is not in FACTS",)
    assert plain["pitchmind.judge_issues"] == 1
    assert sensitive["pitchmind.issues"] == tuple(issues)


def test_fallbacks_are_span_events() -> None:
    spans = run_goal(disabled_agents=frozenset({AgentName.NARRATIVE}))
    fallbacks = events(spans, "pitchmind.fallback")
    assert len(fallbacks) == 3
    assert fallbacks[0]["pitchmind.agent_trace"] == ("orchestrator", "template")
    assert dict(moment_span(spans).attributes or {})["pitchmind.fallbacks"] == 3


def test_a_missed_deadline_is_traced() -> None:
    async def persona(prompt: str) -> str:
        if read_sections(prompt)["SEGMENT"]["language"] == "ar":
            await asyncio.sleep(5)
        return await Scripted(AgentName.PERSONA)(prompt)

    spans = run_goal({AgentName.PERSONA: persona}, moment_deadline_s=0.3)
    (deadline,) = events(spans, "pitchmind.deadline")
    assert deadline["pitchmind.pending_segments"] == ("casual|ar|club:home|player:*|metric:*",)


def test_a_broken_workflow_marks_the_moment_span_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object) -> object:
        raise RuntimeError("graph construction failed")

    monkeypatch.setattr(service_module, "build_workflow", explode)
    span = moment_span(run_goal())
    assert span.status.status_code is StatusCode.ERROR
    assert any(e.name == "exception" for e in span.events)


def test_foundry_tracing_uses_the_connection_string(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(telemetry_module, "configure_azure_monitor", lambda **kw: calls.append(kw))
    monkeypatch.setattr(telemetry_module, "enable_instrumentation", lambda **kw: calls.append(kw))
    asyncio.run(configure_tracing("foundry", connection_string="InstrumentationKey=00000000"))
    assert calls[0]["connection_string"] == "InstrumentationKey=00000000"
    assert calls[1] == {"enable_sensitive_data": False}


@pytest.mark.parametrize(("target", "console"), [("otlp", False), ("console", True)])
def test_otlp_and_console_tracing(monkeypatch: pytest.MonkeyPatch, target: str, console: bool) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(telemetry_module, "configure_otel_providers", lambda **kw: calls.append(kw))
    asyncio.run(configure_tracing(target, sensitive=True))  # type: ignore[arg-type]
    assert calls == [{"enable_console_exporters": console, "enable_sensitive_data": True}]


def test_foundry_tracing_needs_a_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    with pytest.raises(ValueError, match="APPLICATIONINSIGHTS_CONNECTION_STRING"):
        asyncio.run(configure_tracing("foundry", client=object()))

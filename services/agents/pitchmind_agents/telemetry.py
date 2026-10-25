"""OpenTelemetry tracing, exported to Microsoft Foundry (Application Insights).

Agent Framework emits GenAI spans for every agent call, chat request and workflow step
once instrumentation is on. This module adds one ``pitchmind.moment`` span around each
workflow run, plus events when the Verifier rejects a draft, the judge is unreachable,
a moment misses its deadline or a template is published, so a trace in Foundry reads:
moment -> workflow -> agents -> verdicts.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Literal

from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import (
    OBSERVABILITY_SETTINGS,
    configure_otel_providers,
    create_metric_views,
    create_resource,
    enable_instrumentation,
)
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

TraceTarget = Literal["foundry", "otlp", "console"]

tracer = trace.get_tracer("pitchmind_agents")


async def configure_tracing(
    target: TraceTarget,
    *,
    client: object | None = None,
    connection_string: str | None = None,
    sensitive: bool = False,
) -> None:
    """Start exporting traces.

    ``foundry`` uses ``APPLICATIONINSIGHTS_CONNECTION_STRING`` when set, otherwise asks the
    Foundry project behind ``client`` for its Application Insights connection.
    ``otlp`` follows the standard ``OTEL_EXPORTER_OTLP_*`` variables (e.g. Aspire dashboard).
    ``sensitive`` records prompts, replies and judge comments; use it only in development.
    """
    if target == "foundry":
        conn = connection_string or os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if conn:
            configure_azure_monitor(connection_string=conn, resource=create_resource(), views=create_metric_views())
            enable_instrumentation(enable_sensitive_data=sensitive)
        elif isinstance(client, FoundryChatClient):
            await client.configure_azure_monitor(enable_sensitive_data=sensitive)
        else:
            raise ValueError("Foundry tracing needs APPLICATIONINSIGHTS_CONNECTION_STRING or a Foundry chat client")
    else:
        configure_otel_providers(enable_console_exporters=target == "console", enable_sensitive_data=sensitive)


def record_rejection(where: str, attempt: int, issues: Sequence[str]) -> None:
    """Code-check issues are our own sentences; judge comments are model text, kept only when sensitive."""
    judge = [i for i in issues if i.startswith("judge:")]
    shown = list(issues) if OBSERVABILITY_SETTINGS.enable_sensitive_data else [i for i in issues if i not in judge]
    trace.get_current_span().add_event(
        "pitchmind.verifier.rejected",
        {
            "pitchmind.step": where,
            "pitchmind.attempt": attempt,
            "pitchmind.issues": shown,
            "pitchmind.judge_issues": len(judge),
        },
    )


def record_judge_unavailable(reason: str) -> None:
    trace.get_current_span().add_event("pitchmind.judge.unavailable", {"pitchmind.reason": reason})


def record_fallback(segment_key: str, trace_names: Sequence[str]) -> None:
    trace.get_current_span().add_event(
        "pitchmind.fallback",
        {"pitchmind.segment": segment_key, "pitchmind.agent_trace": list(trace_names)},
    )

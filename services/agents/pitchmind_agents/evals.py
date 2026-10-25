"""Evaluate generated insights: Foundry groundedness and fluency, plus numeric fidelity.

    python -m pitchmind_agents.evals                                  # mock insights, numeric fidelity only
    python -m pitchmind_agents.evals --llm foundry --foundry --env-file .env --markdown docs/EVALS.md

Each insight becomes an Agent Framework ``EvalItem``: the query names the moment and the
audience, the response is the headline and body fans see, and the context is the exact
``Facts`` the agents were given. Groundedness is judged against those facts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import EvalItem, EvalItemResult, EvalResults, EvalScoreResult, Evaluator, Message
from agent_framework.foundry import FoundryChatClient, FoundryEvals
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from pitchmind_contracts import AgentName, Insight, Language, Moment, Overlay, parse_wire

from .agents import AgentTeam, ClientSet
from .config import AgentsConfig
from .context import Facts, MatchContext
from .mock_llm import mock_client_set
from .numbers import extract_numbers, is_supported
from .prompts import LANGUAGE_NAMES
from .runtime import load_env_file, read_wire, replay
from .segments import parse_segments
from .service import AgentsService, WireIn

NUMERIC_FIDELITY = "numeric_fidelity"


@dataclass(frozen=True, slots=True)
class EvalCase:
    insight: Insight
    facts: Facts


def replay_facts(messages: Iterable[WireIn]) -> dict[str, Facts]:
    """The facts each moment's agents saw, rebuilt in the same order as ``AgentsService``."""
    contexts: dict[str, MatchContext] = {}
    facts: dict[str, Facts] = {}
    for msg in messages:
        if isinstance(msg, Insight | Overlay):
            continue
        ctx = contexts.setdefault(msg.match_id, MatchContext(msg.match_id))
        if isinstance(msg, Moment) and msg.id not in facts:
            facts[msg.id] = ctx.facts_for(msg)
        ctx.observe(msg)
    return facts


def build_cases(insights: Iterable[Insight], facts: Mapping[str, Facts]) -> list[EvalCase]:
    return [EvalCase(i, facts[i.moment_id]) for i in insights if i.moment_id is not None and i.moment_id in facts]


def to_eval_item(case: EvalCase) -> EvalItem:
    insight, facts = case.insight, case.facts
    segment = insight.segment
    query = (
        f"Write the {insight.kind.value} for the {facts.kind.value} moment in minute {facts.minute}, "
        f"for a {segment.persona.value} fan, in {LANGUAGE_NAMES[segment.language]}."
    )
    response = f"{insight.headline}\n{insight.body}"
    conversation = [Message(role="user", contents=[query]), Message(role="assistant", contents=[response])]
    return EvalItem(conversation=conversation, context=facts.model_dump_json())


def _language_of(query: str) -> Language:
    """The target language named at the end of a query built by ``to_eval_item``."""
    return next((lang for lang, name in LANGUAGE_NAMES.items() if query.endswith(f" in {name}.")), Language.EN)


class NumericFidelity:
    """Share of the numbers fans read that appear in the facts. 1.0 means every number is grounded.

    An Agent Framework ``Evaluator``, so it runs next to ``FoundryEvals`` on the same items.
    Unlike the Verifier it scores published text, template fallbacks included.
    """

    name = "PitchMind"

    async def evaluate(self, items: Sequence[EvalItem], *, eval_name: str = "Numeric fidelity") -> EvalResults:
        results: list[EvalItemResult] = []
        for index, item in enumerate(items):
            if not item.context:
                raise ValueError(f"item {index} has no facts in its context")
            allowed = Facts.model_validate_json(item.context).allowed_numbers()
            tokens = extract_numbers(item.response, _language_of(item.query))
            unsupported = [t.raw for t in tokens if not is_supported(t, allowed)]
            score = 1.0 - len(unsupported) / len(tokens) if tokens else 1.0
            passed = not unsupported
            results.append(
                EvalItemResult(
                    item_id=str(index),
                    status="pass" if passed else "fail",
                    scores=[
                        EvalScoreResult(
                            name=NUMERIC_FIDELITY,
                            score=score,
                            passed=passed,
                            sample={"numbers": [t.raw for t in tokens], "unsupported": unsupported},
                        )
                    ],
                    input_text=item.query,
                    output_text=item.response,
                )
            )
        passed_count = sum(r.is_passed for r in results)
        counts = {"passed": passed_count, "failed": len(results) - passed_count, "errored": 0}
        return EvalResults(
            provider=self.name,
            eval_id="numeric-fidelity",
            run_id=eval_name,
            status="completed",
            result_counts=counts,
            per_evaluator={NUMERIC_FIDELITY: counts},
            items=results,
        )


def foundry_evaluators(
    *,
    endpoint: str | None = None,
    model: str | None = None,
    credential: TokenCredential | None = None,
    env: Mapping[str, str] | None = None,
) -> FoundryEvals:
    """Foundry's built-in groundedness and fluency evaluators, judged by a model deployment."""
    env = os.environ if env is None else env
    endpoint = endpoint or env.get("FOUNDRY_PROJECT_ENDPOINT")
    model = model or env.get("FOUNDRY_EVAL_MODEL") or env.get("FOUNDRY_MODEL_STRONG")
    if not endpoint or not model:
        raise ValueError("set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_EVAL_MODEL (or FOUNDRY_MODEL_STRONG)")
    client = FoundryChatClient(
        project_endpoint=endpoint, model=model, credential=credential or DefaultAzureCredential()
    )
    return FoundryEvals(client=client, model=model, evaluators=[FoundryEvals.GROUNDEDNESS, FoundryEvals.FLUENCY])


@dataclass(frozen=True, slots=True)
class MetricRow:
    metric: str
    provider: str
    mean_score: float | None
    passed: int
    total: int
    report_url: str | None = None


@dataclass(frozen=True, slots=True)
class EvalReport:
    rows: list[MetricRow]
    pipeline: dict[str, float]
    failures: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # evaluators that could not run

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": [asdict(row) for row in self.rows],
            "pipeline": self.pipeline,
            "failures": self.failures,
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        lines = ["| Metric | Provider | Mean score | Passed |", "|---|---|---|---|"]
        for row in self.rows:
            score = "n/a" if row.mean_score is None else f"{row.mean_score:.2f}"
            lines.append(f"| {row.metric} | {row.provider} | {score} | {row.passed}/{row.total} |")
        lines += [f"\nEvaluator failed: {error}" for error in self.errors]
        p = self.pipeline
        lines += [
            "",
            "| Pipeline | Value |",
            "|---|---|",
            f"| Insights | {p['insights']:.0f} |",
            f"| Verified | {p['verified_rate']:.0%} |",
            f"| Template fallback | {p['fallback_rate']:.0%} |",
            f"| Accepted on first pass | {p['first_pass_rate']:.0%} |",
            f"| Latency p50 / p95 | {p['latency_p50_ms']:.0f} / {p['latency_p95_ms']:.0f} ms |",
        ]
        return "\n".join(lines) + "\n"


def _first_pass(insight: Insight) -> bool:
    """Published without a retry: no agent other than the Verifier appears twice in the trace."""
    agents = [a for a in insight.agent_trace if a is not AgentName.VERIFIER]
    return not insight.fallback and len(agents) == len(set(agents))


def pipeline_stats(insights: Sequence[Insight]) -> dict[str, float]:
    n = len(insights) or 1
    # Every insight a fan waited for, templates included, so timeouts show up in the percentiles.
    latencies = sorted(i.latency_ms for i in insights if i.latency_ms is not None) or [0]
    p95_index = min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))
    return {
        "insights": float(len(insights)),
        "verified_rate": sum(i.verified for i in insights) / n,
        "fallback_rate": sum(i.fallback for i in insights) / n,
        "first_pass_rate": sum(_first_pass(i) for i in insights) / n,
        "latency_p50_ms": float(statistics.median(latencies)),
        "latency_p95_ms": float(latencies[p95_index]),
    }


def _insight_id(item: EvalItemResult, cases: Sequence[EvalCase]) -> str:
    """Local evaluators number items by position; cloud providers use their own ids."""
    if item.item_id.isdigit() and int(item.item_id) < len(cases):
        return cases[int(item.item_id)].insight.id
    return item.item_id


def summarize(results: Sequence[EvalResults], cases: Sequence[EvalCase], errors: Sequence[str] = ()) -> EvalReport:
    rows: list[MetricRow] = []
    failures: list[dict[str, Any]] = []
    for result in results:
        scores: dict[str, list[EvalScoreResult]] = {}
        for item in result.items:
            for score in item.scores:
                scores.setdefault(score.name, []).append(score)
                if score.passed is False:
                    failures.append(
                        {
                            "metric": score.name,
                            "insight_id": _insight_id(item, cases),
                            "score": score.score,
                            "response": item.output_text,
                            "detail": score.sample,
                        }
                    )
        if scores:
            for name, values in scores.items():
                mean = statistics.fmean(s.score for s in values)
                passed = sum(bool(s.passed) for s in values)
                rows.append(MetricRow(name, result.provider, mean, passed, len(values), result.report_url))
        else:  # the provider only reported counts
            for name, counts in result.per_evaluator.items():
                total = counts.get("passed", 0) + counts.get("failed", 0)
                rows.append(MetricRow(name, result.provider, None, counts.get("passed", 0), total, result.report_url))
    return EvalReport(rows, pipeline_stats([c.insight for c in cases]), failures, list(errors))


async def evaluate_insights(
    cases: Sequence[EvalCase], evaluators: Sequence[Evaluator], *, eval_name: str = "PitchMind insights"
) -> EvalReport:
    """Run every evaluator; one that fails (e.g. Foundry unreachable) is reported, not fatal."""
    items = [to_eval_item(case) for case in cases]
    outcomes = await asyncio.gather(
        *(ev.evaluate(items, eval_name=eval_name) for ev in evaluators), return_exceptions=True
    )
    results: list[EvalResults] = []
    errors: list[str] = []
    for evaluator, outcome in zip(evaluators, outcomes, strict=True):
        if isinstance(outcome, EvalResults):
            results.append(outcome)
        elif isinstance(outcome, Exception):
            errors.append(f"{evaluator.name}: {type(outcome).__name__}: {outcome}")
        else:
            raise outcome  # cancellation
    return summarize(results, cases, errors)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pitchmind_agents.evals", description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=Path("data/mock/stream.jsonl"), help="wire JSONL with moments")
    parser.add_argument("--insights", type=Path, help="insights JSONL to score (default: generate them now)")
    parser.add_argument("--llm", choices=["mock", "foundry"], default="mock", help="model used to generate insights")
    parser.add_argument("--segments", default="demo", help='"demo", "all", or segment keys separated by ";"')
    parser.add_argument("--foundry", action="store_true", help="also run Foundry groundedness and fluency")
    parser.add_argument("--output", type=Path, help="write the report as JSON")
    parser.add_argument("--markdown", type=Path, help="write the report as a Markdown table")
    parser.add_argument("--env-file", type=Path, help="load KEY=VALUE lines, e.g. .env")
    args = parser.parse_args(argv)

    warnings.filterwarnings("ignore", message=r"\[EVALS\]")  # Agent Framework marks its eval API experimental
    if args.env_file:
        load_env_file(args.env_file)
    messages = list(read_wire(args.input))
    if args.insights:
        lines = args.insights.read_text(encoding="utf-8").splitlines()
        insights = [msg for line in lines if line.strip() and isinstance(msg := parse_wire(line), Insight)]
    else:
        clients: ClientSet
        if args.llm == "foundry":
            from .clients import foundry_client_set

            clients = foundry_client_set()
        else:
            clients = mock_client_set()
        service = AgentsService(AgentTeam(clients, AgentsConfig.from_env()), parse_segments(args.segments))
        insights = asyncio.run(replay(service, iter(messages)))

    evaluators: list[Evaluator] = [NumericFidelity()]
    if args.foundry:
        evaluators.append(foundry_evaluators())
    report = asyncio.run(evaluate_insights(build_cases(insights, replay_facts(messages)), evaluators))

    markdown = report.to_markdown()
    sys.stdout.write(markdown)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

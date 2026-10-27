"""Evaluate generated insights: Foundry groundedness and fluency, plus numeric fidelity.

    python -m pitchmind_agents.evals                                  # mock insights, numeric fidelity only
    python -m pitchmind_agents.evals --llm foundry --foundry --env-file .env --markdown docs/EVALS.md

Each insight becomes an Agent Framework ``EvalItem``: the query names the moment and the
audience, the response is the headline and body fans see, and the context is the exact
``Facts`` the agents were given. Groundedness is judged against those facts.

The CLI scores only the insights the agents wrote. A template fallback is fixed text that
code fills in, so judging it would credit the model with the template's quality; templates
count in the pipeline table (fallback rate, latency) instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import re
import statistics
import sys
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import EvalItem, EvalItemResult, EvalResults, EvalScoreResult, Evaluator, Message
from agent_framework.foundry import FoundryChatClient, FoundryEvals
from agent_framework_foundry._foundry_evals import _poll_eval_run  # no public API attaches to an existing run
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

logger = logging.getLogger(__name__)

NUMERIC_FIDELITY = "numeric_fidelity"
# Score ranges, so a 0-1 share is never read next to a 1-5 rating as if they compared.
SCALES = {NUMERIC_FIDELITY: "0-1", FoundryEvals.GROUNDEDNESS: "1-5", FoundryEvals.FLUENCY: "1-5"}
# Foundry judges 2 metrics x N items on a rate-limited deployment: its 180 s default times out.
FOUNDRY_TIMEOUT_S = 1800.0
FOUNDRY_POLL_S = 10.0
ERROR_MAX = 240  # characters of an error line in the report


@dataclass(frozen=True, slots=True)
class EvalCase:
    insight: Insight
    facts: Facts

    @property
    def response(self) -> str:
        """The text fans read, as the judges see it."""
        return f"{self.insight.headline}\n{self.insight.body}"


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
    """One case per insight whose moment has facts; ``main`` reports the ones it drops."""
    return [EvalCase(i, facts[i.moment_id]) for i in insights if i.moment_id is not None and i.moment_id in facts]


def to_eval_item(case: EvalCase) -> EvalItem:
    insight, facts = case.insight, case.facts
    segment = insight.segment
    query = (
        f"Write the {insight.kind.value} for the {facts.kind.value} moment in minute {facts.minute}, "
        f"for a {segment.persona.value} fan, in {LANGUAGE_NAMES[segment.language]}."
    )
    conversation = [Message(role="user", contents=[query]), Message(role="assistant", contents=[case.response])]
    return EvalItem(conversation=conversation, context=facts.model_dump_json())


def _language_of(query: str) -> Language:
    """The target language named at the end of a query built by ``to_eval_item``."""
    for language, name in LANGUAGE_NAMES.items():
        if query.endswith(f" in {name}."):
            return language
    # Guessing English would parse Arabic or French numbers with the wrong rules.
    raise ValueError(f"no target language at the end of the query: {query!r}")


class NumericFidelity:
    """Share of the numbers fans read that appear in the facts. 1.0 means every number is grounded.

    An Agent Framework ``Evaluator``, so it runs next to ``FoundryEvals`` on the same items.
    It re-checks published text with the Verifier's own number parser: a regression check that
    nothing slipped past the Verifier, not evidence independent of it.
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


class TraceableFoundryEvals:
    """``FoundryEvals``, with each result item carrying the response it judged.

    Foundry numbers the output items of a dataset run from 1 and leaves their output text
    empty, so neither says which insight a score belongs to. Each item's data-source row does:
    the run's items are listed once more and their responses copied onto the results.
    """

    def __init__(
        self,
        evals: FoundryEvals,
        client: FoundryChatClient,
        *,
        run: tuple[str, str] | None = None,
        timeout_s: float = FOUNDRY_TIMEOUT_S,
    ) -> None:
        self._evals = evals
        self._client = client
        self._run = run  # (eval id, run id) of a run started earlier: collect it instead of starting one
        self._timeout_s = timeout_s
        self.name = evals.name

    async def evaluate(self, items: Sequence[EvalItem], *, eval_name: str = "PitchMind insights") -> EvalResults:
        if self._run is None:
            results = await self._evals.evaluate(items, eval_name=eval_name)
        else:
            eval_id, run_id = self._run
            results = await _poll_eval_run(
                self._client.client, eval_id, run_id, FOUNDRY_POLL_S, self._timeout_s, provider=self.name
            )
        if results.status != "completed" or not results.items:
            return results
        responses: dict[str, str] = {}
        try:
            page = await self._client.client.evals.runs.output_items.list(
                run_id=results.run_id, eval_id=results.eval_id
            )
            async for output in page:
                response = (output.datasource_item or {}).get("response")
                if isinstance(response, str):
                    responses[output.id] = response
        except Exception:  # the scores stand; only their link to an insight is lost, and the report shows it
            logger.warning("could not list the Foundry run's items; failures will show Foundry item ids", exc_info=True)
        for item in results.items:
            item.output_text = item.output_text or responses.get(item.item_id)
        return results


def foundry_evaluators(
    *,
    endpoint: str | None = None,
    model: str | None = None,
    credential: TokenCredential | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float = FOUNDRY_TIMEOUT_S,
    run: tuple[str, str] | None = None,
) -> TraceableFoundryEvals:
    """Foundry's built-in groundedness and fluency evaluators, judged by a model deployment.

    With ``run`` (eval id, run id), the results of that earlier run are collected instead.
    """
    env = os.environ if env is None else env
    endpoint = endpoint or env.get("FOUNDRY_PROJECT_ENDPOINT")
    model = model or env.get("FOUNDRY_EVAL_MODEL") or env.get("FOUNDRY_MODEL_STRONG")
    if not endpoint or not model:
        raise ValueError("set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_EVAL_MODEL (or FOUNDRY_MODEL_STRONG)")
    client = FoundryChatClient(
        project_endpoint=endpoint, model=model, credential=credential or DefaultAzureCredential()
    )
    evals = FoundryEvals(
        client=client,
        model=model,
        evaluators=[FoundryEvals.GROUNDEDNESS, FoundryEvals.FLUENCY],
        poll_interval=FOUNDRY_POLL_S,
        timeout=timeout_s,
    )
    return TraceableFoundryEvals(evals, client, run=run, timeout_s=timeout_s)


@dataclass(frozen=True, slots=True)
class MetricRow:
    metric: str
    provider: str
    mean_score: float | None
    passed: int
    total: int
    errored: int = 0  # items the evaluator returned no usable score for
    note: str = ""

    @property
    def scale(self) -> str:
        return SCALES.get(self.metric, "?")


@dataclass(frozen=True, slots=True)
class EvalReport:
    rows: list[MetricRow]
    pipeline: dict[str, float]
    failures: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # evaluators that could not run or came back short
    # Portal links to the cloud runs, for whoever ran the eval. Kept out of the published
    # report: they carry subscription and resource ids.
    links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": [{**asdict(row), "scale": row.scale} for row in self.rows],
            "pipeline": self.pipeline,
            "failures": self.failures,
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        lines = ["| Metric | Provider | Scale | Mean score | Passed | No score |", "|---|---|---|---|---|---|"]
        for row in self.rows:
            score = "n/a" if row.mean_score is None else f"{row.mean_score:.2f}"
            cells = [row.metric, row.provider, row.scale, score, f"{row.passed}/{row.total}", str(row.errored)]
            lines.append(f"| {' | '.join(cells)} |")
        lines += [f"\n{row.metric}: {row.note}" for row in self.rows if row.note]
        lines += [f"\nProblem: {error}" for error in self.errors]
        p = self.pipeline
        lines += [
            "",
            "| Pipeline | Value |",
            "|---|---|",
            f"| Moments | {p['moments']:.0f} |",
            f"| Insights | {p['insights']:.0f} |",
            f"| Written by the agents | {p['written']:.0f} ({p['written_rate']:.0%}) |",
            f"| Template fallback | {p['fallbacks']:.0f} ({p['fallback_rate']:.0%}) |",
            f"| Accepted on first pass | {p['first_pass_rate']:.0%} |",
            f"| Latency p50 / p95 | {p['latency_p50_ms']:.0f} / {p['latency_p95_ms']:.0f} ms |",
        ]
        return "\n".join(lines) + "\n"


def _first_pass(insight: Insight) -> bool:
    """Published without a retry: no agent other than the Verifier appears twice in the trace."""
    agents = [a for a in insight.agent_trace if a is not AgentName.VERIFIER]
    return not insight.fallback and len(agents) == len(set(agents))


def _percentile(ordered: Sequence[int], q: float) -> float:
    """Nearest rank: the smallest value that at least ``q`` of the values do not exceed."""
    return float(ordered[max(0, math.ceil(q * len(ordered)) - 1)])


def pipeline_stats(insights: Sequence[Insight]) -> dict[str, float]:
    n = len(insights)
    fallbacks = sum(i.fallback for i in insights)
    # Every insight a fan waited for, templates included, so timeouts show up in the percentiles.
    latencies = sorted(i.latency_ms for i in insights if i.latency_ms is not None) or [0]

    def share(count: int) -> float:
        return count / n if n else 0.0

    return {
        # A moment's insights share one writer run, so moments are the real sample size.
        "moments": float(len({i.moment_id for i in insights})),
        "insights": float(n),
        "written": float(n - fallbacks),
        "written_rate": share(n - fallbacks),
        "fallbacks": float(fallbacks),
        "fallback_rate": share(fallbacks),
        "first_pass_rate": share(sum(_first_pass(i) for i in insights)),
        "latency_p50_ms": float(statistics.median(latencies)),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


_URL = re.compile(r"https?://\S+")


def _clean(text: str) -> str:
    """An error line fit to publish: no URLs (they name Azure resources), one line, bounded."""
    flat = " ".join(_URL.sub("<url>", text).split())
    return flat if len(flat) <= ERROR_MAX else flat[: ERROR_MAX - 1] + "…"


def _usable(score: EvalScoreResult) -> float | None:
    """The score as a number, or None for an item the provider could not judge."""
    value: object = score.score
    if score.passed is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _case_for(item: EvalItemResult, cases: Sequence[EvalCase], *, positional: bool) -> EvalCase | None:
    """The case a result item belongs to.

    Local evaluators number items by position. Cloud providers use ids of their own, so their
    items are matched on the response text instead, ignoring whitespace.
    """
    if positional:
        index = int(item.item_id) if item.item_id.isdigit() else -1
        return cases[index] if 0 <= index < len(cases) else None
    if not item.output_text:
        return None
    text = " ".join(item.output_text.split())
    return next((c for c in cases if " ".join(c.response.split()) == text), None)


def _numbers_note(scores: Sequence[EvalScoreResult]) -> str:
    counts = [len(s.sample.get("numbers", [])) for s in scores if s.sample is not None]
    return f"{sum(counts)} numbers checked; {sum(c == 0 for c in counts)} insights had none and pass by default"


def _language_note(judged: Sequence[tuple[EvalCase | None, float]]) -> str:
    """Mean score per language, since a judge may rate languages differently."""
    by_language: dict[Language, list[float]] = {}
    for case, value in judged:
        if case is not None:
            by_language.setdefault(case.insight.segment.language, []).append(value)
    if len(by_language) < 2:
        return ""
    parts = [f"{lang.value} {statistics.fmean(v):.2f} (n={len(v)})" for lang, v in sorted(by_language.items())]
    return "by language: " + ", ".join(parts)


def summarize(
    results: Sequence[EvalResults],
    cases: Sequence[EvalCase],
    errors: Sequence[str] = (),
    published: Sequence[Insight] | None = None,
) -> EvalReport:
    """The report. ``published`` (default: the cases' insights) feeds the pipeline table, so
    insights that were not scored, such as template fallbacks, still count there."""
    rows: list[MetricRow] = []
    failures: list[dict[str, Any]] = []
    problems = list(errors)
    links: list[str] = []
    for result in results:
        if result.report_url:
            links.append(result.report_url)
        if result.status != "completed":
            detail = f": {result.error}" if result.error else ""
            # A run that timed out keeps going in the cloud: say how to collect it without paying twice.
            later = f"; collect it with --foundry-run {result.eval_id}/{result.run_id}" if result.run_id else ""
            problems.append(_clean(f"{result.provider} run {result.status}{detail}{later}"))
            continue
        per_metric: dict[str, list[tuple[EvalItemResult, EvalScoreResult]]] = {}
        for item in result.items:
            for score in item.scores:
                per_metric.setdefault(score.name, []).append((item, score))
        if not per_metric:  # the provider only reported counts
            if not result.per_evaluator:
                problems.append(f"{result.provider} returned no results")
            for name, counts in result.per_evaluator.items():
                passed, failed = counts.get("passed", 0), counts.get("failed", 0)
                total = passed + failed + counts.get("errored", 0)
                rows.append(MetricRow(name, result.provider, None, passed, total, errored=total - passed - failed))
            continue
        if len(result.items) < len(cases):
            problems.append(f"{result.provider} returned {len(result.items)} of {len(cases)} items")
        total = max(len(cases), len(result.items))
        positional = result.provider == NumericFidelity.name
        for name, scored in per_metric.items():
            judged: list[tuple[EvalItemResult, EvalScoreResult, float, EvalCase | None]] = []
            for item, score in scored:
                if (value := _usable(score)) is not None:
                    judged.append((item, score, value, _case_for(item, cases, positional=positional)))
            values = [value for _, _, value, _ in judged]
            failed_items = [(item, score, value, case) for item, score, value, case in judged if score.passed is False]
            passed = len(values) - len(failed_items)
            mean = statistics.fmean(values) if values else None
            notes = [_numbers_note([s for _, s in scored])] if name == NUMERIC_FIDELITY else []
            notes.append(_language_note([(case, value) for _, _, value, case in judged]))
            note = "; ".join(n for n in notes if n)
            errored = total - len(values)
            rows.append(MetricRow(name, result.provider, mean, passed, total, errored=errored, note=note))
            for item, score, value, case in failed_items:
                failures.append(
                    {
                        "metric": name,
                        "insight_id": case.insight.id if case else f"{result.provider} item {item.item_id}",
                        "score": value,
                        "response": case.response if case else item.output_text,
                        "detail": score.sample,
                    }
                )
    insights = [c.insight for c in cases] if published is None else list(published)
    return EvalReport(rows, pipeline_stats(insights), failures, problems, links)


async def evaluate_insights(
    cases: Sequence[EvalCase],
    evaluators: Sequence[Evaluator],
    *,
    eval_name: str = "PitchMind insights",
    published: Sequence[Insight] | None = None,
    errors: Sequence[str] = (),
) -> EvalReport:
    """Run every evaluator; one that fails (e.g. Foundry unreachable) is reported, not fatal."""
    problems = list(errors)
    results: list[EvalResults] = []
    if not cases:
        problems.append("no insights to score")
    else:
        items = [to_eval_item(case) for case in cases]
        outcomes = await asyncio.gather(
            *(ev.evaluate(items, eval_name=eval_name) for ev in evaluators), return_exceptions=True
        )
        for evaluator, outcome in zip(evaluators, outcomes, strict=True):
            if isinstance(outcome, EvalResults):
                results.append(outcome)
            elif isinstance(outcome, Exception):
                problems.append(_clean(f"{evaluator.name}: {type(outcome).__name__}: {outcome}"))
            else:
                raise outcome  # cancellation
    return summarize(results, cases, problems, published)


def load_insights(path: Path) -> list[Insight]:
    """The insights in a wire JSONL file; other messages (e.g. a recorded live feed) are skipped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [msg for line in lines if line.strip() and isinstance(msg := parse_wire(line), Insight)]


def generate(llm: str, segments: str, messages: Sequence[WireIn], save: Path | None = None) -> list[Insight]:
    """Run the agents over the match; with ``save``, each insight is written as it arrives."""
    clients: ClientSet
    if llm == "foundry":
        from .clients import foundry_client_set

        clients = foundry_client_set()
    else:
        clients = mock_client_set()
    config = AgentsConfig.from_env()
    print(f"generating with {config}", file=sys.stderr)
    service = AgentsService(AgentTeam(clients, config), parse_segments(segments))
    if save is None:
        return asyncio.run(replay(service, iter(messages)))
    # Written under a temporary name and renamed at the end, so a file that exists is a full run.
    partial = save.with_name(f"{save.name}.partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("w", encoding="utf-8") as f:

        def write(insight: Insight) -> None:
            f.write(insight.model_dump_json() + "\n")
            f.flush()

        insights = asyncio.run(replay(service, iter(messages), on_insight=write))
    partial.replace(save)
    return insights


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pitchmind_agents.evals", description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=Path("data/mock/stream.jsonl"), help="wire JSONL with moments")
    parser.add_argument("--insights", type=Path, help="insights JSONL to score (default: generate them now)")
    parser.add_argument("--llm", choices=["mock", "foundry"], default="mock", help="model used to generate insights")
    parser.add_argument("--segments", default="demo", help='"demo", "all", or segment keys separated by ";"')
    parser.add_argument("--save-insights", type=Path, help="write generated insights to this JSONL as they arrive")
    parser.add_argument("--foundry", action="store_true", help="also run Foundry groundedness and fluency")
    parser.add_argument("--judge-model", help="Foundry deployment that judges (default: FOUNDRY_EVAL_MODEL)")
    parser.add_argument(
        "--foundry-timeout", type=float, default=FOUNDRY_TIMEOUT_S, help="seconds to wait for the Foundry run"
    )
    parser.add_argument(
        "--foundry-run", metavar="EVAL_ID/RUN_ID", help="collect a Foundry run started earlier (same insights)"
    )
    parser.add_argument("--output", type=Path, help="write the report as JSON")
    parser.add_argument("--markdown", type=Path, help="write the report as a Markdown table")
    parser.add_argument("--env-file", type=Path, help="load KEY=VALUE lines, e.g. .env")
    args = parser.parse_args(argv)
    if args.insights and args.save_insights:
        parser.error("--save-insights only applies to insights generated now, not to --insights")
    run: tuple[str, str] | None = None
    if args.foundry_run:
        eval_id, _, run_id = args.foundry_run.partition("/")
        if not (args.foundry and args.insights and eval_id and run_id):
            parser.error("--foundry-run takes EVAL_ID/RUN_ID and needs --foundry and the --insights that run judged")
        run = (eval_id, run_id)

    warnings.filterwarnings("ignore", message=r"\[EVALS\]")  # Agent Framework marks its eval API experimental
    if args.env_file:
        load_env_file(args.env_file)
    messages = list(read_wire(args.input))
    # Built before generating, so a missing setting fails now rather than after the model calls.
    evaluators: list[Evaluator] = [NumericFidelity()]
    if args.foundry:
        evaluators.append(foundry_evaluators(model=args.judge_model, timeout_s=args.foundry_timeout, run=run))
    insights = (
        load_insights(args.insights)
        if args.insights
        else generate(args.llm, args.segments, messages, args.save_insights)
    )

    cases = build_cases(insights, replay_facts(messages))
    problems = []
    if dropped := len(insights) - len(cases):
        problems.append(f"not scored, their moment is not in --input: {dropped} insight(s)")
    written = [case for case in cases if not case.insight.fallback]
    report = asyncio.run(evaluate_insights(written, evaluators, published=insights, errors=problems))

    markdown = report.to_markdown()
    sys.stdout.write(markdown)
    for link in report.links:
        print(f"Foundry report (private): {link}", file=sys.stderr)
    # Markdown first: it cannot fail to serialize, so a paid cloud run is never lost.
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

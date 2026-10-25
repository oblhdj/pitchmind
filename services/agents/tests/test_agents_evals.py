"""Evaluations: numeric fidelity locally, Foundry groundedness and fluency through a captured payload."""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from agent_framework import EvalItem, EvalResults
from azure.core.credentials import AccessToken
from pitchmind_agents import AgentsService, AgentTeam, Draft, mock_client_set
from pitchmind_agents.evals import (
    EvalCase,
    NumericFidelity,
    build_cases,
    evaluate_insights,
    foundry_evaluators,
    pipeline_stats,
    replay_facts,
    to_eval_item,
)
from pitchmind_agents.evals import main as evals_main
from pitchmind_agents.runtime import replay
from pitchmind_agents.testing import MOCK_STREAM, Scripted, hand_written_insights, mock_messages, prime
from pitchmind_contracts import AgentName, Insight

pytestmark = pytest.mark.filterwarnings(r"ignore:\[EVALS\]")

FACTS = replay_facts(mock_messages())
HAND_WRITTEN = hand_written_insights()

# Numbers a writer might *derive* from the facts (0.38 xG -> "4 out of 10", 0.12 xG -> "12%").
# They read naturally but the pipeline never produced them, so they must be caught.
DERIVED = {
    "ins-M001-1-beginner_fr": " Une occasion de ce type finit au fond environ 4 fois sur 10.",
    "ins-M001-9-casual_ar": " فرصة نسبة نجاحها 12% فقط.",
}


def with_derived_numbers() -> list[Insight]:
    return [i.model_copy(update={"body": i.body + DERIVED[i.id]}) if i.id in DERIVED else i for i in HAND_WRITTEN]


def test_hand_written_insights_are_fully_grounded() -> None:
    report = asyncio.run(evaluate_insights(build_cases(HAND_WRITTEN, FACTS), [NumericFidelity()]))
    (row,) = report.rows
    assert (row.metric, row.passed, row.total) == ("numeric_fidelity", 31, 31)
    assert report.failures == []


def test_numeric_fidelity_catches_derived_numbers() -> None:
    report = asyncio.run(evaluate_insights(build_cases(with_derived_numbers(), FACTS), [NumericFidelity()]))
    (row,) = report.rows
    assert (row.passed, row.total) == (29, 31)
    unsupported = {f["insight_id"]: f["detail"]["unsupported"] for f in report.failures}
    assert unsupported == {"ins-M001-1-beginner_fr": ["4", "10"], "ins-M001-9-casual_ar": ["12"]}


def test_the_verifier_keeps_published_text_grounded_when_agents_invent_numbers() -> None:
    def invent(d: Draft, prompt: str, _: int) -> Draft:
        if "## FEEDBACK" in prompt:
            return d
        return d.model_copy(update={"body": f"{d.body} Chances like that go in ninety-nine times out of a hundred."})

    service = AgentsService(
        AgentTeam(mock_client_set(overrides={AgentName.PERSONA: Scripted(AgentName.PERSONA, invent)}))
    )
    insights = asyncio.run(replay(service, mock_messages()))
    report = asyncio.run(evaluate_insights(build_cases(insights, FACTS), [NumericFidelity()]))
    (row,) = report.rows
    assert row.passed == row.total and row.mean_score == 1.0
    assert report.pipeline["first_pass_rate"] == 0.0  # every segment needed the Verifier's retry
    assert report.pipeline["fallback_rate"] == 0.0


def test_pipeline_stats_count_retries_fallbacks_and_their_latency() -> None:
    first = next(i for i in HAND_WRITTEN if not i.fallback)
    o, n, v, p = AgentName.ORCHESTRATOR, AgentName.NARRATIVE, AgentName.VERIFIER, AgentName.PERSONA
    retried = first.model_copy(update={"agent_trace": [o, n, v, n, v, p, v], "latency_ms": 100})
    clean = first.model_copy(update={"agent_trace": [o, n, v, p, v], "latency_ms": 100})
    timed_out = first.model_copy(update={"fallback": True, "agent_trace": [o, AgentName.TEMPLATE], "latency_ms": 12000})
    stats = pipeline_stats([clean, retried, timed_out, clean])
    assert stats["first_pass_rate"] == 0.5
    assert stats["fallback_rate"] == 0.25
    assert stats["latency_p95_ms"] == 12000  # the template the fan waited 12 s for counts


class Broken:
    name = "Broken provider"

    async def evaluate(self, items: Sequence[EvalItem], *, eval_name: str) -> EvalResults:
        raise ConnectionError("Foundry unreachable")


def test_a_failing_evaluator_does_not_lose_the_other_results() -> None:
    report = asyncio.run(evaluate_insights(build_cases(HAND_WRITTEN, FACTS), [NumericFidelity(), Broken()]))
    assert [row.metric for row in report.rows] == ["numeric_fidelity"]
    assert report.errors == ["Broken provider: ConnectionError: Foundry unreachable"]
    assert "Evaluator failed: Broken provider" in report.to_markdown()


def test_replayed_facts_match_what_the_service_saw() -> None:
    service = AgentsService(AgentTeam(mock_client_set()))
    full_time = prime(service, "mom-M001-10")
    assert service.context(full_time.match_id).facts_for(full_time) == FACTS[full_time.id]
    facts = FACTS["mom-M001-10"]
    assert "phase" in [km.kind for km in facts.key_moments]  # the half-time score is a fact at full time
    assert 0.0 in facts.allowed_numbers()
    assert 10.0 in FACTS["mom-M001-6"].allowed_numbers()  # from the metric name home_shots_prev_10min


class StopEval(Exception):
    pass


class FakeRuns:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        raise StopEval


class FakeEvals:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        self.runs = FakeRuns()

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(id="eval-1")


def test_foundry_groundedness_is_judged_against_the_facts() -> None:
    from agent_framework.foundry import FoundryEvals

    api = SimpleNamespace(evals=FakeEvals())
    evaluators = FoundryEvals(
        client=cast(Any, api), model="judge-model", evaluators=[FoundryEvals.GROUNDEDNESS, FoundryEvals.FLUENCY]
    )
    case = EvalCase(HAND_WRITTEN[0], FACTS[HAND_WRITTEN[0].moment_id or ""])
    with pytest.raises(StopEval):
        asyncio.run(evaluators.evaluate([to_eval_item(case)]))

    criteria = {c["name"]: c for c in api.evals.kwargs["testing_criteria"]}
    assert set(criteria) == {"groundedness", "fluency"}
    assert criteria["groundedness"]["data_mapping"]["context"] == "{{item.context}}"
    assert criteria["fluency"]["initialization_parameters"] == {"deployment_name": "judge-model"}
    (row,) = api.evals.runs.kwargs["data_source"]["source"]["content"]
    assert row["item"]["response"] == f"{case.insight.headline}\n{case.insight.body}"
    assert json.loads(row["item"]["context"])["metrics"]["xg"] == 0.38
    assert "analyst fan, in English" in row["item"]["query"]


class FakeCredential:
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken("token", 0)


def test_foundry_evaluators_need_endpoint_and_judge_model() -> None:
    with pytest.raises(ValueError, match="FOUNDRY_EVAL_MODEL"):
        foundry_evaluators(env={})
    evaluators = foundry_evaluators(
        env={
            "FOUNDRY_PROJECT_ENDPOINT": "https://demo.services.ai.azure.com/api/projects/p",
            "FOUNDRY_MODEL_STRONG": "m",
        },
        credential=FakeCredential(),
    )
    assert evaluators.name == "Microsoft Foundry"


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    out_json, out_md = tmp_path / "evals.json", tmp_path / "EVALS.md"
    insights = tmp_path / "insights.jsonl"
    insights.write_text("".join(i.model_dump_json() + "\n" for i in with_derived_numbers()), encoding="utf-8")
    args = ["--input", str(MOCK_STREAM), "--insights", str(insights), "--output", str(out_json)]
    assert evals_main([*args, "--markdown", str(out_md)]) == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["metrics"][0]["metric"] == "numeric_fidelity"
    assert len(report["failures"]) == 2 and report["errors"] == []
    assert "| Accepted on first pass |" in out_md.read_text(encoding="utf-8")

"""The Agent Framework workflow, driven offline by scripted chat clients."""

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import pytest
from pitchmind_agents import AgentsConfig, AgentsService, AgentTeam, ClientSet, Draft, JudgeVerdict, mock_client_set
from pitchmind_agents import workflow as workflow_module
from pitchmind_agents.insights import build_insight
from pitchmind_agents.mock_llm import Responder
from pitchmind_agents.prompts import read_sections
from pitchmind_agents.testing import Scripted, plant, run_moment
from pitchmind_contracts import AgentName, Insight, InsightKind

ORCH, E, N, R = AgentName.ORCHESTRATOR, AgentName.EXPLAIN, AgentName.NARRATIVE, AgentName.RECAP
P, L, V, T = AgentName.PERSONA, AgentName.LANGUAGE, AgentName.VERIFIER, AgentName.TEMPLATE
EN_KEY = "analyst|en|club:*|player:*|metric:*"
AR_KEY = "casual|ar|club:home|player:*|metric:*"
FR_KEY = "beginner|fr|club:*|player:*|metric:*"


def make_service(overrides: Mapping[AgentName, Responder] | None = None, **config: Any) -> AgentsService:
    return AgentsService(AgentTeam(mock_client_set(overrides=overrides), AgentsConfig(**config)))


def segment_of(prompt: str) -> str:
    key: str = read_sections(prompt)["SEGMENT"]["key"]
    return key


def test_happy_path_routes_personalises_and_verifies() -> None:
    insights = run_moment(make_service(), "mom-M001-1")  # goal by A9: the H10 player-focus fan gets nothing
    assert set(insights) == {EN_KEY, AR_KEY, FR_KEY}
    for insight in insights.values():
        assert insight.verified and not insight.fallback
        assert insight.kind is InsightKind.COMMENTARY
        assert insight.claims[0].metrics["xg"] == 0.38  # values copied from the moment by code
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, P, V]
    assert insights[AR_KEY].agent_trace == [ORCH, N, V, P, L, V]  # Language only for non-English
    assert insights[EN_KEY].id == "ins-M001-1-analyst_en"


def test_routes_by_moment_kind() -> None:
    service = make_service()
    explain = run_moment(service, "mom-M001-2")[EN_KEY]
    assert (explain.kind, explain.agent_trace[1]) == (InsightKind.EXPLANATION, E)
    recap = run_moment(service, "mom-M001-4")[EN_KEY]
    assert (recap.kind, recap.agent_trace[1]) == (InsightKind.RECAP, R)


def test_stat_alerts_skip_the_llm() -> None:
    writer = Scripted(N)
    assert run_moment(make_service({N: writer}), "mom-M001-7") == {}
    assert writer.prompts == []


def test_writer_retries_once_with_verifier_feedback() -> None:
    writer = Scripted(N, lambda d, _, n: plant("0.83")(d) if n == 1 else d)
    insights = run_moment(make_service({N: writer}), "mom-M001-1")
    assert not insights[EN_KEY].fallback
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, N, V, P, V]
    assert "body states 0.83, which is not in FACTS" in writer.prompts[1]


def test_demo_plant_is_caught_by_the_verifier_and_never_reaches_fans() -> None:
    """The failure-recovery demo: PITCHMIND_DEMO_PLANT hallucinates a number on the first draft."""
    writer = Scripted(N)
    insights = run_moment(make_service({N: writer}, demo_plant=True), "mom-M001-1")
    assert "body states 0.99, which is not in FACTS" in writer.prompts[1]
    for insight in insights.values():
        assert not insight.fallback and insight.verified and "0.99" not in insight.body
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, N, V, P, V]
    assert AgentsConfig.from_env({"PITCHMIND_DEMO_PLANT": "1"}).demo_plant


def test_writer_wrong_twice_falls_back_to_template_everywhere() -> None:
    writer = Scripted(N, lambda d, _, n: plant("0.83")(d))
    insights = run_moment(make_service({N: writer}), "mom-M001-1")
    assert len(writer.prompts) == 2
    for insight in insights.values():
        assert insight.fallback and insight.verified
        assert insight.claims[0].evidence == [130, 131, 132]
        assert insight.agent_trace == [ORCH, N, V, N, V, T]
    assert insights[EN_KEY].body == "Goal for Harbour United: Halvorsen scores after 9 minutes."
    assert insights[AR_KEY].headline == "هدف!"
    assert insights[AR_KEY].body.startswith("هدف في الدقيقة 9 لصالح Harbour United.")
    assert insights[FR_KEY].body.startswith("But à la 9e minute pour Harbour United.")


def test_persona_rejection_loops_back_once() -> None:
    def edit(d: Draft, prompt: str, _: int) -> Draft:
        first_try_for_en = segment_of(prompt) == EN_KEY and "## FEEDBACK" not in prompt
        return plant("0.99")(d) if first_try_for_en else d

    insights = run_moment(make_service({P: Scripted(P, edit)}), "mom-M001-1")
    assert not insights[EN_KEY].fallback
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, P, V, P, V]
    assert insights[AR_KEY].agent_trace == [ORCH, N, V, P, L, V]


def test_persona_wrong_twice_only_affects_its_segment() -> None:
    def edit(d: Draft, prompt: str, _: int) -> Draft:
        return plant("0.99")(d) if segment_of(prompt) == EN_KEY else d

    insights = run_moment(make_service({P: Scripted(P, edit)}), "mom-M001-1")
    assert insights[EN_KEY].fallback
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, P, V, P, V, T]
    assert not insights[AR_KEY].fallback and not insights[FR_KEY].fallback


def test_persona_writing_numbers_as_words_is_caught() -> None:
    def edit(d: Draft, prompt: str, _: int) -> Draft:
        if "## FEEDBACK" in prompt:
            return d
        return d.model_copy(update={"body": f"{d.body} Chances like that go in four times out of ten."})

    insights = run_moment(make_service({P: Scripted(P, edit)}), "mom-M001-1")
    assert all(not i.fallback for i in insights.values())
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, P, V, P, V]
    assert "four times" not in insights[EN_KEY].body


def test_killed_agent_falls_back_and_recovers() -> None:
    service = make_service(disabled_agents=frozenset({N}))
    killed = run_moment(service, "mom-M001-1")
    assert all(i.fallback and i.agent_trace == [ORCH, T] for i in killed.values())  # never called, so not traced
    service.team.enable(N)
    recovered = run_moment(service, "mom-M001-6")
    assert not any(i.fallback for i in recovered.values())


def test_killed_language_agent_only_hits_translated_segments() -> None:
    insights = run_moment(make_service(disabled_agents=frozenset({L})), "mom-M001-1")
    assert not insights[EN_KEY].fallback
    assert insights[AR_KEY].fallback and insights[AR_KEY].agent_trace == [ORCH, N, V, P, T]


def test_timeout_falls_back_fast() -> None:
    writer = Scripted(N, delay_s=2.0)
    started = time.perf_counter()
    insights = run_moment(make_service({N: writer}, agent_timeout_s=0.05), "mom-M001-1")
    assert time.perf_counter() - started < 1.5
    assert all(i.fallback and i.agent_trace == [ORCH, N, T] for i in insights.values())


def test_insufficient_evidence_is_not_retried() -> None:
    writer = Scripted(N, lambda d, _, n: Draft(status="INSUFFICIENT_EVIDENCE", headline="", body="", claims=[]))
    insights = run_moment(make_service({N: writer}), "mom-M001-1")
    assert len(writer.prompts) == 1
    assert all(i.fallback and i.agent_trace == [ORCH, N, V, T] for i in insights.values())


def test_unreadable_reply_falls_back_without_tripping_the_breaker() -> None:
    async def persona(prompt: str) -> str:
        return "this is not JSON" if segment_of(prompt) == AR_KEY else await Scripted(P)(prompt)

    service = make_service({P: persona}, breaker_threshold=1)
    first = run_moment(service, "mom-M001-1")
    assert first[AR_KEY].fallback and first[AR_KEY].agent_trace == [ORCH, N, V, P, T]
    assert not first[EN_KEY].fallback
    later = run_moment(service, "mom-M001-6")  # Persona is still trusted: the service answered every time
    assert not later[EN_KEY].fallback


def test_circuit_breaker_stops_calling_a_failing_agent() -> None:
    writer = Scripted(N, error=RuntimeError("quota exceeded"))
    service = make_service({N: writer}, breaker_threshold=2, breaker_cooldown_s=3600.0)
    for moment_id in ("mom-M001-1", "mom-M001-6", "mom-M001-9"):
        assert all(i.fallback for i in run_moment(service, moment_id).values())
    assert len(writer.prompts) == 2  # the third goal never reached the model


def test_llm_judge_can_reject_a_draft_the_code_checks_accept() -> None:
    calls: list[str] = []

    async def judge(prompt: str) -> str:
        calls.append(prompt)
        supported = len(calls) > 1
        issues = [] if supported else ["the draft says Halvorsen scored a header; no event shows that"]
        return JudgeVerdict(supported=supported, issues=issues).model_dump_json()

    writer = Scripted(N)
    insights = run_moment(make_service({N: writer, V: judge}, judge=True), "mom-M001-1")
    assert len(writer.prompts) == 2
    assert "judge: the draft says Halvorsen scored a header" in writer.prompts[1]
    assert insights[EN_KEY].agent_trace == [ORCH, N, V, N, V, P, V]
    assert len(calls) == 2 + 3  # both writer drafts, then every segment's final draft


def test_judge_checks_translated_drafts_too() -> None:
    async def judge(prompt: str) -> str:
        arabic_draft = "Goal for Harbour United" in prompt and "translated" in prompt
        return JudgeVerdict(supported=not arabic_draft, issues=["invented"] if arabic_draft else []).model_dump_json()

    async def language(prompt: str) -> str:
        draft = Draft.model_validate(read_sections(prompt)["DRAFT"])
        return draft.model_copy(update={"headline": f"{draft.headline} (translated)"}).model_dump_json()

    insights = run_moment(make_service({V: judge, L: language}, judge=True), "mom-M001-1")
    assert not insights[EN_KEY].fallback
    assert insights[AR_KEY].fallback and insights[FR_KEY].fallback  # rejected twice by the judge


def test_one_slow_segment_does_not_hold_back_the_others() -> None:
    async def persona(prompt: str) -> str:
        if segment_of(prompt) == AR_KEY:
            await asyncio.sleep(0.6)
        return await Scripted(P)(prompt)

    insights = run_moment(make_service({P: persona}), "mom-M001-1")
    assert (insights[EN_KEY].latency_ms or 0) < 300
    assert (insights[AR_KEY].latency_ms or 0) >= 580  # sleep(0.6) can measure 598 ms on Windows timers


def test_moment_deadline_publishes_templates_for_late_segments() -> None:
    async def persona(prompt: str) -> str:
        if segment_of(prompt) == AR_KEY:
            await asyncio.sleep(5)
        return await Scripted(P)(prompt)

    started = time.perf_counter()
    insights = run_moment(make_service({P: persona}, moment_deadline_s=0.3), "mom-M001-1")
    assert time.perf_counter() - started < 1.5
    assert not insights[EN_KEY].fallback and not insights[FR_KEY].fallback
    assert insights[AR_KEY].fallback and insights[AR_KEY].agent_trace == [ORCH, T]


def test_an_unexpected_error_only_costs_its_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    original = build_insight

    def flaky(**kwargs: Any) -> Insight:
        if kwargs["segment"].key == AR_KEY:
            raise KeyError("boom")
        return original(**kwargs)

    monkeypatch.setattr(workflow_module, "build_insight", flaky)
    insights = run_moment(make_service(), "mom-M001-1")
    assert insights[AR_KEY].fallback and insights[AR_KEY].agent_trace == [ORCH, N, V, P, L, V, T]
    assert not insights[EN_KEY].fallback and not insights[FR_KEY].fallback


def test_insight_names_the_model_that_wrote_its_text() -> None:
    base = mock_client_set()
    models = {**base.models, P: "persona-model", L: "language-model", N: "writer-model"}
    service = AgentsService(AgentTeam(ClientSet(clients=base.clients, models=models, translates=False)))
    insights = run_moment(service, "mom-M001-1")
    assert insights[EN_KEY].model == "persona-model"
    assert insights[AR_KEY].model == "language-model"


def test_segments_run_in_parallel() -> None:
    persona = Scripted(P, delay_s=0.3)
    started = time.perf_counter()
    insights = run_moment(make_service({P: persona}), "mom-M001-3")  # big chance with H10: all 4 demo segments
    assert len(insights) == 4
    assert time.perf_counter() - started < 0.9  # sequential would take 1.2 s

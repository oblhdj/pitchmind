import asyncio
import codecs
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from azure.core.credentials import AccessToken
from pitchmind_agents import (
    DEMO_SEGMENTS,
    AgentsConfig,
    AgentsService,
    AgentTeam,
    matrix_segments,
    mock_client_set,
    parse_segments,
)
from pitchmind_agents import routing as routing_module
from pitchmind_agents import service as service_module
from pitchmind_agents.__main__ import main as cli_main
from pitchmind_agents.agents import CircuitBreaker
from pitchmind_agents.clients import foundry_client_set
from pitchmind_agents.numbers import unsupported_numbers
from pitchmind_agents.routing import ROUTES, STAT_ALERTS, route
from pitchmind_agents.runtime import load_env_file, replay
from pitchmind_agents.segments import applies
from pitchmind_agents.testing import MOCK_STREAM, Scripted, mock_messages, mock_moments, prime
from pitchmind_agents.verifier import wrong_language
from pitchmind_contracts import AgentName, Insight, Language, MomentKind, Overlay, Phase, Segment, parse_wire

N = AgentName.NARRATIVE


def new_service(**overrides: Scripted) -> AgentsService:
    return AgentsService(AgentTeam(mock_client_set(overrides={AgentName(k): v for k, v in overrides.items()})))


def expected_count() -> int:
    """Every routed moment times the demo segments that care about it."""
    return sum(sum(applies(s, m) for s in DEMO_SEGMENTS) for m in mock_moments() if not route(m).skip)


def test_replaying_the_demo_match_covers_every_moment() -> None:
    insights = asyncio.run(replay(new_service(), mock_messages()))
    moments = mock_moments()
    assert {i.moment_id for i in insights} == {m.id for m in moments if m.kind is not MomentKind.SPEED_THRESHOLD}
    assert len(insights) == expected_count()
    assert all(i.verified and not i.fallback for i in insights)
    assert len({i.id for i in insights}) == len(insights)
    player_focus = {i.moment_id for i in insights if i.segment.player == "H10"}
    assert player_focus == {m.id for m in moments if "H10" in m.players and m.kind is not MomentKind.SPEED_THRESHOLD}


def test_a_redelivered_moment_replays_its_insights_without_new_llm_calls() -> None:
    writer = Scripted(N)
    service = new_service(narrative=writer)
    goal = prime(service, "mom-M001-1")
    first = asyncio.run(service.process(goal))
    again = asyncio.run(service.process(goal))
    assert again == first
    assert len(writer.prompts) == 1


def test_concurrent_duplicates_share_one_run() -> None:
    writer = Scripted(N, delay_s=0.1)
    service = new_service(narrative=writer)
    goal = prime(service, "mom-M001-1")

    async def both() -> tuple[list[Insight], list[Insight]]:
        a, b = await asyncio.gather(service.process(goal), service.process(goal))
        return a, b

    a, b = asyncio.run(both())
    assert a == b and len(a) == 3
    assert len(writer.prompts) == 1


def test_an_interrupted_run_is_processed_again_on_redelivery() -> None:
    writer = Scripted(N)
    service = new_service(narrative=writer)
    goal = prime(service, "mom-M001-1")

    async def first_insight_only() -> Insight:
        stream = service.stream(goal)
        insight = await anext(stream)
        await stream.aclose()
        return insight

    asyncio.run(first_insight_only())
    assert len(asyncio.run(service.process(goal))) == 3
    assert len(writer.prompts) == 2


def test_close_match_forgets_its_state() -> None:
    service = new_service()
    asyncio.run(service.process(prime(service, "mom-M001-1")))
    service.close_match("M001")
    assert not service.context("M001").seen("mom-M001-1")


def test_old_matches_are_forgotten_as_new_ones_start() -> None:
    service = new_service()
    asyncio.run(service.process(prime(service, "mom-M001-1")))
    for match_id in ("M002", "M003"):
        service.context(match_id)
    assert service.tracked_matches == ("M002", "M003")  # the live match and the previous one
    assert service.is_closed("M001")


def test_late_messages_for_a_closed_match_are_dropped_without_evicting_live_ones() -> None:
    service = new_service()
    goal = prime(service, "mom-M001-1")
    for match_id in ("M002", "M003"):
        service.context(match_id)
    assert asyncio.run(service.process(goal)) == []  # M001 is closed: no agents called
    meta = next(m for m in mock_messages() if m.msg == "match_meta")
    assert asyncio.run(service.handle(meta)) == []
    assert service.tracked_matches == ("M002", "M003")


def test_a_match_still_being_processed_is_not_forgotten() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    writer = Scripted(AgentName.NARRATIVE)

    async def slow_writer(prompt: str) -> str:
        started.set()
        await release.wait()
        return await writer(prompt)

    service = AgentsService(AgentTeam(mock_client_set(overrides={AgentName.NARRATIVE: slow_writer})))
    goal = prime(service, "mom-M001-1")

    async def scenario() -> list[Insight]:
        run = asyncio.create_task(service.process(goal))
        await started.wait()
        for match_id in ("M002", "M003"):
            service.context(match_id)
        assert "M001" in service.tracked_matches  # its goal is still being written
        release.set()
        return await run

    assert len(asyncio.run(scenario())) == 3


def test_downstream_messages_are_ignored() -> None:
    service = new_service()
    insight = next(m for m in mock_messages() if isinstance(m, Insight))
    overlay = next(m for m in mock_messages() if isinstance(m, Overlay))
    assert asyncio.run(service.handle(insight)) == []
    assert asyncio.run(service.handle(overlay)) == []


def test_a_broken_workflow_still_publishes_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object) -> object:
        raise RuntimeError("graph construction failed")

    monkeypatch.setattr(service_module, "build_workflow", explode)
    service = new_service()
    insights = asyncio.run(service.process(prime(service, "mom-M001-1")))
    assert len(insights) == 3
    assert all(i.fallback and i.agent_trace == [AgentName.ORCHESTRATOR, AgentName.TEMPLATE] for i in insights)


def test_a_very_long_fallback_text_is_clipped_not_fatal() -> None:
    service = AgentsService(AgentTeam(mock_client_set(), AgentsConfig(disabled_agents=frozenset({N}))))
    goal = prime(service, "mom-M001-1").model_copy(update={"id": "mom-long", "fallback_text": "x" * 2000})
    insights = asyncio.run(service.process(goal))
    english = [i for i in insights if i.segment.language is Language.EN]
    assert english and all(i.fallback and len(i.body) == 1500 and i.body.endswith("…") for i in english)


def test_a_fallback_speaks_the_fans_language_with_only_pipeline_numbers() -> None:
    """Live QA: the Arabic feed showed an Arabic template headline over an English body."""
    service = AgentsService(AgentTeam(mock_client_set(), AgentsConfig(disabled_agents=frozenset({N}))))
    goal = prime(service, "mom-M001-1")
    facts = service.context(goal.match_id).facts_for(goal)
    insights = {i.segment.language: i for i in asyncio.run(service.process(goal))}
    assert insights[Language.EN].body == goal.fallback_text
    assert insights[Language.FR].body.startswith(f"But à la {facts.minute}e minute pour {facts.team}.")
    assert insights[Language.AR].body.startswith(f"هدف في الدقيقة {facts.minute}")
    for language, insight in insights.items():
        assert insight.fallback
        assert not unsupported_numbers(insight.body, facts.allowed_numbers(), language), insight.body
        words = insight.body
        for name in facts.teams.values():  # names stay in Latin script by design
            words = words.replace(name, "")
        assert not wrong_language(words, language), insight.body


def test_every_moment_kind_has_a_route(monkeypatch: pytest.MonkeyPatch) -> None:
    assert set(ROUTES) | STAT_ALERTS == set(MomentKind)
    goal = mock_moments()[0]
    monkeypatch.delitem(routing_module.ROUTES, MomentKind.GOAL)
    assert route(goal).writer is AgentName.NARRATIVE  # a kind the table does not know still gets commentary


def test_shared_state_gives_agents_names_score_and_phase() -> None:
    service = new_service()
    ht = prime(service, "mom-M001-4")
    facts = service.context("M001").facts_for(ht)
    assert facts.phase is Phase.HALF_TIME
    assert facts.score == {"home": 0, "away": 1}
    assert facts.teams == {"home": "North City FC", "away": "Harbour United"}
    assert {p.id: p.name for p in facts.players}["A9"] == "Halvorsen"
    key_moments = [(km.minute, km.kind) for km in facts.key_moments]
    assert key_moments == [(9, "goal"), (27, "pressure_surge"), (33, "big_chance")]
    assert 9.0 in facts.allowed_numbers()


def test_cli_writes_insights_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "insights.jsonl"
    assert cli_main(["--input", str(MOCK_STREAM), "--output", str(out), "--disable", "narrative"]) == 0
    insights = [parse_wire(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(insights) == expected_count()
    goals = [i for i in insights if isinstance(i, Insight) and i.kind == "commentary"]
    assert goals and all(i.fallback for i in goals)  # the Narrative agent was killed


def test_cli_stdout_survives_a_redirect_on_windows(tmp_path: Path) -> None:
    out = tmp_path / "stdout.jsonl"
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}}
    with out.open("wb") as f:
        done = subprocess.run(
            [sys.executable, "-m", "pitchmind_agents", "--input", str(MOCK_STREAM), "--disable", "narrative"],
            stdout=f,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert "هدف!" in out.read_text(encoding="utf-8")


def test_load_env_file_handles_windows_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("PM_A", "PM_B", "PM_C", "PM_D", "PM_E", "PM_KEEP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PM_KEEP", "already set")
    lines = [
        "# a comment",
        "PM_A=plain value # trailing comment",
        "export PM_B=exported",
        'PM_C="quoted # not a comment"',
        "PM_D='ends with a quote'",
        "=no key",
        "not a pair",
        "PM_E=InstrumentationKey=abc;IngestionEndpoint=https://x",
        "PM_KEEP=from file",
    ]
    bom = tmp_path / "bom.env"
    bom.write_bytes(codecs.BOM_UTF8 + "\n".join(lines).encode("utf-8"))
    load_env_file(bom)
    assert os.environ["PM_A"] == "plain value"
    assert os.environ["PM_B"] == "exported"
    assert os.environ["PM_C"] == "quoted # not a comment"
    assert os.environ["PM_D"] == "ends with a quote"
    assert os.environ["PM_E"] == "InstrumentationKey=abc;IngestionEndpoint=https://x"
    assert os.environ["PM_KEEP"] == "already set"

    monkeypatch.delenv("PM_A")
    utf16 = tmp_path / "utf16.env"
    utf16.write_bytes("PM_A=from powershell\n".encode("utf-16"))
    load_env_file(utf16)
    assert os.environ["PM_A"] == "from powershell"


class FakeCredential:
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken("token", 0)


def test_foundry_clients_put_writers_on_the_strong_model() -> None:
    clients = foundry_client_set(
        endpoint="https://demo.services.ai.azure.com/api/projects/pitchmind",
        strong_model="strong-model",
        fast_model="fast-model",
        credential=FakeCredential(),
    )
    assert {role: clients.models[role] for role in (AgentName.NARRATIVE, AgentName.PERSONA)} == {
        AgentName.NARRATIVE: "strong-model",
        AgentName.PERSONA: "fast-model",
    }
    assert clients.clients[AgentName.EXPLAIN] is clients.clients[AgentName.RECAP]
    assert clients.clients[AgentName.EXPLAIN] is not clients.clients[AgentName.LANGUAGE]
    with pytest.raises(ValueError, match="FOUNDRY_PROJECT_ENDPOINT"):
        foundry_client_set(env={})


def test_config_from_env() -> None:
    config = AgentsConfig.from_env(
        {
            "PITCHMIND_DISABLED_AGENTS": "narrative, Language",
            "PITCHMIND_JUDGE": "1",
            "PITCHMIND_AGENT_TIMEOUT_S": "3",
            "PITCHMIND_MOMENT_DEADLINE_S": "10",
        }
    )
    assert config.disabled_agents == {AgentName.NARRATIVE, AgentName.LANGUAGE}
    assert config.judge and config.agent_timeout_s == 3.0 and config.moment_deadline_s == 10.0
    assert AgentsConfig.from_env({}) == AgentsConfig()


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"PITCHMIND_MAX_RETRIES": "-1"}, "max_retries must be 0 or more"),
        ({"PITCHMIND_AGENT_TIMEOUT_S": "fast"}, "PITCHMIND_AGENT_TIMEOUT_S must be a float, got 'fast'"),
        ({"PITCHMIND_DISABLED_AGENTS": "narator"}, "unknown agents \\['narator'\\]"),
        ({"PITCHMIND_MIN_IMPORTANCE": "2"}, "min_importance must be between 0 and 1"),
    ],
)
def test_config_rejects_bad_values(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AgentsConfig.from_env(env)


def test_circuit_breaker_half_open_lets_exactly_one_probe_through() -> None:
    now = [0.0]
    breaker = CircuitBreaker(2, 30.0, lambda: now[0])
    breaker.failure()
    breaker.failure()
    assert breaker.state == "open" and not breaker.allow()
    now[0] = 31.0
    assert breaker.allow()  # the probe
    assert not breaker.allow()  # everyone else waits for it
    breaker.failure()  # probe failed: open again at once
    assert breaker.state == "open" and not breaker.allow()
    now[0] = 62.0
    assert breaker.allow()
    breaker.success()  # probe succeeded: closed
    assert breaker.state == "closed" and breaker.allow() and breaker.allow()


def test_a_cancelled_probe_frees_the_slot() -> None:
    now = [0.0]
    breaker = CircuitBreaker(1, 10.0, lambda: now[0])
    breaker.failure()
    now[0] = 11.0
    assert breaker.allow()
    breaker.abandon()
    assert breaker.allow()


def test_segment_helpers() -> None:
    assert parse_segments("demo") == DEMO_SEGMENTS
    assert len(matrix_segments()) == 12  # 3 personas x 4 languages
    assert len(parse_segments("all")) == 13  # plus player focus on H10
    (custom,) = parse_segments("casual|es|club:away|player:*|metric:xg")
    assert custom.key == "casual|es|club:away|player:*|metric:xg"


def test_metric_focus_matches_whole_metric_names() -> None:
    moment = mock_moments()[0].model_copy(update={"metrics": {"home_xg": 0.4, "next_pass": 1.0}})
    assert applies(Segment.from_key("casual|en|club:*|player:*|metric:xg"), moment)
    assert not applies(Segment.from_key("casual|en|club:*|player:*|metric:xt"), moment)

"""Behaviour needed by small Foundry models (Phi on serverless): no native JSON mode, a low RPM limit,
and a tendency to embellish names or skip the translation."""

import asyncio
from typing import Any

import pytest
from pitchmind_agents import AgentsConfig, AgentTeam, ClientSet, Draft, Facts, check, mock_client_set
from pitchmind_agents.agents import (
    AgentCallError,
    RateLimiter,
    extract_json,
    ignores_response_format,
    rate_limit_wait,
    with_schema,
)
from pitchmind_agents.evals import replay_facts
from pitchmind_agents.mock_llm import Responder, mock_draft
from pitchmind_agents.testing import mock_messages
from pitchmind_agents.verifier import invented_first_names, wrong_language
from pitchmind_contracts import AgentName, Language

GOAL: Facts = replay_facts(mock_messages())["mom-M001-1"]
N, P = AgentName.NARRATIVE, AgentName.PERSONA


def test_extract_json_strips_fences_and_prose() -> None:
    assert extract_json('Sure! ```json\n{"a": 1}\n``` Hope that helps.') == '{"a": 1}'
    assert extract_json("no json here") == "no json here"


def test_with_schema_appends_the_contract() -> None:
    prompt = with_schema("## TASK\nWrite.", Draft)
    assert prompt.startswith("## TASK\nWrite.")
    assert "## OUTPUT FORMAT" in prompt and '"headline"' in prompt


def test_prose_reply_errors_are_recognised() -> None:
    assert ignores_response_format(ValueError("1 validation error for Draft\n  Invalid JSON: expected value"))
    assert not ignores_response_format(RuntimeError("429 Too Many Requests"))


def test_team_switches_to_schema_in_prompt_when_the_model_ignores_response_format() -> None:
    prompts: list[str] = []

    async def phi_like(prompt: str) -> str:
        prompts.append(prompt)
        if "## OUTPUT FORMAT" not in prompt:
            raise ValueError("1 validation error for Draft\n  Invalid JSON: expected value [type=json_invalid]")
        return f"Here you go:\n```json\n{mock_draft(GOAL).model_dump_json()}\n```"

    team = AgentTeam(mock_client_set(overrides={N: phi_like}), AgentsConfig(breaker_threshold=1))
    first = asyncio.run(team.ask(N, "## TASK\nWrite.", Draft))
    second = asyncio.run(team.ask(N, "## TASK\nWrite again.", Draft))
    assert first.headline == second.headline == mock_draft(GOAL).headline
    assert len(prompts) == 3  # one prose failure, then the schema goes in every prompt
    assert "## OUTPUT FORMAT" in prompts[2]


def test_rate_limiter_waits_for_a_free_slot() -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2, clock=lambda: now[0], sleep=fake_sleep)

    async def calls() -> None:
        for _ in range(3):
            await limiter.acquire()
            now[0] += 1.0

    asyncio.run(calls())
    assert sleeps == [58.0]  # the 3rd call waits until the 1st leaves the 60 s window


def test_rate_limiter_spreads_a_burst_over_10_second_windows() -> None:
    """A goal fans out to every segment at once; Foundry refuses bursts that fit the minute."""
    now = [0.0]
    started: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    limiter = RateLimiter(18, clock=lambda: now[0], sleep=fake_sleep, per_10s=3)

    async def burst() -> None:
        for _ in range(7):
            await limiter.acquire()
            started.append(now[0])

    asyncio.run(burst())
    assert started == [0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 20.0]


def test_each_model_deployment_has_its_own_limiter() -> None:
    team = AgentTeam(mock_client_set(), AgentsConfig(requests_per_minute=12))
    assert team.limiter("Phi-4") is team.limiter("Phi-4")
    assert team.limiter("Phi-4") is not team.limiter("Phi-4-mini-instruct")


def test_rate_limiter_zero_means_unlimited() -> None:
    async def never(_: float) -> None:
        raise AssertionError("must not sleep")

    async def burst() -> None:
        limiter = RateLimiter(0, sleep=never)
        await asyncio.gather(*(limiter.acquire() for _ in range(100)))

    asyncio.run(burst())


def test_rpm_is_read_from_the_environment() -> None:
    assert AgentsConfig.from_env({"PITCHMIND_RPM": "18"}).requests_per_minute == 18
    with pytest.raises(ValueError, match="requests_per_minute"):
        AgentsConfig(requests_per_minute=-1)


def test_invented_first_name_is_rejected() -> None:
    scorer = next(p for p in GOAL.players if p.name in GOAL.summary)
    assert invented_first_names(f"In the first half, Johan {scorer.name} scores.", GOAL) == [f"Johan {scorer.name}"]
    assert invented_first_names(f"{scorer.full_name} scores. Then {scorer.name} celebrates.", GOAL) == []
    assert invented_first_names(f"As {scorer.name} shoots. Johan {scorer.name} scores.", GOAL) == []  # sentence starts
    draft = mock_draft(GOAL).model_copy(update={"body": f"{GOAL.summary} Then Johan {scorer.name} celebrates."})
    verdict = check(draft, GOAL)
    assert not verdict.ok and any("Johan" in issue for issue in verdict.issues)


def test_untranslated_text_is_rejected_for_other_languages() -> None:
    english = "The striker scored after a pass from the left and the keeper was beaten."
    assert wrong_language(english, Language.FR) is not None
    assert wrong_language(english, Language.EN) is None
    assert wrong_language("Halvorsen marque après une passe venue de la gauche.", Language.FR) is None
    assert wrong_language("سجل Halvorsen هدفا رائعا بعد تمريرة من Albers", Language.AR) is None
    assert wrong_language(english, Language.AR) is not None


def test_language_check_is_off_for_clients_that_cannot_translate() -> None:
    draft = mock_draft(GOAL)  # English text
    assert not check(draft, GOAL, Language.FR).ok
    assert check(draft, GOAL, Language.FR, check_language=False).ok
    assert not mock_client_set().translates


class FakeRateLimitError(Exception):
    """Shaped like the OpenAI SDK's RateLimitError."""

    status_code = 429

    def __init__(self, retry_after: str | None = "2") -> None:
        super().__init__("Error code: 429 - rate_limit_exceeded")
        self.response = type("Response", (), {"headers": {"retry-after": retry_after} if retry_after else {}})()


def test_rate_limit_wait_reads_retry_after_through_wrappers() -> None:
    try:
        try:
            raise FakeRateLimitError("7")
        except FakeRateLimitError as inner:
            raise RuntimeError("service failed to complete the prompt") from inner
    except RuntimeError as wrapped:
        assert rate_limit_wait(wrapped) == 7.0
    assert rate_limit_wait(FakeRateLimitError(None)) == 10.0
    assert rate_limit_wait(RuntimeError("Error code: 429 Too Many Requests")) == 10.0
    assert rate_limit_wait(RuntimeError("connection reset")) is None


def test_rate_limit_wait_finds_the_header_behind_a_wrapper_that_also_mentions_the_429() -> None:
    try:
        try:
            raise FakeRateLimitError("7")
        except FakeRateLimitError as inner:
            raise RuntimeError("service failed: Error code: 429 - rate_limit_exceeded") from inner
    except RuntimeError as wrapped:
        assert rate_limit_wait(wrapped) == 7.0


def test_retry_after_ms_wins_and_dates_fall_back_to_the_default() -> None:
    error = FakeRateLimitError(None)
    error.response.headers.update({"retry-after-ms": "2500", "retry-after": "9"})
    assert rate_limit_wait(error) == 2.5
    dated = FakeRateLimitError("Wed, 21 Oct 2026 07:28:00 GMT")
    assert rate_limit_wait(dated) == 10.0


def test_rate_limiter_can_be_reused_across_event_loops() -> None:
    now = [0.0]

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    limiter = RateLimiter(1, clock=lambda: now[0], sleep=fake_sleep)

    async def contended() -> None:
        await asyncio.gather(limiter.acquire(), limiter.acquire())  # the 2nd waits on the lock

    asyncio.run(contended())
    asyncio.run(contended())  # a new loop: no "bound to a different event loop" error
    assert now[0] >= 180.0


def make_team(responder: Responder, **config: Any) -> tuple[AgentTeam, list[float]]:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    team = AgentTeam(mock_client_set(overrides={N: responder}), AgentsConfig(**config), sleep=fake_sleep)
    return team, waits


def test_a_429_waits_and_retries_without_tripping_the_breaker() -> None:
    calls = [0]

    async def busy_once(prompt: str) -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise FakeRateLimitError("3")
        return mock_draft(GOAL).model_dump_json()

    team, waits = make_team(busy_once, breaker_threshold=1)
    assert asyncio.run(team.ask(N, "x", Draft)).headline == mock_draft(GOAL).headline
    assert waits == [3.0]
    assert asyncio.run(team.ask(N, "x", Draft))  # breaker_threshold=1, yet the circuit stayed closed


def test_a_persistent_429_falls_back_after_one_retry() -> None:
    async def always_busy(prompt: str) -> str:
        raise FakeRateLimitError("1")

    team, waits = make_team(always_busy)
    with pytest.raises(AgentCallError, match="429"):
        asyncio.run(team.ask(N, "x", Draft))
    assert waits == [1.0]


def test_schema_in_prompt_is_switched_per_model() -> None:
    seen: dict[str, list[str]] = {"narrative": [], "persona": []}

    def recorder(role: str, prose: bool) -> Responder:
        async def respond(prompt: str) -> str:
            seen[role].append(prompt)
            if prose and "## OUTPUT FORMAT" not in prompt:
                raise ValueError('1 validation error for Draft\n  Invalid JSON [type=json_invalid, input_value="Sure"')
            return mock_draft(GOAL).model_dump_json()

        return respond

    base = mock_client_set(overrides={N: recorder("narrative", True), P: recorder("persona", False)})
    models = {**base.models, N: "phi", P: "gpt"}
    team = AgentTeam(ClientSet(clients=base.clients, models=models))
    asyncio.run(team.ask(N, "x", Draft))
    asyncio.run(team.ask(P, "x", Draft))
    assert "## OUTPUT FORMAT" in seen["narrative"][-1]
    assert all("## OUTPUT FORMAT" not in prompt for prompt in seen["persona"])


def test_truncated_json_is_not_mistaken_for_prose() -> None:
    truncated = ValueError(
        '1 validation error for Draft\n  Invalid JSON: EOF [type=json_invalid, input_value=\'{"claims":['
    )
    prose = ValueError('1 validation error for Draft\n  Invalid JSON [type=json_invalid, input_value="With pace')
    assert not ignores_response_format(truncated)
    assert ignores_response_format(prose)


def test_title_case_headlines_and_role_words_are_not_invented_names() -> None:
    assert invented_first_names("Early Strike From Halvorsen Stuns North City", GOAL) == []
    assert invented_first_names("A clinical finish, Forward Halvorsen delivers.", GOAL) == []


def test_untranslated_claims_are_rejected() -> None:
    french = mock_draft(GOAL).model_copy(
        update={"headline": "But de Halvorsen", "body": "Halvorsen marque à la 9e minute pour Harbour United."}
    )
    verdict = check(french, GOAL, Language.FR)  # the mock's claim text is still English
    assert not verdict.ok and any(issue.startswith("claims:") for issue in verdict.issues)

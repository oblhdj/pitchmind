import pytest
from pitchmind_agents import ClaimDraft, Draft, Facts, check
from pitchmind_agents.evals import replay_facts
from pitchmind_agents.mock_llm import mock_draft
from pitchmind_agents.testing import hand_written_insights, mock_messages
from pitchmind_contracts import Insight, Language

FACTS = replay_facts(mock_messages())


def mock_insights(moment_id: str) -> dict[str, Insight]:
    return {i.segment.key: i for i in hand_written_insights() if i.moment_id == moment_id}


def as_draft(insight: Insight) -> Draft:
    claims = [ClaimDraft(text=c.text, evidence=c.evidence, metrics=list(c.metrics)) for c in insight.claims]
    return Draft(status="ok", headline=insight.headline, body=insight.body, claims=claims)


@pytest.fixture(scope="module")
def goal() -> Facts:
    return FACTS["mom-M001-1"]


def with_body(facts: Facts, body: str) -> Draft:
    return mock_draft(facts).model_copy(update={"body": body})


def test_grounded_draft_passes(goal: Facts) -> None:
    verdict = check(mock_draft(goal), goal)
    assert verdict.ok, verdict.issues


def test_planted_wrong_number_is_rejected(goal: Facts) -> None:
    verdict = check(with_body(goal, "Halvorsen finishes a 0.83 xG chance at 104.2 km/h."), goal)
    assert not verdict.ok
    assert verdict.issues == ("body states 0.83, which is not in FACTS",)


def test_event_ids_in_the_text_are_named_as_such(goal: Facts) -> None:
    """Live, the recap writer kept copying event ids into the body: the feedback must say why."""
    ids = sorted(goal.evidence)[:2]
    verdict = check(with_body(goal, f"Halvorsen scores (events {ids[0]}, {ids[1]}) from a 0.83 xG chance."), goal)
    assert verdict.issues == (
        f"body writes event ids {ids[0]}, {ids[1]}: event ids belong only in a claim's evidence, "
        "never in the headline, body or claim text",
        "body states 0.83, which is not in FACTS",
    )


def test_numbers_written_as_words_are_checked(goal: Facts) -> None:
    english = with_body(goal, "Scored in the eleventh minute; one in four chances like that go in.")
    assert check(english, goal).issues == ("body states eleventh, four, which is not in FACTS",)
    french = with_body(goal, "Une occasion de ce type finit au fond quatre fois sur dix.")
    assert check(french, goal, Language.FR, check_language=False).issues == (
        "body states quatre, dix, which is not in FACTS",
    )
    assert check(with_body(goal, "Halvorsen scores in the ninth minute."), goal).ok


@pytest.mark.parametrize(
    "body", ["<script>alert(1)</script> Goal!", "Watch it at https://evil.example", "Goal!\x07", "See www.example.com"]
)
def test_markup_links_and_control_characters_are_rejected(goal: Facts, body: str) -> None:
    assert check(with_body(goal, body), goal).issues == (
        "body contains markup, a link or control characters; write plain text",
    )


def test_numbers_in_team_and_player_names_are_facts(goal: Facts) -> None:
    schalke = goal.model_copy(update={"teams": {"home": "Schalke 04", "away": "Harbour United"}})
    assert check(with_body(schalke, "Schalke 04 concede to Halvorsen."), schalke).ok


def test_evidence_and_metric_names_must_come_from_the_moment(goal: Facts) -> None:
    claim = ClaimDraft(text="Halvorsen scores.", evidence=[131, 999], metrics=["xg", "pressure_index"])
    verdict = check(mock_draft(goal).model_copy(update={"claims": [claim]}), goal)
    assert verdict.issues == (
        "claim 1 cites event ids [999] that are not in FACTS.evidence",
        "claim 1 names metrics ['pressure_index'] that are not in FACTS.metrics",
    )


def test_structure_checks(goal: Facts) -> None:
    empty = Draft(status="ok", headline="x" * 91, body="", claims=[])
    assert check(empty, goal).issues == (
        "headline has 91 characters, the limit is 90",
        "body is empty",
        "there are no claims; cite at least one",
    )
    uncited = mock_draft(goal).model_copy(update={"claims": [ClaimDraft(text="A goal.", evidence=[], metrics=[])]})
    assert check(uncited, goal).issues == ("claim 1 cites no event id",)


def test_insufficient_evidence_is_never_retried(goal: Facts) -> None:
    verdict = check(Draft(status="INSUFFICIENT_EVIDENCE", headline="", body="", claims=[]), goal)
    assert not verdict.ok
    assert verdict.insufficient


def test_hand_written_multilingual_insights_pass() -> None:
    insights = mock_insights("mom-M001-2")
    assert len(insights) == 3  # EN analyst, AR casual (0.38 / 68%), FR beginner (0,38 / 68 %)
    for key, insight in insights.items():
        verdict = check(as_draft(insight), FACTS["mom-M001-2"], insight.segment.language)
        assert verdict.ok, (key, verdict.issues)


def test_recap_may_cite_key_moment_minutes() -> None:
    facts = FACTS["mom-M001-4"]
    assert [km.minute for km in facts.key_moments] == [9, 27, 33]
    analyst = mock_insights("mom-M001-4")["analyst|en|club:*|player:*|metric:*"]
    assert "9th-minute" in analyst.body
    assert check(as_draft(analyst), facts).ok


def test_derived_numbers_are_caught() -> None:
    # "4 fois sur 10" is computed from xG 0.38; it is not a fact the pipeline produced.
    beginner = mock_insights("mom-M001-1")["beginner|fr|club:*|player:*|metric:*"]
    derived = beginner.model_copy(update={"body": beginner.body + " Elle finit au fond environ 4 fois sur 10."})
    verdict = check(as_draft(derived), FACTS["mom-M001-1"], Language.FR)
    assert verdict.issues == ("body states 4, 10, which is not in FACTS",)

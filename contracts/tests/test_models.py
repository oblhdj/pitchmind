import pytest
from pitchmind_contracts import (
    AgentName,
    Claim,
    EventType,
    FanProfile,
    Insight,
    InsightKind,
    Language,
    MatchEvent,
    MetricName,
    Moment,
    MomentKind,
    Outcome,
    Overlay,
    OverlaySlot,
    Persona,
    Phase,
    Segment,
    TeamSide,
    parse_wire,
)
from pydantic import ValidationError


def make_pass(**overrides: object) -> MatchEvent:
    data: dict[str, object] = {
        "id": 312,
        "match_id": "M001",
        "t": 1394.2,
        "minute": 23,
        "phase": Phase.FIRST_HALF,
        "type": EventType.PASS,
        "team": TeamSide.HOME,
        "player": "H7",
        "receiver": "H10",
        "start": (40.1, 60.3),
        "end": (71.0, 52.8),
        "outcome": Outcome.SUCCESS,
        "under_pressure": True,
        "ball_speed_kmh": 58.4,
    }
    data.update(overrides)
    return MatchEvent.model_validate(data)


class TestMatchEvent:
    def test_valid_pass_round_trips_through_wire(self) -> None:
        event = make_pass()
        parsed = parse_wire(event.model_dump_json())
        assert parsed == event

    def test_point_outside_pitch_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_pass(end=(110.0, 30.0))

    def test_pass_needs_success_or_failure(self) -> None:
        with pytest.raises(ValidationError, match="pass outcome"):
            make_pass(outcome=Outcome.GOAL)

    def test_shot_without_start_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="start point"):
            make_pass(type=EventType.SHOT, start=None, outcome=Outcome.ON_TARGET)

    def test_bad_player_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_pass(player="Saka")

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_pass(xg=0.3)


class TestSegment:
    def test_key_round_trip(self) -> None:
        seg = Segment(persona=Persona.CASUAL, language=Language.AR, club=TeamSide.HOME, player="H10")
        assert seg.key == "casual|ar|club:home|player:H10|metric:*"
        assert Segment.from_key(seg.key) == seg

    def test_key_is_serialized(self) -> None:
        seg = Segment(persona=Persona.ANALYST, language=Language.EN, metric_focus=MetricName.XG)
        assert seg.model_dump()["key"] == "analyst|en|club:*|player:*|metric:xg"

    def test_fan_profile_maps_to_segment(self) -> None:
        fan = FanProfile(id="u1", display_name="Test", language=Language.FR, player="A9")
        assert fan.to_segment().key == "casual|fr|club:*|player:A9|metric:*"


class TestInsight:
    def _insight(self, **overrides: object) -> Insight:
        data: dict[str, object] = {
            "id": "ins-1",
            "match_id": "M001",
            "moment_id": "mom-M001-7",
            "t": 1400.0,
            "kind": InsightKind.EXPLANATION,
            "segment": Segment(persona=Persona.ANALYST, language=Language.EN),
            "headline": "Pressure is building",
            "body": "Home have pinned Away back for five minutes.",
            "claims": [Claim(text="Pressure index rose to 0.71", evidence=[312], metrics={"pi": 0.71})],
            "verified": True,
            "agent_trace": [AgentName.ORCHESTRATOR, AgentName.EXPLAIN, AgentName.VERIFIER],
        }
        data.update(overrides)
        return Insight.model_validate(data)

    def test_valid(self) -> None:
        assert parse_wire(self._insight().model_dump_json()).msg == "insight"

    def test_llm_insight_without_claims_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="evidenced claim"):
            self._insight(claims=[])

    def test_fallback_insight_may_have_no_claims(self) -> None:
        assert self._insight(claims=[], fallback=True, agent_trace=[AgentName.TEMPLATE]).fallback

    def test_claim_without_evidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Claim(text="made up", evidence=[])


def test_moment_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Moment(
            id="m1", match_id="M001", t=10, minute=0, kind=MomentKind.GOAL,
            importance=1, evidence=[], fallback_text="Goal!",
        )


def test_overlay_rtl_flag() -> None:
    overlay = Overlay(
        overlay_id="ov-1", match_id="M001", show_at=1396, duration_s=6,
        slot=OverlaySlot.LOWER_THIRD, priority=50, segment_key="casual|ar|club:*|player:*|metric:*",
        language=Language.AR, title="الضغط يتصاعد", body="...",
    )
    assert overlay.rtl is True
    assert overlay.model_dump()["rtl"] is True
    assert parse_wire(overlay.model_dump_json()) == overlay

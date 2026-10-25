from pitchmind_contracts import (
    AgentName,
    Claim,
    EventType,
    Insight,
    InsightKind,
    Language,
    MatchEvent,
    MetricName,
    Moment,
    MomentKind,
    OverlaySlot,
    Persona,
    Phase,
    Segment,
    TeamSide,
)
from pitchmind_render import OverlayRenderer, clip, format_number, priority_for
from pitchmind_simulator import build_match_meta

ANALYST = Segment(persona=Persona.ANALYST, language=Language.EN)
ARABIC = Segment(persona=Persona.CASUAL, language=Language.AR, club=TeamSide.HOME)
FRENCH = Segment(persona=Persona.BEGINNER, language=Language.FR)
HADDAD = Segment(persona=Persona.CASUAL, language=Language.EN, player="H10")
SEGMENTS = [ANALYST, ARABIC, FRENCH, HADDAD]


def moment(n: int, kind: MomentKind, t: float, importance: float = 0.6, **metrics: float) -> Moment:
    return Moment(
        id=f"mom-{n}",
        match_id="M1",
        t=t,
        minute=int(t // 60),
        kind=kind,
        importance=importance,
        team=TeamSide.HOME,
        players=["H11"],
        evidence=[10, 11],
        metrics=metrics,
        fallback_text="text",
    )


def insight(m: Moment, segment: Segment, kind: InsightKind, headline: str = "Headline") -> Insight:
    return Insight(
        id=f"ins-{m.id}-{segment.key}",
        match_id="M1",
        moment_id=m.id,
        t=m.t,
        kind=kind,
        segment=segment,
        headline=headline,
        body="Body text.",
        claims=[Claim(text="c", evidence=[11])],
        verified=True,
        agent_trace=[AgentName.ORCHESTRATOR, AgentName.EXPLAIN, AgentName.VERIFIER],
    )


def clock(renderer: OverlayRenderer, t: float) -> None:
    renderer.observe(
        MatchEvent(id=int(t), match_id="M1", t=t, minute=int(t // 60), phase=Phase.FIRST_HALF, type=EventType.FOUL)
    )


def test_insight_becomes_a_lower_third_after_the_current_clock() -> None:
    r = OverlayRenderer(SEGMENTS)
    m = moment(1, MomentKind.PRESSURE_SURGE, 600, pressure_index_after=0.74)
    r.observe(m)
    clock(r, 610)
    (ov,) = r.observe(insight(m, ARABIC, InsightKind.EXPLANATION))
    assert (ov.slot, ov.show_at, ov.duration_s) == (OverlaySlot.LOWER_THIRD, 611.0, 7.0)
    assert ov.segment_key == ARABIC.key and ov.language is Language.AR and ov.rtl
    assert ov.metric is not None and (ov.metric.name, ov.metric.value) == (MetricName.PRESSURE_INDEX, 0.74)
    assert ov.evidence == [11] and ov.priority == priority_for(0.6) and ov.team is TeamSide.HOME


def test_recaps_use_the_recap_card() -> None:
    r = OverlayRenderer(SEGMENTS)
    m = moment(2, MomentKind.PHASE, 2850, importance=0.9)
    r.observe(m)
    (ov,) = r.observe(insight(m, FRENCH, InsightKind.RECAP))
    assert (ov.slot, ov.duration_s) == (OverlaySlot.RECAP_CARD, 20.0)


def test_lower_thirds_queue_but_goals_cut_in() -> None:
    r = OverlayRenderer(SEGMENTS)
    first = moment(1, MomentKind.PRESSURE_SURGE, 100)
    second = moment(2, MomentKind.MOMENTUM_SWING, 101)
    goal = moment(3, MomentKind.GOAL, 102, importance=1.0, xg=0.3)
    for m in (first, second, goal):
        r.observe(m)
    a = r.observe(insight(first, ANALYST, InsightKind.EXPLANATION))[0]
    b = r.observe(insight(second, ANALYST, InsightKind.EXPLANATION))[0]
    g = r.observe(insight(goal, ANALYST, InsightKind.COMMENTARY))[0]
    assert b.show_at >= a.show_at + a.duration_s + 2  # waits for the first to clear
    assert g.show_at == 103.0 and g.priority == 100  # the goal does not wait


def test_redelivered_insight_is_rendered_once() -> None:
    r = OverlayRenderer(SEGMENTS)
    m = moment(1, MomentKind.BIG_CHANCE, 100, xg=0.41)
    r.observe(m)
    ins = insight(m, ANALYST, InsightKind.EXPLANATION)
    assert len(r.observe(ins)) == 1
    assert r.observe(ins) == []


def test_speed_record_tags_every_segment_in_its_language_without_an_agent() -> None:
    r = OverlayRenderer(SEGMENTS)
    r.observe(build_match_meta("M1", seed=7))
    tags = r.observe(moment(7, MomentKind.SPEED_THRESHOLD, 4330, importance=0.4, player_speed_kmh=35.2))
    by_lang = {t.language: t for t in tags}
    assert set(by_lang) == {Language.EN, Language.AR, Language.FR}  # not the H10 player-focus fan
    assert all(t.slot is OverlaySlot.PLAYER_TAG and t.player_id == "H11" for t in tags)
    assert by_lang[Language.EN].body == "Kenji Arai — 35.2 km/h"
    assert by_lang[Language.FR].body == "Kenji Arai — 35,2 km/h"
    assert by_lang[Language.AR].title == "أعلى سرعة"


def test_text_helpers() -> None:
    assert clip("x" * 70, 60) == "x" * 59 + "…"
    assert format_number(0.38, Language.FR) == "0,38" and format_number(0.38, Language.AR) == "0.38"
    assert priority_for(0) == 40 and priority_for(1) == 100

from itertools import pairwise

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
    Overlay,
    OverlaySlot,
    Persona,
    Phase,
    Segment,
    TeamSide,
)
from pitchmind_render import (
    GAP_S,
    LEAD_S,
    LOWER_THIRD_GAP_S,
    MAX_LOWER_THIRD_DELAY_S,
    OverlayRenderer,
    clip,
    format_number,
    priority_for,
)
from pitchmind_simulator import build_match_meta

ANALYST = Segment(persona=Persona.ANALYST, language=Language.EN)
ARABIC = Segment(persona=Persona.CASUAL, language=Language.AR, club=TeamSide.HOME)
FRENCH = Segment(persona=Persona.BEGINNER, language=Language.FR)
HADDAD = Segment(persona=Persona.CASUAL, language=Language.EN, player="H10")
SEGMENTS = [ANALYST, ARABIC, FRENCH, HADDAD]


def moment(
    n: int, kind: MomentKind, t: float, importance: float = 0.6, match_id: str = "M1", **metrics: float
) -> Moment:
    return Moment(
        id=f"mom-{n}",
        match_id=match_id,
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
        match_id=m.match_id,
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
    assert b.show_at == a.show_at + a.duration_s + LOWER_THIRD_GAP_S  # waits 20 s after the first clears
    assert g.show_at == 103.0 and g.priority == 100  # the goal does not wait


def test_at_most_one_lower_third_per_20_s_per_segment() -> None:
    r = OverlayRenderer(SEGMENTS)
    shown: list[Overlay] = []
    for n in range(6):  # a moment every 25 s: each lower third waits a little, none long enough to drop
        m = moment(n, MomentKind.PRESSURE_SURGE, 300 + 25 * n)
        r.observe(m)
        shown += r.observe(insight(m, ANALYST, InsightKind.EXPLANATION))
        shown += r.observe(insight(m, ARABIC, InsightKind.COMMENTARY))
    for segment in (ANALYST, ARABIC):
        mine = [o for o in shown if o.segment_key == segment.key]
        assert len(mine) == 6 and all(o.slot is OverlaySlot.LOWER_THIRD for o in mine)
        for earlier, later in pairwise(mine):
            assert later.show_at >= earlier.show_at + earlier.duration_s + LOWER_THIRD_GAP_S
    first_analyst, first_arabic = (next(o for o in shown if o.segment_key == s.key) for s in (ANALYST, ARABIC))
    assert first_analyst.show_at == first_arabic.show_at == 301.0  # segments do not hold each other up


def busy_spell(r: OverlayRenderer) -> list[list[Overlay]]:
    """Three analyst lower thirds a second apart: airs at 301, waits 26 s, would wait 52 s."""
    out: list[list[Overlay]] = []
    for n in range(3):
        m = moment(n, MomentKind.PRESSURE_SURGE, 300 + n)
        r.observe(m)
        out.append(r.observe(insight(m, ANALYST, InsightKind.EXPLANATION)))
    return out


def test_a_busy_spell_drops_the_stale_lower_third_and_keeps_the_next_on_schedule() -> None:
    r = OverlayRenderer(SEGMENTS)
    (a,), (b,), stale = busy_spell(r)
    assert (a.show_at, b.show_at) == (301.0, 328.0)
    assert b.show_at - (301 + LEAD_S) <= MAX_LOWER_THIRD_DELAY_S  # the second waits 26 s and airs
    assert b.show_at + b.duration_s + LOWER_THIRD_GAP_S - (302 + LEAD_S) > MAX_LOWER_THIRD_DELAY_S  # the third, 52 s
    assert stale == []
    slow = moment(9, MomentKind.BIG_CHANCE, 330, xg=0.2)
    r.observe(slow)
    clock(r, 400)  # its insight arrives 70 s after the moment: agent latency is not queue delay
    (on_time,) = r.observe(insight(slow, ANALYST, InsightKind.EXPLANATION))
    assert on_time.show_at == 400 + LEAD_S


def test_a_goal_still_cuts_into_a_full_queue() -> None:
    r = OverlayRenderer(SEGMENTS)
    busy_spell(r)
    goal = moment(5, MomentKind.GOAL, 302, importance=1.0, xg=0.4)
    r.observe(goal)
    (g,) = r.observe(insight(goal, ANALYST, InsightKind.COMMENTARY))
    assert (g.slot, g.priority, g.show_at) == (OverlaySlot.LOWER_THIRD, 100, 303.0)


def test_a_dropped_lower_third_does_not_reserve_its_slot() -> None:
    r = OverlayRenderer(SEGMENTS)
    _, (b,), stale = busy_spell(r)
    assert stale == []
    m = moment(6, MomentKind.MOMENTUM_SWING, 315)
    r.observe(m)
    (d,) = r.observe(insight(m, ANALYST, InsightKind.EXPLANATION))
    # It takes the 355 s the dropped one would have had; had that been reserved, it would wait 66 s and drop too.
    assert d.show_at == b.show_at + b.duration_s + LOWER_THIRD_GAP_S == 355.0


def test_the_next_match_of_a_live_loop_starts_from_a_clean_clock_and_queue() -> None:
    r = OverlayRenderer(SEGMENTS)
    r.observe(build_match_meta("M1", seed=7))
    whistle = moment(1, MomentKind.PRESSURE_SURGE, 5790)
    r.observe(whistle)
    (w,) = r.observe(insight(whistle, ANALYST, InsightKind.EXPLANATION))
    r.observe(build_match_meta("M1", seed=7))  # the simulator's re-announcement keeps the match
    queued = moment(2, MomentKind.MOMENTUM_SWING, 5791)
    r.observe(queued)
    (q,) = r.observe(insight(queued, ANALYST, InsightKind.EXPLANATION))
    assert q.show_at == w.show_at + w.duration_s + LOWER_THIRD_GAP_S  # still queued behind the first

    r.observe(build_match_meta("M2", seed=7))
    kickoff = moment(1, MomentKind.PRESSURE_SURGE, 600, match_id="M2")  # ids start again too
    r.observe(kickoff)
    (k,) = r.observe(insight(kickoff, ANALYST, InsightKind.EXPLANATION))
    assert (k.match_id, k.show_at) == ("M2", 601.0)  # not after the previous match's final whistle


def test_late_messages_of_the_finished_match_are_ignored() -> None:
    r = OverlayRenderer(SEGMENTS)
    r.observe(build_match_meta("M1", seed=7))
    old = moment(1, MomentKind.PRESSURE_SURGE, 5790)
    r.observe(old)
    r.observe(build_match_meta("M2", seed=7))
    assert r.observe(insight(old, ANALYST, InsightKind.EXPLANATION)) == []
    assert r.observe(moment(2, MomentKind.SPEED_THRESHOLD, 5795, player_speed_kmh=35.0)) == []
    clock(r, 5799)  # a late event of M1 must not move M2's clock
    fresh = moment(3, MomentKind.PRESSURE_SURGE, 120, match_id="M2")
    r.observe(fresh)
    (f,) = r.observe(insight(fresh, ANALYST, InsightKind.EXPLANATION))
    assert f.show_at == 121.0


def test_a_moment_that_overtakes_its_match_metadata_still_starts_the_next_match() -> None:
    r = OverlayRenderer(SEGMENTS)
    r.observe(build_match_meta("M1", seed=7))
    whistle = moment(1, MomentKind.PRESSURE_SURGE, 5790)
    r.observe(whistle)
    early = moment(2, MomentKind.PRESSURE_SURGE, 300, match_id="M2")  # moments travel apart from the metadata
    r.observe(early)
    r.observe(build_match_meta("M2", seed=7))
    (ov,) = r.observe(insight(early, ANALYST, InsightKind.EXPLANATION))
    assert (ov.match_id, ov.show_at) == ("M2", 301.0)
    assert ov.priority == priority_for(early.importance) and ov.team is TeamSide.HOME  # the moment was kept
    assert r.observe(insight(whistle, ANALYST, InsightKind.EXPLANATION)) == []  # M1 is finished


def test_the_queue_restarts_20_s_after_a_goal_clears() -> None:
    r = OverlayRenderer(SEGMENTS)
    goal = moment(1, MomentKind.GOAL, 200, importance=1.0, xg=0.3)
    r.observe(goal)
    (g,) = r.observe(insight(goal, ANALYST, InsightKind.COMMENTARY))
    after = moment(2, MomentKind.PRESSURE_SURGE, 205)
    r.observe(after)
    (n,) = r.observe(insight(after, ANALYST, InsightKind.EXPLANATION))
    assert g.show_at == 201.0
    assert n.show_at == g.show_at + g.duration_s + LOWER_THIRD_GAP_S


def test_other_slots_keep_the_short_gap() -> None:
    r = OverlayRenderer([ANALYST])
    (a,) = r.observe(moment(1, MomentKind.SPEED_THRESHOLD, 500, importance=0.4, player_speed_kmh=34.0))
    (b,) = r.observe(moment(2, MomentKind.SPEED_THRESHOLD, 501, importance=0.4, player_speed_kmh=35.0))
    assert a.slot is b.slot is OverlaySlot.PLAYER_TAG
    assert b.show_at == a.show_at + a.duration_s + GAP_S


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

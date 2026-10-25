import math
from collections import Counter
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from pitchmind_contracts import (
    EventType,
    MatchEvent,
    MatchMeta,
    Moment,
    MomentKind,
    Outcome,
    Phase,
    StatSnapshot,
    TeamSide,
    parse_wire,
)
from pitchmind_moments import MatchContext, MomentDetector, detect
from pitchmind_moments import detector as detector_module
from pitchmind_moments.__main__ import main as cli_main
from pitchmind_moments.rules import PressureSurgeRule
from pitchmind_simulator import DEMO, ORGANIC, build_match_meta, simulate
from pitchmind_stats import replay

H, A = TeamSide.HOME, TeamSide.AWAY


class Feed:
    def __init__(self) -> None:
        self.detector = MomentDetector(build_match_meta("T1", seed=1))
        self.ids = count()
        self.moments: list[Moment] = []

    def event(self, t: float, type: EventType, **fields: Any) -> MatchEvent:
        return MatchEvent(
            id=next(self.ids), match_id="T1", t=t, minute=int(t // 60), phase=Phase.FIRST_HALF, type=type, **fields
        )

    def push(self, t: float, type: EventType, **fields: Any) -> MatchEvent:
        event = self.event(t, type, **fields)
        self.moments += self.detector.on_event(event)
        return event


class TestEventRules:
    def test_goal_with_assist_cites_pass_shot_and_goal(self) -> None:
        feed = Feed()
        p = feed.push(
            10,
            EventType.PASS,
            team=H,
            player="H10",
            receiver="H9",
            start=(70, 34),
            end=(96, 33),
            outcome=Outcome.SUCCESS,
            distance_m=26.0,
        )
        s = feed.push(12, EventType.SHOT, team=H, player="H9", start=(96, 33), outcome=Outcome.GOAL)
        g = feed.push(13, EventType.GOAL, team=H, player="H9", related_event_id=s.id)
        (m,) = feed.moments
        assert m.kind is MomentKind.GOAL and m.team is H
        assert m.evidence == [p.id, s.id, g.id]
        assert m.players == ["H9", "H10"]
        assert m.metrics["home_goals"] == 1 and m.metrics["away_goals"] == 0
        assert 0.25 < m.metrics["xg"] < 0.35 and m.metrics["pass_distance_m"] == 26.0
        assert m.fallback_text == "Goal for North City FC: Kaya scores, assisted by Haddad. NCF 1-0 HBU."

    def test_saved_big_chance_waits_for_the_keeper(self) -> None:
        feed = Feed()
        s = feed.push(10, EventType.SHOT, team=H, player="H10", start=(98, 35), outcome=Outcome.ON_TARGET)
        assert feed.moments == []
        save = feed.push(11, EventType.SAVE, team=A, player="A1", start=(1, 34), related_event_id=s.id)
        (m,) = feed.moments
        assert m.kind is MomentKind.BIG_CHANCE and m.evidence == [s.id, save.id]
        assert m.players == ["H10", "A1"] and m.metrics["saved"] == 1.0
        assert "saved by Sandvik" in m.fallback_text

    def test_low_xg_shot_is_not_a_big_chance(self) -> None:
        feed = Feed()
        feed.push(10, EventType.SHOT, team=H, player="H10", start=(80, 34), outcome=Outcome.OFF_TARGET)
        assert feed.moments == []

    def test_speed_record_only_when_new_and_elite(self) -> None:
        feed = Feed()
        for t, speed in ((5, 33.0), (9, 34.5), (12, 34.2), (20, 35.2)):
            feed.push(t, EventType.SPRINT, team=H, player="H11", start=(40, 60), end=(80, 60), player_speed_kmh=speed)
        assert [m.metrics["player_speed_kmh"] for m in feed.moments] == [34.5, 35.2]
        assert feed.moments[-1].metrics["previous_record_kmh"] == 34.5

    def test_card_cites_the_foul(self) -> None:
        feed = Feed()
        foul = feed.push(10, EventType.FOUL, team=A, player="A5", start=(30, 40))
        card = feed.push(12, EventType.CARD, team=A, player="A5", outcome=Outcome.RED)
        (m,) = feed.moments
        assert m.evidence == [foul.id, card.id] and m.importance == 0.8

    def test_redelivered_event_is_ignored(self) -> None:
        feed = Feed()
        s = feed.push(12, EventType.SHOT, team=H, player="H9", start=(96, 33), outcome=Outcome.GOAL)
        goal = feed.event(13, EventType.GOAL, team=H, player="H9", related_event_id=s.id)
        assert len(feed.detector.on_event(goal)) == 1
        assert feed.detector.on_event(goal) == []
        assert feed.detector.ctx.score[H] == 1


def run(meta: MatchMeta, seed: int, demo: bool = False) -> tuple[list[MatchEvent], list[Moment]]:
    events = [m for m in simulate(meta, DEMO if demo else ORGANIC, seed=seed) if isinstance(m, MatchEvent)]
    return events, detect(meta, events, replay(meta, events))


@pytest.fixture(scope="module")
def demo() -> tuple[list[MatchEvent], list[Moment]]:
    return run(build_match_meta("M001", seed=7), seed=7, demo=True)


def find(moments: list[Moment], kind: MomentKind, team: TeamSide | None = None) -> list[Moment]:
    return [m for m in moments if m.kind is kind and (team is None or m.team is team)]


class TestDemoStoryline:
    def test_every_moment_is_grounded(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        events, moments = demo
        ids = {e.id for e in events}
        for m in moments:
            assert m.evidence and set(m.evidence) <= ids, m.id
            assert m.fallback_text
            assert all(math.isfinite(v) for v in m.metrics.values()), m.id
        assert len({m.id for m in moments}) == len(moments)

    def test_goals(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        _, moments = demo
        goals = find(moments, MomentKind.GOAL)
        assert [(g.minute, g.players[0]) for g in goals] == [(9, "A9"), (61, "H9"), (86, "H10")]
        assert goals[1].players == ["H9", "H10"]  # Haddad's assist is credited

    def test_haddad_big_chance_saved_by_sandvik(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        _, moments = demo
        chance = next(m for m in find(moments, MomentKind.BIG_CHANCE) if m.minute == 33)
        assert chance.players == ["H10", "A1"] and chance.metrics["xg"] >= 0.35

    def test_pressing_spells(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        _, moments = demo
        home_surges = [m.minute for m in find(moments, MomentKind.PRESSURE_SURGE, team=H)]
        assert any(18 <= m <= 34 for m in home_surges)
        assert any(51 <= m <= 62 for m in home_surges)

    def test_chaos_window(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        _, moments = demo
        chaos = find(moments, MomentKind.CONTROL_SHIFT)
        assert any(78 <= m.minute <= 84 and m.metrics["control_chaos_after"] >= 0.8 for m in chaos)

    def test_chaos_during_a_press_is_not_announced_twice(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        _, moments = demo
        surges = [m.t for m in find(moments, MomentKind.PRESSURE_SURGE)]
        for chaos in find(moments, MomentKind.CONTROL_SHIFT):
            assert not any(0 <= chaos.t - t <= 360 for t in surges)

    def test_speed_record(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        _, moments = demo
        (speed,) = find(moments, MomentKind.SPEED_THRESHOLD)
        assert (speed.minute, speed.players, speed.metrics["player_speed_kmh"]) == (72, ["H11"], 35.2)

    def test_half_and_full_time_summaries(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        events, moments = demo
        ht, ft = find(moments, MomentKind.PHASE)
        assert (ht.metrics["home_goals"], ht.metrics["away_goals"]) == (0, 1)
        assert (ft.metrics["home_goals"], ft.metrics["away_goals"]) == (2, 1)
        assert {e.id for e in events if e.type is EventType.GOAL} <= set(ft.evidence)
        assert ft.fallback_text == "Full-time: NCF 2-1 HBU."


def test_organic_matches_are_not_flooded_with_moments() -> None:
    kinds: Counter[MomentKind] = Counter()
    for seed in range(1, 6):
        _, moments = run(build_match_meta(f"M{seed}", seed=seed), seed=seed)
        kinds.update(m.kind for m in moments)
    per_match = {k: v / 5 for k, v in kinds.items()}
    assert per_match.get(MomentKind.PRESSURE_SURGE, 0) <= 1.0
    assert per_match.get(MomentKind.CONTROL_SHIFT, 0) <= 1.5
    assert per_match.get(MomentKind.MOMENTUM_SWING, 0) <= 3.0
    assert sum(per_match.values()) <= 20


class TestReviewRegressions:
    def _pass_to_scorer(self, feed: Feed, t: float) -> MatchEvent:
        return feed.push(
            t,
            EventType.PASS,
            team=H,
            player="H10",
            receiver="H9",
            start=(70, 34),
            end=(95, 33),
            outcome=Outcome.SUCCESS,
            distance_m=25.0,
        )

    def _shot_and_goal(self, feed: Feed, t: float) -> None:
        s = feed.push(t, EventType.SHOT, team=H, player="H9", start=(95, 33), outcome=Outcome.GOAL)
        feed.push(t + 1, EventType.GOAL, team=H, player="H9", related_event_id=s.id)

    def test_assist_survives_a_press_and_the_scorers_dribble(self) -> None:
        feed = Feed()
        p = self._pass_to_scorer(feed, 10)
        feed.push(11, EventType.PRESSURE, team=A, player="A5", start=(10, 35))
        feed.push(12, EventType.CARRY, team=H, player="H9", start=(95, 33), end=(97, 34), player_speed_kmh=20)
        self._shot_and_goal(feed, 13)
        (goal,) = feed.moments
        assert goal.players == ["H9", "H10"] and p.id in goal.evidence

    def test_no_assist_across_a_change_of_possession(self) -> None:
        feed = Feed()
        self._pass_to_scorer(feed, 10)
        feed.push(11, EventType.POSSESSION_CHANGE, team=A)
        feed.push(12, EventType.POSSESSION_CHANGE, team=H)
        self._shot_and_goal(feed, 13)
        (goal,) = feed.moments
        assert goal.players == ["H9"]

    def test_saved_chance_is_emitted_even_if_the_save_never_arrives(self) -> None:
        feed = Feed()
        s = feed.push(10, EventType.SHOT, team=H, player="H10", start=(98, 35), outcome=Outcome.ON_TARGET)
        feed.push(25, EventType.PASS, team=A, player="A4", receiver="A8", start=(20, 30), end=(35, 30),
                  outcome=Outcome.SUCCESS)  # fmt: skip
        (chance,) = feed.moments
        assert chance.evidence == [s.id] and chance.players == ["H10"]
        assert chance.fallback_text.endswith("is saved.")

    def test_card_does_not_cite_an_old_foul(self) -> None:
        feed = Feed()
        feed.push(10, EventType.FOUL, team=A, player="A5", start=(30, 40))
        card = feed.push(200, EventType.CARD, team=A, player="A5", outcome=Outcome.YELLOW)
        assert feed.moments[0].evidence == [card.id]

    def test_simultaneous_surges_are_both_reported(self, demo: tuple[list[MatchEvent], list[Moment]]) -> None:
        meta = build_match_meta("M001", seed=7)
        events, _ = demo
        template = replay(meta, events)[20]
        rule = PressureSurgeRule()
        ctx = MatchContext(meta)

        def snap(t: float, pressure: float) -> StatSnapshot:
            return template.model_copy(
                update={
                    "t": t,
                    "home": template.home.model_copy(update={"pressure_index": pressure}),
                    "away": template.away.model_copy(update={"pressure_index": pressure}),
                }
            )

        for t, pressure in ((1000.0, 0.3), (1060.0, 0.6)):
            ctx.add_snapshot(snap(t, pressure))
            moments = rule.on_snapshot(ctx, ctx.snapshots[-1])
        assert sorted(m.team for m in moments if m.team) == [A, H]

    def test_live_snapshots_arriving_early_give_identical_moments(
        self, demo: tuple[list[MatchEvent], list[Moment]]
    ) -> None:
        meta = build_match_meta("M001", seed=7)
        events, in_order = demo
        by_event: dict[int, list[StatSnapshot]] = {}
        for s in replay(meta, events):
            by_event.setdefault(s.last_event_id, []).append(s)
        detector, live = MomentDetector(meta), []
        lag = 6  # the stats topic is consumed 6 events ahead of the events topic
        for i, event in enumerate(events):
            if i + lag < len(events):
                for s in by_event.get(events[i + lag].id, []):
                    live += detector.on_snapshot(s)
            live += detector.on_event(event)
        assert detector.held_snapshots == 0
        assert [m.model_dump() for m in live] == [m.model_dump() for m in in_order]

    def test_held_snapshots_are_bounded_when_events_stall(
        self,
        demo: tuple[list[MatchEvent], list[Moment]],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(detector_module, "MAX_HELD_SNAPSHOTS", 20)
        meta = build_match_meta("M001", seed=7)
        events, _ = demo
        detector = MomentDetector(meta)
        detector.on_event(events[0])  # then the events feed stalls; only snapshots keep coming
        with caplog.at_level("WARNING"):
            for s in replay(meta, events)[1:60]:
                detector.on_snapshot(s)
        assert detector.held_snapshots == 20
        assert "events feed stalled" in caplog.text

    def test_organic_assists_are_credited(self) -> None:
        real = credited = 0
        for seed in range(1, 11):
            events, moments = run(build_match_meta(f"M{seed}", seed=seed), seed=seed)
            by_id = {e.id: e for e in events}
            credited += sum(len(m.players) > 1 for m in moments if m.kind is MomentKind.GOAL)
            for goal in (e for e in events if e.type is EventType.GOAL):
                assert goal.related_event_id is not None
                shot = by_id[goal.related_event_id]
                for e in reversed([e for e in events if e.id < shot.id and shot.t - e.t <= 15]):
                    if e.type is EventType.POSSESSION_CHANGE:
                        break
                    if e.type is EventType.PASS and e.outcome is Outcome.SUCCESS and e.receiver == shot.player:
                        real += 1
                        break
        assert credited == real


def test_cli_writes_moments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    meta = build_match_meta("M001", seed=7)
    source = tmp_path / "M001.jsonl"
    source.write_text("\n".join(m.model_dump_json() for m in simulate(meta, DEMO, seed=7)), encoding="utf-8")
    cli_main([str(source)])
    lines = (tmp_path / "M001.moments.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines and all(isinstance(parse_wire(line), Moment) for line in lines)
    assert "Full-time: NCF 2-1 HBU." in capsys.readouterr().out


def test_cli_rejects_a_match_without_events(tmp_path: Path) -> None:
    source = tmp_path / "empty.jsonl"
    source.write_text(build_match_meta("M001", seed=7).model_dump_json(), encoding="utf-8")
    with pytest.raises(SystemExit):
        cli_main([str(source)])

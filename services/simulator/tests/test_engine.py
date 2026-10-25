from collections.abc import Sequence
from itertools import pairwise

import pytest
from pitchmind_contracts import EventType, MatchEvent, MatchMeta, Outcome, Phase, TeamSide
from pitchmind_football import expected_goals, expected_threat, flip, pass_difficulty
from pitchmind_simulator import DEMO, ORGANIC, MatchEngine, build_match_meta, simulate


def events_of(messages: list[MatchMeta | MatchEvent]) -> list[MatchEvent]:
    return [m for m in messages if isinstance(m, MatchEvent)]


@pytest.fixture(scope="module")
def demo() -> list[MatchEvent]:
    return events_of(simulate(build_match_meta("M001", seed=7), DEMO, seed=7))


class TestFootballModels:
    def test_xg_reference_values(self) -> None:
        assert 0.45 < expected_goals((99.5, 34)) < 0.65  # six-yard box
        assert 0.15 < expected_goals((94, 34)) < 0.30  # penalty spot
        assert expected_goals((85, 34)) < 0.12  # edge of the box
        assert expected_goals((94, 34), under_pressure=True) < expected_goals((94, 34))

    def test_pass_difficulty_grows_with_length_and_pressure(self) -> None:
        short = pass_difficulty((40, 34), (50, 34), under_pressure=False)
        long = pass_difficulty((40, 34), (80, 34), under_pressure=False)
        assert short < long
        assert pass_difficulty((40, 34), (50, 34), under_pressure=True) > short

    def test_threat_rises_towards_goal(self) -> None:
        assert expected_threat((30, 34)) < expected_threat((70, 34)) < expected_threat((90, 34))
        assert expected_threat((94, 34)) > expected_threat((94, 5))
        assert expected_threat((52.5, 34)) < 0.02

    def test_flip_is_an_involution(self) -> None:
        assert flip(flip((12.3, 45.6))) == (12.3, 45.6)


class TestStreamShape:
    def test_meta_first_then_ordered_events(self, demo: list[MatchEvent]) -> None:
        messages = simulate(build_match_meta("M001", seed=7), DEMO, seed=7)
        assert isinstance(messages[0], MatchMeta)
        assert [e.id for e in demo] == list(range(len(demo)))
        assert all(a.t <= b.t for a, b in pairwise(demo))

    def test_phases_in_order(self, demo: list[MatchEvent]) -> None:
        phases = [e.phase for e in demo if e.type is EventType.PHASE_CHANGE]
        assert phases == [Phase.FIRST_HALF, Phase.HALF_TIME, Phase.SECOND_HALF, Phase.FULL_TIME]

    def test_deterministic_for_a_seed(self) -> None:
        meta = build_match_meta("M009", seed=9)
        first = [e.model_dump_json() for e in events_of(simulate(meta, ORGANIC, seed=9))]
        second = [e.model_dump_json() for e in events_of(simulate(meta, ORGANIC, seed=9))]
        assert first == second

    def test_engine_is_single_use(self) -> None:
        engine = MatchEngine(build_match_meta("M001", seed=7), ORGANIC, seed=7)
        list(engine.run())
        with pytest.raises(RuntimeError, match="only be called once"):
            list(engine.run())

    def test_organic_stoppage_time_varies_with_seed(self) -> None:
        halves = {MatchEngine(build_match_meta(f"M{s}", seed=s), ORGANIC, seed=s).first_half_s for s in range(1, 6)}
        assert len(halves) > 1
        assert all(2760 <= h <= 2940 for h in halves)

    def test_different_seeds_differ(self) -> None:
        a = events_of(simulate(build_match_meta("M1", seed=1), ORGANIC, seed=1))
        b = events_of(simulate(build_match_meta("M2", seed=2), ORGANIC, seed=2))
        assert len(a) != len(b) or a[10].model_dump() != b[10].model_dump()


@pytest.fixture(scope="module")
def matches() -> list[list[MatchEvent]]:
    return [events_of(simulate(build_match_meta(f"M{s}", seed=s), ORGANIC, seed=s)) for s in range(1, 7)]


class TestRealism:
    """Averages over a few organic matches must look like real football."""

    @staticmethod
    def mean(values: Sequence[float]) -> float:
        return sum(values) / len(values)

    def test_pass_accuracy_and_volume(self, matches: list[list[MatchEvent]]) -> None:
        accs: list[float] = []
        counts: list[int] = []
        for events in matches:
            passes = [e for e in events if e.type is EventType.PASS]
            counts.append(len(passes))
            accs.append(100 * sum(e.outcome is Outcome.SUCCESS for e in passes) / len(passes))
        assert 74 <= self.mean(accs) <= 88
        assert 750 <= self.mean(counts) <= 1150

    def test_shots_and_goals(self, matches: list[list[MatchEvent]]) -> None:
        shots = [sum(e.type is EventType.SHOT for e in m) for m in matches]
        goals = [sum(e.type is EventType.GOAL for e in m) for m in matches]
        assert 15 <= self.mean(shots) <= 35
        assert 1.0 <= self.mean(goals) <= 4.5

    def test_every_goal_follows_a_scoring_shot(self, matches: list[list[MatchEvent]]) -> None:
        for events in matches:
            by_id = {e.id: e for e in events}
            for goal in (e for e in events if e.type is EventType.GOAL):
                assert goal.related_event_id is not None
                shot = by_id[goal.related_event_id]
                assert shot.type is EventType.SHOT and shot.outcome is Outcome.GOAL
                assert shot.team is goal.team

    def test_valid_substitutions(self, matches: list[list[MatchEvent]]) -> None:
        for events in matches:
            subs = [e for e in events if e.type is EventType.SUBSTITUTION]
            for side in TeamSide:
                assert sum(s.team is side for s in subs) <= 5
            assert len({s.receiver for s in subs}) == len(subs)


class TestDemoScenario:
    def test_comeback_score(self, demo: list[MatchEvent]) -> None:
        goals = [e for e in demo if e.type is EventType.GOAL]
        assert [(g.team, g.player, g.minute) for g in goals] == [
            (TeamSide.AWAY, "A9", 9),
            (TeamSide.HOME, "H9", 61),
            (TeamSide.HOME, "H10", 86),
        ]

    def test_haddad_assists_the_equaliser(self, demo: list[MatchEvent]) -> None:
        by_id = {e.id: e for e in demo}
        equaliser = next(e for e in demo if e.type is EventType.GOAL and e.player == "H9")
        assert equaliser.related_event_id is not None
        shot = by_id[equaliser.related_event_id]
        assist = by_id[shot.id - 1]
        assert assist.type is EventType.PASS and assist.player == "H10" and assist.receiver == "H9"

    def test_record_sprint_is_the_fastest(self, demo: list[MatchEvent]) -> None:
        sprints = [e for e in demo if e.type is EventType.SPRINT]
        fastest = max(sprints, key=lambda e: e.player_speed_kmh or 0)
        assert (fastest.player, fastest.player_speed_kmh, fastest.minute) == ("H11", 35.2, 72)

    def test_scheduled_substitutions(self, demo: list[MatchEvent]) -> None:
        subs = [(e.player, e.receiver) for e in demo if e.type is EventType.SUBSTITUTION]
        assert subs[:2] == [("H8", "H14"), ("A4", "A14")]

    def test_home_presses_more_during_scripted_spell(self, demo: list[MatchEvent]) -> None:
        def presses(side: TeamSide) -> int:
            return sum(
                e.type is EventType.PRESSURE and e.team is side and 23 <= e.minute < 34 and e.phase is Phase.FIRST_HALF
                for e in demo
            )

        assert presses(TeamSide.HOME) > presses(TeamSide.AWAY)

    def test_engine_tracks_final_score(self) -> None:
        engine = MatchEngine(build_match_meta("M001", seed=7), DEMO, seed=7)
        list(engine.run())
        assert engine.score == {TeamSide.HOME: 2, TeamSide.AWAY: 1}

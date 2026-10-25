from itertools import count
from pathlib import Path
from typing import Any

import pytest
from pitchmind_contracts import EventType, MatchEvent, MatchMeta, Outcome, Phase, StatSnapshot, TeamSide, parse_wire
from pitchmind_football import expected_goals
from pitchmind_simulator import DEMO, ORGANIC, Scenario, build_match_meta, simulate
from pitchmind_stats import StatsEngine, replay
from pitchmind_stats.__main__ import main as cli_main

H, A = TeamSide.HOME, TeamSide.AWAY
Point = tuple[float, float]


@pytest.fixture
def meta() -> MatchMeta:
    return build_match_meta("T1", seed=1)


class Feed:
    """Builds valid events with increasing ids and pushes them into an engine."""

    def __init__(self, meta: MatchMeta, **engine_kwargs: Any) -> None:
        self.engine = StatsEngine(meta, **engine_kwargs)
        self.ids = count()
        self.snapshots: list[StatSnapshot] = []

    def push(self, t: float, type: EventType, **fields: Any) -> MatchEvent:
        event = MatchEvent(
            id=next(self.ids), match_id="T1", t=t, minute=int(t // 60), phase=Phase.FIRST_HALF, type=type, **fields
        )
        if (snap := self.engine.apply(event)) is not None:
            self.snapshots.append(snap)
        return event

    def pass_(self, t: float, team: TeamSide, ok: bool = True, start: Point = (40, 34), end: Point = (55, 34)) -> None:
        player, receiver = ("H8", "H10") if team is H else ("A8", "A10")
        self.push(
            t,
            EventType.PASS,
            team=team,
            player=player,
            receiver=receiver,
            start=start,
            end=end,
            outcome=Outcome.SUCCESS if ok else Outcome.FAILURE,
        )


class TestCounting:
    def test_possession_is_time_weighted(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        feed.pass_(0, H)
        feed.push(30, EventType.POSSESSION_CHANGE, team=A)  # home had it for 30 s
        feed.pass_(31, A)
        feed.push(120, EventType.POSSESSION_CHANGE, team=H)  # away for 90 s
        snap = feed.engine.snapshot()
        assert snap.home.possession_pct == 25.0
        assert snap.away.possession_pct == 75.0

    def test_pass_accuracy_and_player_counts(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        for i, ok in enumerate([True, True, True, False]):
            feed.pass_(i * 5, H, ok=ok)
        snap = feed.engine.snapshot()
        assert (snap.home.passes, snap.home.pass_accuracy_pct) == (4, 75.0)
        h8 = next(p for p in snap.players if p.player_id == "H8")
        assert (h8.passes, h8.pass_accuracy_pct, h8.touches) == (4, 75.0, 4)

    def test_xg_and_goal(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        shot = feed.push(10, EventType.SHOT, team=H, player="H9", start=(94.0, 34.0), outcome=Outcome.GOAL)
        feed.push(12, EventType.GOAL, team=H, player="H9", related_event_id=shot.id)
        snap = feed.engine.snapshot()
        assert snap.home.xg == round(expected_goals((94.0, 34.0)), 2)
        assert (snap.home.shots, snap.home.shots_on_target, snap.score.home) == (1, 1, 1)
        assert next(p for p in snap.players if p.player_id == "H9").xg == snap.home.xg

    def test_substitution_splits_minutes(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        feed.push(600, EventType.SUBSTITUTION, team=H, player="H8", receiver="H14")
        feed.pass_(1200, H)
        players = {p.player_id: p for p in feed.engine.snapshot().players}
        rate = {pid: players[pid].distance_covered_m / 10 for pid in ("H8", "H14")}  # both played 10 min
        assert 100 <= rate["H8"] <= 125 and 100 <= rate["H14"] <= 125
        assert "H17" not in players  # an unused substitute does not appear

    def test_top_speed_and_sprints(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        for t, speed in ((5, 34.1), (9, 31.0)):
            feed.push(
                t, EventType.SPRINT, team=H, player="H11", start=(40.0, 60.0), end=(80.0, 60.0), player_speed_kmh=speed
            )
        h11 = next(p for p in feed.engine.snapshot().players if p.player_id == "H11")
        assert (h11.top_speed_kmh, h11.sprints) == (34.1, 2)


class TestDerivedMetrics:
    def test_pressure_index_rises_with_high_pressing_and_expires(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        for i in range(15):
            feed.push(i * 10, EventType.PRESSURE, team=H, player="H9", start=(95.0, 30.0))
        assert feed.engine.pressure_index(H) > 0.5
        assert feed.engine.pressure_index(A) == 0.0
        feed.pass_(600, H)  # the 5-minute window has moved past every press
        assert feed.engine.pressure_index(H) == 0.0

    def test_high_presses_count_more_than_deep_ones(self, meta: MatchMeta) -> None:
        high, deep = Feed(meta), Feed(meta)
        for i in range(10):
            high.push(i * 10, EventType.PRESSURE, team=H, player="H9", start=(95.0, 30.0))
            deep.push(i * 10, EventType.PRESSURE, team=H, player="H4", start=(15.0, 30.0))
        assert high.engine.pressure_index(H) > deep.engine.pressure_index(H)

    def test_momentum_follows_threat(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        for i in range(4):
            feed.push(i * 20, EventType.SHOT, team=H, player="H9", start=(96.0, 34.0), outcome=Outcome.OFF_TARGET)
        assert feed.engine.momentum() > 0.4
        for i in range(8):
            feed.push(100 + i * 20, EventType.SHOT, team=A, player="A9", start=(96.0, 34.0), outcome=Outcome.OFF_TARGET)
        assert feed.engine.momentum() < 0

    def test_chaos_from_turnovers_and_fouls(self, meta: MatchMeta) -> None:
        calm, scrappy = Feed(meta), Feed(meta)
        for i in range(40):
            calm.pass_(i * 4, H)
            scrappy.pass_(i * 4, H if i % 2 else A)
            scrappy.push(i * 4 + 1, EventType.POSSESSION_CHANGE, team=A if i % 2 else H)
            if i % 5 == 0:
                scrappy.push(i * 4 + 2, EventType.FOUL, team=A, player="A4", start=(50.0, 30.0))
        assert calm.engine.control_chaos() == 0.0
        assert scrappy.engine.control_chaos() > 0.8


class TestPublishing:
    def test_snapshots_on_interval_and_key_events(self, meta: MatchMeta) -> None:
        feed = Feed(meta, snapshot_every_s=60)
        for t in range(0, 300, 10):
            feed.pass_(t, H)
        assert [s.t for s in feed.snapshots] == [0, 60, 120, 180, 240]
        feed.push(305, EventType.SHOT, team=H, player="H9", start=(90.0, 34.0), outcome=Outcome.OFF_TARGET)
        assert feed.snapshots[-1].t == 305

    def test_rejects_out_of_order_and_foreign_events(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        feed.pass_(100, H)
        with pytest.raises(ValueError, match="out-of-order"):
            feed.pass_(50, H)
        foreign = MatchEvent(
            id=99, match_id="OTHER", t=200, minute=3, phase=Phase.FIRST_HALF, type=EventType.PHASE_CHANGE
        )
        with pytest.raises(ValueError, match="match OTHER"):
            feed.engine.apply(foreign)


def run(meta: MatchMeta, scenario: Scenario = ORGANIC, seed: int = 1) -> tuple[list[MatchEvent], list[StatSnapshot]]:
    events = [m for m in simulate(meta, scenario, seed=seed) if isinstance(m, MatchEvent)]
    return events, replay(meta, events)


@pytest.fixture(scope="module")
def demo() -> tuple[list[MatchEvent], list[StatSnapshot]]:
    return run(build_match_meta("M001", seed=7), DEMO, seed=7)


class TestOnSimulatedMatches:
    def test_totals_match_the_event_stream(self, demo: tuple[list[MatchEvent], list[StatSnapshot]]) -> None:
        events, snaps = demo
        final = snaps[-1]
        assert final.home.shots + final.away.shots == sum(e.type is EventType.SHOT for e in events)
        assert (final.score.home, final.score.away) == (2, 1)
        assert final.phase is Phase.FULL_TIME
        assert final.home.possession_pct + final.away.possession_pct == pytest.approx(100, abs=0.2)

    def test_replay_is_deterministic(self, demo: tuple[list[MatchEvent], list[StatSnapshot]]) -> None:
        events, snaps = demo
        again = replay(build_match_meta("M001", seed=7), events)
        assert [s.model_dump_json() for s in again] == [s.model_dump_json() for s in snaps]

    def test_scripted_pressing_spell_shows(self, demo: tuple[list[MatchEvent], list[StatSnapshot]]) -> None:
        _, snaps = demo
        spell = [s.home.pressure_index for s in snaps if s.phase is Phase.FIRST_HALF and 28 <= s.minute <= 35]
        assert max(spell) >= 0.5

    def test_scripted_chaos_window_shows(self, demo: tuple[list[MatchEvent], list[StatSnapshot]]) -> None:
        _, snaps = demo
        second = [s for s in snaps if s.phase is Phase.SECOND_HALF]
        window = [s.control_chaos for s in second if 79 <= s.minute <= 84]
        before = [s.control_chaos for s in second if 70 <= s.minute <= 76]
        assert max(window) >= 0.7 > max(before)

    def test_organic_baselines_are_calm(self) -> None:
        chaos: list[float] = []
        pressure: list[float] = []
        for seed in range(1, 5):
            _, snaps = run(build_match_meta(f"M{seed}", seed=seed), ORGANIC, seed)
            chaos += [s.control_chaos for s in snaps[5:]]
            pressure += [s.home.pressure_index for s in snaps[5:]]
        assert sorted(chaos)[len(chaos) // 2] < 0.3
        assert sorted(pressure)[len(pressure) // 2] < 0.4


class TestReviewRegressions:
    def test_redelivered_events_are_ignored(self, demo: tuple[list[MatchEvent], list[StatSnapshot]]) -> None:
        events, snaps = demo
        engine = StatsEngine(build_match_meta("M001", seed=7))
        for e in events:  # at-least-once delivery: every 10th event arrives twice
            engine.apply(e)
            if e.id % 10 == 0:
                assert engine.apply(e) is None
        assert engine.snapshot().model_dump() == snaps[-1].model_dump()

    def test_possession_clock_stops_after_a_goal(self, meta: MatchMeta) -> None:
        feed = Feed(meta)
        feed.pass_(0, H)
        shot = feed.push(20, EventType.SHOT, team=H, player="H9", start=(94.0, 34.0), outcome=Outcome.GOAL)
        feed.push(21, EventType.GOAL, team=H, player="H9", related_event_id=shot.id)
        feed.push(80, EventType.POSSESSION_CHANGE, team=A, start=(52.5, 34.0))  # kick-off after 59 s of celebration
        feed.pass_(81, A)
        feed.push(101, EventType.POSSESSION_CHANGE, team=H)
        snap = feed.engine.snapshot()
        # home: 0-21 s in play; away: 80-101 s. The celebration counts for nobody.
        assert snap.home.possession_pct == 50.0

    def test_cli_writes_snapshots(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        meta = build_match_meta("M001", seed=7)
        source = tmp_path / "M001.jsonl"
        source.write_text("\n".join(m.model_dump_json() for m in simulate(meta, DEMO, seed=7)), encoding="utf-8")
        cli_main([str(source)])
        out = tmp_path / "M001.stats.jsonl"
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines and isinstance(parse_wire(lines[-1]), StatSnapshot)
        assert "FT 2-1" in capsys.readouterr().out

    def test_cli_rejects_a_match_without_events(self, tmp_path: Path) -> None:
        source = tmp_path / "empty.jsonl"
        source.write_text(build_match_meta("M001", seed=7).model_dump_json(), encoding="utf-8")
        with pytest.raises(SystemExit):
            cli_main([str(source)])

"""Scenarios steer a simulated match towards a storyline without scripting every event.

Beats are forced sequences (a goal, a saved big chance, a record sprint) injected at
a given match time. Windows bias behaviour over a period (a pressing spell, a chaotic
phase). Everything between beats is played out by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pitchmind_contracts import TeamSide


class BeatKind(StrEnum):
    GOAL = "goal"
    SAVED_CHANCE = "saved_chance"
    MISSED_CHANCE = "missed_chance"
    SPRINT = "sprint"


@dataclass(frozen=True)
class Beat:
    t: float
    kind: BeatKind
    team: TeamSide
    player: str
    assist: str | None = None
    shot_from: tuple[float, float] = (93.0, 36.0)
    pass_from: tuple[float, float] = (68.0, 34.0)
    under_pressure: bool = False
    speed_kmh: float | None = None


@dataclass(frozen=True)
class Window:
    """Multiplies a team's pressing intensity (or both teams' chaos) between two times."""

    start: float
    end: float
    team: TeamSide | None  # None = both teams
    press: float = 1.0
    chaos: float = 0.0  # 0..1, raises turnovers and tempo


@dataclass(frozen=True)
class ScheduledSub:
    t: float
    team: TeamSide
    off: str
    on: str


@dataclass(frozen=True)
class Scenario:
    name: str
    first_half_s: float | None = None  # None = drawn from the seed (45 min + 1-4 min stoppage)
    second_half_s: float | None = None  # None = drawn from the seed (45 min + 2-6 min stoppage)
    beats: tuple[Beat, ...] = ()
    windows: tuple[Window, ...] = ()
    subs: tuple[ScheduledSub, ...] = ()
    lock_score: bool = False  # organic shots never score; only beats change the score


# Demo halves: 45+2:30 and 90+4, matching tools/mock_stream.py.
DEMO_FIRST_HALF_S = 2850.0
DEMO_SECOND_HALF_S = 49 * 60.0


def _t1(minute: int, sec: int = 0) -> float:
    return float(minute * 60 + sec)


def _t2(minute: int, sec: int = 0) -> float:
    return DEMO_FIRST_HALF_S + (minute - 45) * 60 + sec


H, A = TeamSide.HOME, TeamSide.AWAY

# The demo storyline, aligned with tools/mock_stream.py so the UI and the real
# pipeline tell the same story.
DEMO = Scenario(
    name="demo-comeback",
    first_half_s=DEMO_FIRST_HALF_S,
    second_half_s=DEMO_SECOND_HALF_S,
    lock_score=True,
    beats=(
        # Shot positions give realistic xG: ~0.34, ~0.41, ~0.30, ~0.23 (pressured) and a 0.08 long-range winner.
        Beat(_t1(9, 10), BeatKind.GOAL, A, "A9", assist="A10", pass_from=(62, 30), shot_from=(97, 36)),
        Beat(
            _t1(33, 4),
            BeatKind.SAVED_CHANCE,
            H,
            "H10",
            assist="H7",
            pass_from=(80, 58),
            shot_from=(98, 35),
        ),
        Beat(_t2(58, 20), BeatKind.MISSED_CHANCE, H, "H9", assist="H11", pass_from=(80, 50), shot_from=(96, 35)),
        Beat(
            _t2(61, 8),
            BeatKind.GOAL,
            H,
            "H9",
            assist="H10",
            pass_from=(68, 36),
            shot_from=(96, 33),
            under_pressure=True,
        ),
        Beat(_t2(72, 20), BeatKind.SPRINT, H, "H11", speed_kmh=35.2),
        Beat(_t2(86, 4), BeatKind.GOAL, H, "H10", pass_from=(70, 30), shot_from=(86.6, 37)),
    ),
    windows=(
        Window(_t1(10), _t1(20), A, press=1.5),
        Window(_t1(23), _t1(34), H, press=2.2),
        Window(_t2(46), _t2(51), A, press=1.5),
        Window(_t2(51), _t2(62), H, press=1.9),
        Window(_t2(77), _t2(82), None, press=1.6, chaos=0.8),
    ),
    subs=(
        ScheduledSub(_t2(64), H, "H8", "H14"),
        ScheduledSub(_t2(70), A, "A4", "A14"),
        ScheduledSub(_t2(75), A, "A11", "A18"),
        ScheduledSub(_t2(79), H, "H7", "H17"),
    ),
)

ORGANIC = Scenario(name="organic")

SCENARIOS: dict[str, Scenario] = {s.name: s for s in (DEMO, ORGANIC)}

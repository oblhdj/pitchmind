"""Scripted content for the mock demo match: the timeline, events, moments, texts and keyframes.

Edit the storyline here; tools/mock_stream.py turns it into wire messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pitchmind_contracts import (
    EventType,
    InsightKind,
    Language,
    MetricName,
    MomentKind,
    Outcome,
    OverlaySlot,
    Persona,
    Phase,
    Segment,
    TeamSide,
)

MATCH_ID = "M001"
HT_T = 2850.0  # first half ends at 45+2:30
FT_T = HT_T + 49 * 60  # second half ends at 90+4
HOME, AWAY = TeamSide.HOME, TeamSide.AWAY


SEGMENTS: dict[str, Segment] = {
    "analyst_en": Segment(persona=Persona.ANALYST, language=Language.EN),
    "casual_ar": Segment(persona=Persona.CASUAL, language=Language.AR, club=HOME),
    "beginner_fr": Segment(persona=Persona.BEGINNER, language=Language.FR),
    "player_h10": Segment(persona=Persona.CASUAL, language=Language.EN, player="H10"),
}


def t1(minute: int, sec: int = 0) -> float:
    return float(minute * 60 + sec)


def t2(minute: int, sec: int = 0) -> float:
    return HT_T + (minute - 45) * 60 + sec


def minute_of(t: float) -> int:
    return int(t // 60) if t < HT_T else 45 + int((t - HT_T) // 60)


def phase_of(t: float) -> Phase:
    if t >= FT_T:
        return Phase.FULL_TIME
    return Phase.FIRST_HALF if t < HT_T else Phase.SECOND_HALF


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------


@dataclass
class Ev:
    key: str
    t: float
    type: EventType
    team: TeamSide | None = None
    player: str | None = None
    receiver: str | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    outcome: Outcome | None = None
    under_pressure: bool = False
    ball_speed: float | None = None
    player_speed: float | None = None
    distance: float | None = None
    related: str | None = None
    phase: Phase | None = None
    xg: float = 0.0  # not on the wire; feeds player stats


@dataclass
class Text:
    headline: str
    body: str
    claims: list[str]


@dataclass
class Scripted:
    n: int
    t: float
    kind: MomentKind
    team: TeamSide | None
    players: list[str]
    importance: float
    metrics: dict[str, float]
    fallback: str
    claims: list[tuple[list[str], list[str]]]  # (evidence event keys, metric keys) per claim
    texts: dict[str, Text]
    insight_kind: InsightKind = InsightKind.EXPLANATION
    slot: OverlaySlot = OverlaySlot.LOWER_THIRD
    priority: int = 60
    duration: float = 7.0
    metric: tuple[MetricName, str, str | None] | None = None  # (name, metrics key, unit)
    template_segments: set[str] = field(default_factory=set)


EVENTS: list[Ev] = [
    Ev("kickoff", 0.0, EventType.PHASE_CHANGE, phase=Phase.FIRST_HALF),
    # 9' Harbour goal
    Ev(
        "m1_pass",
        t1(9, 6),
        EventType.PASS,
        AWAY,
        "A10",
        "A9",
        (62, 30),
        (89, 33),
        Outcome.SUCCESS,
        ball_speed=61.0,
        distance=27.2,
    ),
    Ev(
        "m1_shot",
        t1(9, 10),
        EventType.SHOT,
        AWAY,
        "A9",
        start=(91, 31),
        end=(105, 35),
        outcome=Outcome.GOAL,
        ball_speed=104.2,
        xg=0.38,
    ),
    Ev("m1_goal", t1(9, 12), EventType.GOAL, AWAY, "A9", related="m1_shot"),
    # 27' North City press
    Ev("m2_p1", t1(23, 40), EventType.PRESSURE, HOME, "H9", start=(88, 40)),
    Ev("m2_p2", t1(24, 40), EventType.PRESSURE, HOME, "H8", start=(80, 22)),
    Ev("m2_t1", t1(25, 10), EventType.TACKLE, HOME, "H8", start=(78, 25), outcome=Outcome.SUCCESS),
    Ev("m2_t2", t1(25, 40), EventType.TACKLE, HOME, "H6", start=(70, 40), outcome=Outcome.SUCCESS),
    Ev("m2_p3", t1(26, 10), EventType.PRESSURE, HOME, "H6", start=(74, 50)),
    Ev("m2_i1", t1(26, 40), EventType.INTERCEPTION, HOME, "H7", start=(85, 60)),
    Ev("m2_i2", t1(26, 55), EventType.INTERCEPTION, HOME, "H10", start=(82, 36)),
    Ev("m2_p4", t1(27, 30), EventType.PRESSURE, HOME, "H9", start=(90, 30)),
    # 33' Haddad chance
    Ev("m3_pass", t1(33, 1), EventType.PASS, HOME, "H7", "H10", (80, 58), (92, 40), Outcome.SUCCESS, ball_speed=55.0),
    Ev(
        "m3_shot",
        t1(33, 4),
        EventType.SHOT,
        HOME,
        "H10",
        start=(93, 38),
        end=(105, 36),
        outcome=Outcome.ON_TARGET,
        under_pressure=True,
        ball_speed=112.3,
        xg=0.41,
    ),
    Ev("m3_save", t1(33, 5), EventType.SAVE, AWAY, "A1", start=(0.5, 33), related="m3_shot"),
    # Half-time
    Ev("ht", HT_T, EventType.PHASE_CHANGE, phase=Phase.HALF_TIME),
    Ev("kickoff2", HT_T, EventType.PHASE_CHANGE, phase=Phase.SECOND_HALF),
    # 52'-58' North City shots
    Ev(
        "m5_s1",
        t2(52, 10),
        EventType.SHOT,
        HOME,
        "H9",
        start=(90, 28),
        outcome=Outcome.OFF_TARGET,
        ball_speed=88.0,
        xg=0.06,
    ),
    Ev(
        "m5_s2",
        t2(55, 0),
        EventType.SHOT,
        HOME,
        "H11",
        start=(89, 50),
        outcome=Outcome.BLOCKED,
        ball_speed=79.5,
        xg=0.08,
    ),
    Ev(
        "m5_s3",
        t2(57, 5),
        EventType.SHOT,
        HOME,
        "H7",
        start=(84, 20),
        outcome=Outcome.OFF_TARGET,
        ball_speed=91.2,
        xg=0.05,
    ),
    Ev(
        "m5_s4",
        t2(58, 20),
        EventType.SHOT,
        HOME,
        "H9",
        start=(94, 36),
        outcome=Outcome.OFF_TARGET,
        ball_speed=95.0,
        xg=0.11,
    ),
    # 61' equaliser
    Ev(
        "m6_pass",
        t2(61, 5),
        EventType.PASS,
        HOME,
        "H10",
        "H9",
        (68, 36),
        (95, 33),
        Outcome.SUCCESS,
        under_pressure=True,
        ball_speed=66.0,
        distance=27.5,
    ),
    Ev(
        "m6_shot",
        t2(61, 8),
        EventType.SHOT,
        HOME,
        "H9",
        start=(95, 33),
        end=(105, 32),
        outcome=Outcome.GOAL,
        ball_speed=98.7,
        xg=0.29,
    ),
    Ev("m6_goal", t2(61, 10), EventType.GOAL, HOME, "H9", related="m6_shot"),
    # Substitutions and a card
    Ev("sub_h8", t2(64, 0), EventType.SUBSTITUTION, HOME, "H8", "H14"),
    Ev("sub_a4", t2(70, 0), EventType.SUBSTITUTION, AWAY, "A4", "A14"),
    # 72' sprint
    Ev(
        "m7_sprint",
        t2(72, 20),
        EventType.SPRINT,
        HOME,
        "H11",
        start=(40, 60),
        end=(88, 62),
        player_speed=35.2,
        distance=48.0,
    ),
    Ev("foul_a5", t2(77, 25), EventType.FOUL, AWAY, "A5", start=(30, 40)),
    Ev("card_a5", t2(77, 30), EventType.CARD, AWAY, "A5", outcome=Outcome.YELLOW, related="foul_a5"),
    # 80' chaos
    Ev("m8_pc1", t2(77, 25), EventType.POSSESSION_CHANGE, HOME),
    Ev("m8_pc2", t2(78, 25), EventType.POSSESSION_CHANGE, AWAY),
    Ev("m8_pc3", t2(79, 25), EventType.POSSESSION_CHANGE, HOME),
    Ev("m8_pc4", t2(80, 25), EventType.POSSESSION_CHANGE, AWAY),
    # 86' winner
    Ev(
        "m9_carry",
        t2(85, 59),
        EventType.CARRY,
        HOME,
        "H10",
        start=(70, 30),
        end=(86, 36),
        player_speed=27.0,
        distance=17.2,
    ),
    Ev(
        "m9_shot",
        t2(86, 4),
        EventType.SHOT,
        HOME,
        "H10",
        start=(86.6, 37),
        end=(105, 30),
        outcome=Outcome.GOAL,
        ball_speed=117.4,
        xg=0.12,
    ),
    Ev("m9_goal", t2(86, 5), EventType.GOAL, HOME, "H10", related="m9_shot"),
    Ev("ft", FT_T, EventType.PHASE_CHANGE, phase=Phase.FULL_TIME),
]

PRESSURE_EVENTS = ["m2_p1", "m2_p2", "m2_p3", "m2_p4"]
RECOVERIES = ["m2_t1", "m2_t2", "m2_i1", "m2_i2"]
SPELL_SHOTS = ["m5_s1", "m5_s2", "m5_s3", "m5_s4"]
TURNOVERS = ["m8_pc1", "m8_pc2", "m8_pc3", "m8_pc4"]


@dataclass(frozen=True)
class SpeedAlert:
    """A stat alert rendered straight from a threshold, with no agent involved."""

    n: int
    t: float
    event: str
    player: str
    speed: float
    titles: dict[str, str]
    bodies: dict[str, str]


SPEED_ALERT = SpeedAlert(
    n=7,
    t=t2(72, 20),
    event="m7_sprint",
    player="H11",
    speed=35.2,
    titles={"analyst_en": "Top speed", "casual_ar": "أعلى سرعة", "beginner_fr": "Vitesse de pointe"},
    bodies={
        "analyst_en": "Kenji Arai — 35.2 km/h",
        "casual_ar": "Kenji Arai — 35.2 كم/س",
        "beginner_fr": "Kenji Arai — 35,2 km/h",
    },
)

SUBS = {
    "H8": ("off", t2(64, 0)),
    "H14": ("on", t2(64, 0)),
    "A4": ("off", t2(70, 0)),
    "A14": ("on", t2(70, 0)),
}

# Keyframes (t, value), linearly interpolated.
KEY: dict[str, list[tuple[float, float]]] = {
    "momentum": [
        (0, 0),
        (t1(9, 10), -0.1),
        (t1(10), -0.45),
        (t1(22), -0.1),
        (t1(27, 40), 0.5),
        (t1(33, 5), 0.55),
        (HT_T, 0.2),
        (t2(50), -0.35),
        (t2(58, 30), 0.52),
        (t2(61, 10), 0.6),
        (t2(75), 0.3),
        (t2(80, 45), 0.1),
        (t2(86, 5), 0.45),
        (FT_T, 0.3),
    ],
    "control_chaos": [(0, 0.3), (t2(79), 0.31), (t2(80, 45), 0.78), (t2(86, 5), 0.65), (FT_T, 0.5)],
    "rhythm": [(0, 16), (t2(79), 14), (t2(80, 45), 23), (FT_T, 18)],
    "home_pi": [
        (0, 0.4),
        (t1(22), 0.38),
        (t1(27, 40), 0.74),
        (t1(33, 5), 0.72),
        (HT_T, 0.58),
        (t2(50), 0.45),
        (t2(58, 30), 0.66),
        (t2(61, 10), 0.7),
        (t2(75), 0.6),
        (FT_T, 0.55),
    ],
    "away_pi": [
        (0, 0.4),
        (t1(10), 0.5),
        (t1(27, 40), 0.3),
        (HT_T, 0.38),
        (t2(50), 0.5),
        (t2(58, 30), 0.35),
        (t2(80, 45), 0.5),
        (FT_T, 0.45),
    ],
    "home_poss": [(0, 50), (t1(10), 46), (t1(27, 40), 51), (HT_T, 52), (t2(61), 54), (FT_T, 55)],
    "home_xg": [
        (0, 0),
        (t1(33, 4), 0.25),
        (t1(33, 6), 0.66),
        (HT_T, 0.71),
        (t2(58, 25), 1.01),
        (t2(61, 7), 1.04),
        (t2(61, 9), 1.33),
        (t2(86, 3), 1.70),
        (t2(86, 5), 1.82),
        (FT_T, 1.86),
    ],
    "away_xg": [(0, 0), (t1(9, 9), 0.02), (t1(9, 11), 0.40), (HT_T, 0.52), (FT_T, 0.97)],
    "home_shots": [
        (0, 0),
        (t1(33, 3), 4),
        (t1(33, 5), 5),
        (HT_T, 6),
        (t2(52, 9), 6),
        (t2(52, 11), 7),
        (t2(55, 1), 8),
        (t2(57, 6), 9),
        (t2(58, 21), 10),
        (t2(61, 9), 11),
        (t2(86, 3), 13),
        (t2(86, 5), 14),
        (FT_T, 15),
    ],
    "away_shots": [(0, 0), (t1(9, 9), 1), (t1(9, 11), 2), (HT_T, 4), (FT_T, 8)],
    "home_sot": [(0, 0), (t1(33, 5), 2), (HT_T, 2), (t2(61, 9), 4), (t2(86, 5), 6), (FT_T, 6)],
    "away_sot": [(0, 0), (t1(9, 11), 1), (HT_T, 2), (FT_T, 3)],
}

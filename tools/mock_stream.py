"""Scripted demo match -> mock wire stream for frontend development.

Storyline (North City FC vs Harbour United):
    9'  Harbour score first (Halvorsen)
    27' North City pressing surge
    33' Haddad big chance, saved by Sandvik
    HT  recap, 0-1
    58' momentum swings to North City
    61' Kaya equalises from Haddad's through ball
    72' Arai hits 35.2 km/h (stat alert, no LLM)
    80' match turns chaotic
    86' Haddad's 0.12 xG winner, 2-1
    FT  recap

Every message is a validated contract model. Text is written to obey the agent
rules: every number in a claim comes from the moment's metrics, every claim cites
event ids. The analyst insight at 80' is a template fallback, so the UI can show
the failure-recovery path.

Usage (repo root):
    python tools/mock_stream.py            -> data/mock/stream.jsonl + match_meta.json
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from pitchmind_contracts import (
    AgentName,
    Claim,
    EventType,
    Insight,
    InsightKind,
    Language,
    MatchEvent,
    MatchMeta,
    MetricName,
    Moment,
    MomentKind,
    Outcome,
    Overlay,
    OverlayMetric,
    OverlaySlot,
    Persona,
    Phase,
    PlayerStats,
    Position,
    Score,
    Segment,
    StatSnapshot,
    TeamSide,
    TeamStats,
    parse_wire,
)
from pitchmind_simulator.league import build_match_meta

MATCH_ID = "M001"
HT_T = 2850.0  # first half ends at 45+2:30
FT_T = HT_T + 49 * 60  # second half ends at 90+4
HOME, AWAY = TeamSide.HOME, TeamSide.AWAY

Wire = MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay

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

MOMENTS: list[Scripted] = [
    Scripted(
        1,
        t1(9, 12),
        MomentKind.GOAL,
        AWAY,
        ["A9", "A10"],
        1.0,
        {"xg": 0.38, "shot_speed_kmh": 104.2, "pass_difficulty": 0.71, "home_goals": 0, "away_goals": 1},
        "Goal for Harbour United: Halvorsen scores after 9 minutes.",
        [(["m1_pass"], ["pass_difficulty"]), (["m1_shot", "m1_goal"], ["xg", "shot_speed_kmh"])],
        {
            "analyst_en": Text(
                "Harbour strike first through Halvorsen",
                "Albers splits the North City back line with a pass rated 0.71 for difficulty, and "
                "Halvorsen finishes at 104.2 km/h. The chance was worth 0.38 xG.",
                [
                    "Albers' pass had a difficulty rating of 0.71.",
                    "Halvorsen's shot was a 0.38 xG chance, struck at 104.2 km/h.",
                ],
            ),
            "casual_ar": Text(
                "هدف مبكر لهاربور يونايتد",
                "بداية صعبة لنورث سيتي: تمريرة ذكية من Albers وضعت Halvorsen أمام المرمى، "
                "فسدد بقوة 104.2 كم/س. ما زالت المباراة في دقائقها الأولى.",
                ["تمريرة Albers كانت صعبة التنفيذ (0.71).", "تسديدة Halvorsen بلغت سرعتها 104.2 كم/س."],
            ),
            "beginner_fr": Text(
                "But de Harbour United !",
                "Halvorsen marque après 9 minutes. Le « xG » (buts attendus) de son tir était de 0,38 : "
                "une occasion de ce type finit au fond environ 4 fois sur 10.",
                ["La passe d'Albers était difficile (0,71 sur 1).", "Le tir de Halvorsen valait 0,38 xG."],
            ),
        },
        insight_kind=InsightKind.COMMENTARY,
        priority=90,
        duration=8.0,
        metric=(MetricName.XG, "xg", None),
    ),
    Scripted(
        2,
        t1(27, 40),
        MomentKind.PRESSURE_SURGE,
        HOME,
        ["H9", "H8", "H6"],
        0.7,
        {
            "pressure_index_before": 0.38,
            "pressure_index_after": 0.74,
            "window_min": 5,
            "recoveries_opp_half": 4,
            "possession_pct_window": 68,
        },
        "North City's pressure index rose from 0.38 to 0.74 in 5 minutes.",
        [
            (PRESSURE_EVENTS, ["pressure_index_before", "pressure_index_after", "window_min"]),
            (RECOVERIES, ["recoveries_opp_half"]),
            (PRESSURE_EVENTS, ["possession_pct_window"]),
        ],
        {
            "analyst_en": Text(
                "North City's press takes hold",
                "North City's pressure index has jumped from 0.38 to 0.74 in 5 minutes, with 4 ball "
                "recoveries in Harbour's half and 68% of the possession in that window.",
                [
                    "Pressure index rose from 0.38 to 0.74 over 5 minutes.",
                    "4 ball recoveries in Harbour's half.",
                    "68% possession during the spell.",
                ],
            ),
            "casual_ar": Text(
                "نورث سيتي يضغط بقوة!",
                "فريقك استعاد الكرة 4 مرات في نصف ملعب الخصم خلال 5 دقائق، واستحوذ على 68% من الكرة. "
                "الضغط يتصاعد بوضوح.",
                [
                    "مؤشر الضغط ارتفع من 0.38 إلى 0.74.",
                    "4 استعادات للكرة في نصف ملعب هاربور.",
                    "استحواذ بنسبة 68% خلال هذه الفترة.",
                ],
            ),
            "beginner_fr": Text(
                "North City met la pression",
                "« Presser », c'est attaquer le porteur du ballon pour le récupérer vite. North City l'a "
                "fait si bien qu'il a récupéré le ballon 4 fois dans le camp adverse en 5 minutes.",
                [
                    "L'indice de pression est passé de 0,38 à 0,74.",
                    "4 ballons récupérés dans le camp adverse.",
                    "68 % de possession pendant cette période.",
                ],
            ),
        },
        metric=(MetricName.PRESSURE_INDEX, "pressure_index_after", None),
    ),
    Scripted(
        3,
        t1(33, 5),
        MomentKind.BIG_CHANCE,
        HOME,
        ["H10", "A1", "H7"],
        0.8,
        {"xg": 0.41, "shot_speed_kmh": 112.3},
        "Big chance for North City: Haddad's shot is saved by Sandvik.",
        [(["m3_pass", "m3_shot"], ["xg", "shot_speed_kmh"]), (["m3_save"], [])],
        {
            "analyst_en": Text(
                "Haddad denied by Sandvik",
                "Whitcombe finds Haddad between the lines; his 112.3 km/h strike was a 0.41 xG chance, "
                "kept out by Sandvik.",
                ["Haddad's shot: 0.41 xG at 112.3 km/h.", "Sandvik made the save."],
            ),
            "casual_ar": Text(
                "يا لها من فرصة!",
                "Haddad سدد كرة قوية بسرعة 112.3 كم/س، لكن الحارس Sandvik أنقذها ببراعة. "
                "نورث سيتي كان قريباً جداً من التعادل.",
                ["تسديدة Haddad: سرعة 112.3 كم/س وفرصة تسجيل 0.41.", "الحارس Sandvik تصدى للكرة."],
            ),
            "beginner_fr": Text(
                "Énorme arrêt de Sandvik",
                "Haddad frappe à 112,3 km/h. Cette occasion valait 0,41 xG, soit environ 4 chances sur 10 "
                "de marquer, mais le gardien Sandvik a réussi l'arrêt.",
                ["Le tir de Haddad valait 0,41 xG, à 112,3 km/h.", "Sandvik a arrêté le tir."],
            ),
            "player_h10": Text(
                "Big moment for Haddad",
                "Rayan Haddad forced a big save with a 112.3 km/h shot, a 0.41 xG chance.",
                ["Haddad's shot: 0.41 xG at 112.3 km/h.", "Sandvik made the save."],
            ),
        },
        priority=75,
        metric=(MetricName.XG, "xg", None),
    ),
    Scripted(
        4,
        HT_T,
        MomentKind.PHASE,
        None,
        ["A9", "H10"],
        0.9,
        {
            "home_goals": 0,
            "away_goals": 1,
            "home_xg": 0.71,
            "away_xg": 0.52,
            "home_shots": 6,
            "away_shots": 4,
            "home_pressure_index_peak": 0.74,
        },
        "Half-time: North City 0-1 Harbour United.",
        [
            (["m1_goal"], ["home_goals", "away_goals"]),
            (["m1_shot", "m3_shot"], ["home_xg", "away_xg"]),
            (["ht"], ["home_shots", "away_shots"]),
            (["m2_p4"], ["home_pressure_index_peak"]),
        ],
        {
            "analyst_en": Text(
                "Half-time: Harbour lead, North City lead the xG",
                "Harbour lead 1-0 through Halvorsen's 9th-minute goal, but North City lead the xG 0.71 to "
                "0.52 and the shot count 6 to 4. Their press, peaking at a 0.74 pressure index, produced "
                "Haddad's chance, saved by Sandvik.",
                [
                    "Score 0-1 after Halvorsen's goal.",
                    "xG: North City 0.71, Harbour 0.52.",
                    "Shots: 6 to 4 for North City.",
                    "Pressure index peaked at 0.74.",
                ],
            ),
            "casual_ar": Text(
                "نهاية الشوط الأول: تأخر رغم الأفضلية",
                "نورث سيتي متأخر 0-1، لكنه كان الأخطر: 6 تسديدات مقابل 4، وأهداف متوقعة 0.71 مقابل 0.52. "
                "الضغط العالي صنع أفضل فرصة لـ Haddad، وأنقذها الحارس.",
                [
                    "النتيجة 0-1 بعد هدف Halvorsen.",
                    "الأهداف المتوقعة: 0.71 مقابل 0.52.",
                    "التسديدات: 6 مقابل 4 لنورث سيتي.",
                    "مؤشر الضغط وصل إلى 0.74.",
                ],
            ),
            "beginner_fr": Text(
                "Mi-temps : 0-1",
                "Harbour United mène grâce au but de Halvorsen. Pourtant, North City a tiré plus souvent "
                "(6 tirs contre 4) et a eu les meilleures occasions selon le xG (0,71 contre 0,52). "
                "Le score ne reflète pas toujours le jeu.",
                [
                    "Score : 0-1 après le but de Halvorsen.",
                    "xG : 0,71 pour North City, 0,52 pour Harbour.",
                    "Tirs : 6 contre 4 pour North City.",
                    "L'indice de pression a atteint 0,74.",
                ],
            ),
        },
        insight_kind=InsightKind.RECAP,
        slot=OverlaySlot.RECAP_CARD,
        priority=80,
        duration=20.0,
    ),
    Scripted(
        5,
        t2(58, 30),
        MomentKind.MOMENTUM_SWING,
        HOME,
        ["H9", "H11", "H7"],
        0.65,
        {"momentum_before": -0.35, "momentum_after": 0.52, "home_shots_last_10min": 4, "window_min": 8},
        "Momentum has swung to North City: 4 shots in the last 10 minutes.",
        [(SPELL_SHOTS, ["home_shots_last_10min"]), (["m5_s1", "m5_s4"], ["momentum_before", "momentum_after"])],
        {
            "analyst_en": Text(
                "Momentum flips to North City",
                "Match momentum has swung from -0.35 to +0.52 in 8 minutes, with North City taking 4 shots "
                "in the last 10 minutes.",
                ["4 North City shots in 10 minutes.", "Momentum moved from -0.35 to 0.52."],
            ),
            "casual_ar": Text(
                "الكفة تميل لفريقك",
                "نورث سيتي سيطر على المباراة من جديد: 4 تسديدات في آخر 10 دقائق، ومؤشر الزخم انقلب لصالحه.",
                ["4 تسديدات لنورث سيتي في 10 دقائق.", "مؤشر الزخم انتقل من -0.35 إلى 0.52."],
            ),
            "beginner_fr": Text(
                "Le vent tourne",
                "Le « momentum » mesure quelle équipe domine en ce moment. Il est passé du côté de "
                "North City, qui a tiré 4 fois en 10 minutes.",
                ["4 tirs de North City en 10 minutes.", "Le momentum est passé de -0,35 à 0,52."],
            ),
        },
        metric=(MetricName.MOMENTUM, "momentum_after", None),
    ),
    Scripted(
        6,
        t2(61, 10),
        MomentKind.GOAL,
        HOME,
        ["H9", "H10"],
        1.0,
        {
            "pass_difficulty": 0.83,
            "pass_distance_m": 27.5,
            "xg": 0.29,
            "shot_speed_kmh": 98.7,
            "home_goals": 1,
            "away_goals": 1,
            "home_shots_prev_10min": 4,
        },
        "Goal for North City: Kaya equalises, assisted by Haddad. 1-1.",
        [
            (["m6_pass"], ["pass_difficulty", "pass_distance_m"]),
            (["m6_shot", "m6_goal"], ["xg", "shot_speed_kmh"]),
            (SPELL_SHOTS, ["home_shots_prev_10min"]),
        ],
        {
            "analyst_en": Text(
                "Kaya levels from Haddad's through ball",
                "Haddad's 27.5 m through ball under pressure carried a 0.83 difficulty rating; Kaya "
                "converted the 0.29 xG chance at 98.7 km/h. The equaliser follows 4 shots in 10 minutes.",
                [
                    "Haddad's pass: 27.5 m, difficulty 0.83.",
                    "Kaya's finish: 0.29 xG at 98.7 km/h.",
                    "4 shots in the previous 10 minutes.",
                ],
            ),
            "casual_ar": Text(
                "تعادل! Kaya يسجل",
                "تمريرة ساحرة من Haddad تحت الضغط، وKaya يسدد في الشباك بسرعة 98.7 كم/س. 1-1 والمباراة تشتعل!",
                [
                    "تمريرة Haddad: 27.5 متر وصعوبة 0.83.",
                    "تسديدة Kaya بسرعة 98.7 كم/س.",
                    "4 تسديدات في الدقائق العشر السابقة.",
                ],
            ),
            "beginner_fr": Text(
                "Égalisation de North City !",
                "Haddad a réussi une passe très difficile (0,83 sur 1) entre les défenseurs, et Kaya a "
                "marqué. Score : 1-1.",
                [
                    "Passe de Haddad : 27,5 m, difficulté 0,83.",
                    "Tir de Kaya : 0,29 xG à 98,7 km/h.",
                    "4 tirs dans les 10 minutes précédentes.",
                ],
            ),
            "player_h10": Text(
                "Haddad's assist",
                "Rayan Haddad delivered the assist: a 27.5 m through ball under pressure with a 0.83 "
                "difficulty rating.",
                [
                    "Haddad's pass: 27.5 m, difficulty 0.83.",
                    "Kaya's finish: 0.29 xG at 98.7 km/h.",
                    "4 shots in the previous 10 minutes.",
                ],
            ),
        },
        insight_kind=InsightKind.COMMENTARY,
        priority=90,
        duration=8.0,
        metric=(MetricName.PASS_DIFFICULTY, "pass_difficulty", None),
    ),
    Scripted(
        8,
        t2(80, 45),
        MomentKind.CONTROL_SHIFT,
        None,
        [],
        0.6,
        {
            "control_chaos_before": 0.31,
            "control_chaos_after": 0.78,
            "rhythm_before_epm": 14,
            "rhythm_after_epm": 23,
            "turnovers_last_5min": 9,
        },
        "The match has turned chaotic: control-chaos index up from 0.31 to 0.78.",
        [
            (TURNOVERS, ["turnovers_last_5min", "control_chaos_before", "control_chaos_after"]),
            (["m8_pc1", "m8_pc4"], ["rhythm_before_epm", "rhythm_after_epm"]),
        ],
        {
            "analyst_en": Text("", "", []),  # template fallback, see template_segments
            "casual_ar": Text(
                "المباراة خرجت عن السيطرة!",
                "9 كرات ضائعة في 5 دقائق فقط والإيقاع أصبح سريعاً جداً. كل شيء ممكن الآن.",
                ["9 كرات ضائعة في 5 دقائق.", "الإيقاع ارتفع من 14 إلى 23 حدثاً في الدقيقة."],
            ),
            "beginner_fr": Text(
                "Le match s'emballe",
                "Les deux équipes perdent souvent le ballon (9 pertes en 5 minutes) et le jeu va beaucoup "
                "plus vite. On dit que le match devient « chaotique ».",
                ["9 pertes de balle en 5 minutes.", "Le rythme est passé de 14 à 23 actions par minute."],
            ),
        },
        metric=(MetricName.CONTROL_CHAOS, "control_chaos_after", None),
        template_segments={"analyst_en"},
    ),
    Scripted(
        9,
        t2(86, 5),
        MomentKind.GOAL,
        HOME,
        ["H10"],
        1.0,
        {"xg": 0.12, "shot_speed_kmh": 117.4, "distance_to_goal_m": 18.6, "home_goals": 2, "away_goals": 1},
        "Goal for North City: Haddad scores. 2-1.",
        [
            (["m9_shot"], ["xg", "shot_speed_kmh", "distance_to_goal_m"]),
            (["m1_goal", "m6_goal", "m9_goal"], ["home_goals", "away_goals"]),
        ],
        {
            "analyst_en": Text(
                "Haddad's 0.12 xG winner",
                "Haddad scores from 18.6 m at 117.4 km/h, a chance worth only 0.12 xG. North City lead 2-1, "
                "completing the comeback from Halvorsen's early goal.",
                ["Haddad's shot: 0.12 xG from 18.6 m at 117.4 km/h.", "North City lead 2-1."],
            ),
            "casual_ar": Text(
                "Haddad يقلب الطاولة! 2-1",
                "صاروخ من Haddad بسرعة 117.4 كم/س من 18.6 متر! فرصة نسبة نجاحها 12% فقط، لكنه حوّلها "
                "إلى هدف. نورث سيتي يتقدم.",
                ["تسديدة Haddad: 117.4 كم/س من 18.6 متر.", "نورث سيتي يتقدم 2-1."],
            ),
            "beginner_fr": Text(
                "But exceptionnel de Haddad !",
                "Haddad marque de loin (18,6 m). Le xG du tir était de 0,12 : un tir comme celui-ci rentre "
                "à peu près 1 fois sur 8. North City mène 2-1.",
                ["Tir de Haddad : 0,12 xG depuis 18,6 m, à 117,4 km/h.", "North City mène 2-1."],
            ),
            "player_h10": Text(
                "Haddad wins it",
                "Rayan Haddad's 117.4 km/h strike from 18.6 m, a 0.12 xG chance, puts North City 2-1 up.",
                ["Haddad's shot: 0.12 xG from 18.6 m at 117.4 km/h.", "North City lead 2-1."],
            ),
        },
        insight_kind=InsightKind.COMMENTARY,
        priority=95,
        duration=9.0,
        metric=(MetricName.XG, "xg", None),
    ),
    Scripted(
        10,
        FT_T,
        MomentKind.PHASE,
        None,
        ["H9", "H10", "A9"],
        1.0,
        {
            "home_goals": 2,
            "away_goals": 1,
            "home_shots": 15,
            "away_shots": 8,
            "home_xg": 1.86,
            "away_xg": 0.97,
            "haddad_goals": 1,
            "haddad_assists": 1,
            "winner_xg": 0.12,
        },
        "Full-time: North City 2-1 Harbour United.",
        [
            (["m1_goal", "m6_goal", "m9_goal"], ["home_goals", "away_goals"]),
            (["ft"], ["home_shots", "away_shots", "home_xg", "away_xg"]),
            (["m6_pass", "m9_shot"], ["haddad_goals", "haddad_assists", "winner_xg"]),
        ],
        {
            "analyst_en": Text(
                "Full-time: North City 2-1 Harbour United",
                "North City came from behind with goals from Kaya (61') and Haddad (86'). They out-shot "
                "Harbour 15 to 8 and won the xG 1.86 to 0.97. Haddad was involved in both goals: 1 assist "
                "and 1 goal from a 0.12 xG chance.",
                ["Final score 2-1.", "Shots 15-8, xG 1.86-0.97.", "Haddad: 1 goal, 1 assist."],
            ),
            "casual_ar": Text(
                "نهاية المباراة: فوز نورث سيتي 2-1",
                "عودة رائعة! بعد التأخر بهدف مبكر، سجل Kaya وHaddad وقلبا النتيجة. فريقك سدد 15 مرة "
                "مقابل 8 وكان الأخطر هجومياً.",
                ["النتيجة النهائية 2-1.", "التسديدات 15 مقابل 8.", "Haddad: هدف وتمريرة حاسمة."],
            ),
            "beginner_fr": Text(
                "Fin du match : North City 2-1",
                "North City était mené 0-1 mais a gagné grâce aux buts de Kaya et Haddad. Il a tiré 15 fois "
                "contre 8 pour Harbour United : une victoire logique selon les statistiques.",
                [
                    "Score final : 2-1.",
                    "Tirs : 15 contre 8, xG : 1,86 contre 0,97.",
                    "Haddad : 1 but, 1 passe décisive.",
                ],
            ),
            "player_h10": Text(
                "Haddad's match: 1 goal, 1 assist",
                "Rayan Haddad decided the game: the assist for Kaya's equaliser and the winner from a 0.12 xG chance.",
                ["Final score 2-1.", "Shots 15-8, xG 1.86-0.97.", "Haddad: 1 goal, 1 assist."],
            ),
        },
        insight_kind=InsightKind.RECAP,
        slot=OverlaySlot.RECAP_CARD,
        priority=85,
        duration=20.0,
    ),
]


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

_TOUCH_RATE = {
    Position.GK: 0.5,
    Position.CB: 1.0,
    Position.FB: 1.1,
    Position.DM: 1.3,
    Position.CM: 1.25,
    Position.AM: 1.2,
    Position.W: 0.9,
    Position.ST: 0.7,
}


def interp(name: str, t: float) -> float:
    pts = KEY[name]
    if t <= pts[0][0]:
        return pts[0][1]
    for (ta, va), (tb, vb) in pairwise(pts):
        if t <= tb:
            return va if tb == ta else va + (vb - va) * (t - ta) / (tb - ta)
    return pts[-1][1]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_events() -> tuple[list[MatchEvent], dict[str, int]]:
    ordered = sorted(enumerate(EVENTS), key=lambda pair: (pair[1].t, pair[0]))
    ids: dict[str, int] = {}
    last = -1
    for _, ev in ordered:
        last = max(last + 1, int(ev.t / 4.2))
        ids[ev.key] = last
    events = [
        MatchEvent(
            id=ids[ev.key],
            match_id=MATCH_ID,
            t=ev.t,
            minute=minute_of(ev.t),
            phase=ev.phase or phase_of(ev.t),
            type=ev.type,
            team=ev.team,
            player=ev.player,
            receiver=ev.receiver,
            start=ev.start,
            end=ev.end,
            outcome=ev.outcome,
            under_pressure=ev.under_pressure,
            ball_speed_kmh=ev.ball_speed,
            player_speed_kmh=ev.player_speed,
            distance_m=ev.distance,
            related_event_id=ids[ev.related] if ev.related else None,
        )
        for _, ev in ordered
    ]
    return events, ids


def _minutes_played(pid: str, starters: set[str], t: float) -> float:
    on, off = (0.0, FT_T) if pid in starters else (FT_T, FT_T)
    if pid in SUBS:
        kind, at = SUBS[pid]
        on, off = (at, FT_T) if kind == "on" else (0.0, at)
    return max(0.0, min(t, off) - on) / 60


def build_snapshot(t: float, meta: MatchMeta, events: list[MatchEvent], ids: dict[str, int]) -> StatSnapshot:
    past = [e for e in events if e.t <= t]
    goals = [e for e in past if e.type is EventType.GOAL]
    score = Score(home=sum(e.team is HOME for e in goals), away=sum(e.team is AWAY for e in goals))
    minutes = t / 60
    home_poss = interp("home_poss", t)

    def team_stats(side: TeamSide) -> TeamStats:
        h = side is HOME
        xg = interp("home_xg" if h else "away_xg", t)
        return TeamStats(
            possession_pct=round(home_poss if h else 100 - home_poss, 1),
            passes=int(minutes * (5.1 if h else 4.3)),
            pass_accuracy_pct=83.4 if h else 79.1,
            avg_pass_difficulty=0.42 if h else 0.39,
            shots=math.floor(interp("home_shots" if h else "away_shots", t)),
            shots_on_target=math.floor(interp("home_sot" if h else "away_sot", t)),
            xg=round(xg, 2),
            xt=round(xg * 0.85, 2),
            tackles_won=int(minutes * (0.19 if h else 0.21)),
            pressure_index=round(interp("home_pi" if h else "away_pi", t), 2),
            distance_covered_m=round(minutes * 1165),
        )

    xg_by_id = {ids[ev.key]: ev.xg for ev in EVENTS if ev.type is EventType.SHOT}
    players: list[PlayerStats] = []
    for team in (meta.home, meta.away):
        starters = set(team.starting_xi)
        for p in team.players:
            mins = _minutes_played(p.id, starters, t)
            if mins <= 0:
                continue
            mine = [e for e in past if e.player == p.id]
            shots = [e for e in mine if e.type is EventType.SHOT]
            sprint_speeds = [e.player_speed_kmh for e in mine if e.player_speed_kmh is not None]
            touches = int(mins * _TOUCH_RATE[p.position])
            base_speed = 24 + p.attributes.pace * 0.1
            players.append(
                PlayerStats(
                    player_id=p.id,
                    team=team.side,
                    touches=touches,
                    passes=int(touches * 0.75),
                    pass_accuracy_pct=round(min(99.0, 70 + p.attributes.passing * 0.2), 1),
                    shots=len(shots),
                    xg=round(sum(xg_by_id.get(e.id, 0.0) for e in shots), 2),
                    tackles_won=int(mins * p.attributes.defending / 100 * 0.05),
                    distance_covered_m=round(
                        mins * (55 if p.position is Position.GK else 100 + p.attributes.stamina * 0.2)
                    ),
                    top_speed_kmh=round(max([base_speed, *sprint_speeds]), 1),
                    sprints=int(mins * p.attributes.pace / 700) + sum(e.type is EventType.SPRINT for e in mine),
                )
            )

    return StatSnapshot(
        match_id=MATCH_ID,
        t=t,
        minute=minute_of(t),
        phase=Phase.HALF_TIME if t == HT_T else phase_of(t),
        last_event_id=max((e.id for e in past), default=0),
        score=score,
        home=team_stats(HOME),
        away=team_stats(AWAY),
        momentum=round(interp("momentum", t), 2),
        control_chaos=round(interp("control_chaos", t), 2),
        rhythm_epm=round(interp("rhythm", t), 1),
        players=players,
    )


def _trace(kind: InsightKind, language: Language) -> list[AgentName]:
    writer = {InsightKind.RECAP: AgentName.RECAP, InsightKind.COMMENTARY: AgentName.NARRATIVE}.get(
        kind, AgentName.EXPLAIN
    )
    trace = [AgentName.ORCHESTRATOR, writer, AgentName.PERSONA]
    if language is not Language.EN:
        trace.append(AgentName.LANGUAGE)
    return [*trace, AgentName.VERIFIER]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_story(ids: dict[str, int]) -> list[tuple[float, int, Wire]]:
    """Moments, insights and overlays as (publish time, order, message)."""
    out: list[tuple[float, int, Wire]] = []
    overlay_n = 0
    for sm in MOMENTS:
        moment = Moment(
            id=f"mom-{MATCH_ID}-{sm.n}",
            match_id=MATCH_ID,
            t=sm.t,
            minute=minute_of(sm.t),
            kind=sm.kind,
            importance=sm.importance,
            team=sm.team,
            players=sm.players,
            evidence=sorted({ids[k] for keys, _ in sm.claims for k in keys}),
            metrics=sm.metrics,
            fallback_text=sm.fallback,
        )
        out.append((sm.t + 1, 3, moment))
        for i, (seg_name, text) in enumerate(sm.texts.items()):
            seg = SEGMENTS[seg_name]
            delay = 6.0 if sm.insight_kind is InsightKind.RECAP else 4.0
            t_ins = sm.t + delay + i * 0.5
            fallback = seg_name in sm.template_segments
            insight = Insight(
                id=f"ins-{MATCH_ID}-{sm.n}-{seg_name}",
                match_id=MATCH_ID,
                moment_id=moment.id,
                t=t_ins,
                kind=sm.insight_kind,
                segment=seg,
                headline="Match update" if fallback else text.headline,
                body=sm.fallback if fallback else text.body,
                claims=[]
                if fallback
                else [
                    Claim(text=ct, evidence=[ids[k] for k in keys], metrics={m: sm.metrics[m] for m in mkeys})
                    for ct, (keys, mkeys) in zip(text.claims, sm.claims, strict=True)
                ],
                verified=True,
                fallback=fallback,
                agent_trace=[AgentName.ORCHESTRATOR, AgentName.EXPLAIN, AgentName.TEMPLATE]
                if fallback
                else _trace(sm.insight_kind, seg.language),
                model=None if fallback else "mock",
                latency_ms=900 if fallback else 2100 + (sm.n * 731 + i * 389) % 4300,
            )
            out.append((t_ins, 4, insight))
            overlay_n += 1
            metric = None
            if sm.metric:
                name, mkey, unit = sm.metric
                metric = OverlayMetric(name=name, value=sm.metrics[mkey], unit=unit)
            out.append(
                (
                    t_ins,
                    5,
                    Overlay(
                        overlay_id=f"ov-{overlay_n}",
                        match_id=MATCH_ID,
                        insight_id=insight.id,
                        show_at=t_ins + 1,
                        duration_s=sm.duration,
                        slot=sm.slot,
                        priority=sm.priority,
                        segment_key=seg.key,
                        language=seg.language,
                        title=_clip(insight.headline, 60),
                        body=_clip(insight.body, 600),
                        team=sm.team,
                        player_id=seg.player,
                        metric=metric,
                        evidence=sorted({ev for c in insight.claims for ev in c.evidence}) or moment.evidence,
                    ),
                )
            )

    alert = SPEED_ALERT
    ev_id = ids[alert.event]
    out.append(
        (
            alert.t + 1,
            3,
            Moment(
                id=f"mom-{MATCH_ID}-{alert.n}",
                match_id=MATCH_ID,
                t=alert.t,
                minute=minute_of(alert.t),
                kind=MomentKind.SPEED_THRESHOLD,
                importance=0.4,
                team=HOME,
                players=[alert.player],
                evidence=[ev_id],
                metrics={"player_speed_kmh": alert.speed, "threshold_kmh": 33.0},
                fallback_text="Kenji Arai reaches 35.2 km/h.",
            ),
        )
    )
    for seg_name, title in alert.titles.items():
        seg = SEGMENTS[seg_name]
        overlay_n += 1
        out.append(
            (
                alert.t + 1.5,
                5,
                Overlay(
                    overlay_id=f"ov-{overlay_n}",
                    match_id=MATCH_ID,
                    show_at=alert.t + 2,
                    duration_s=5,
                    slot=OverlaySlot.PLAYER_TAG,
                    priority=70,
                    segment_key=seg.key,
                    language=seg.language,
                    title=title,
                    body=alert.bodies[seg_name],
                    team=HOME,
                    player_id=alert.player,
                    metric=OverlayMetric(name=MetricName.PLAYER_SPEED_KMH, value=alert.speed, unit="km/h"),
                    evidence=[ev_id],
                ),
            )
        )
    return out


def build_stream() -> tuple[MatchMeta, list[Wire]]:
    meta = build_match_meta(MATCH_ID)
    events, ids = build_events()

    snapshot_times = {float(s) for s in range(0, int(FT_T) + 1, 300)} | {HT_T, FT_T}
    snapshot_times |= {sm.t + 2 for sm in MOMENTS if sm.t not in (HT_T, FT_T)}
    snapshot_times.add(SPEED_ALERT.t + 2)

    timeline: list[tuple[float, int, Wire]] = [(0.0, 0, meta)]
    timeline += [(e.t, 1, e) for e in events]
    timeline += [(t, 2, build_snapshot(t, meta, events, ids)) for t in sorted(snapshot_times)]
    timeline += build_story(ids)
    timeline.sort(key=lambda item: (item[0], item[1]))
    return meta, [msg for _, _, msg in timeline]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("data/mock"))
    args = parser.parse_args()

    meta, messages = build_stream()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "match_meta.json").write_text(meta.model_dump_json(indent=2) + "\n", encoding="utf-8")
    lines = [m.model_dump_json() for m in messages]
    for line in lines:
        parse_wire(line)  # round-trip check
    (args.out / "stream.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for m in messages:
        counts[m.msg] = counts.get(m.msg, 0) + 1
    print(f"wrote {len(lines)} messages to {args.out / 'stream.jsonl'}: {counts}")


if __name__ == "__main__":
    main()

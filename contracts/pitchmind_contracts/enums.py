"""Enumerations shared by every PitchMind service and the frontend."""

from enum import StrEnum


class Phase(StrEnum):
    PRE_MATCH = "pre_match"
    FIRST_HALF = "first_half"
    HALF_TIME = "half_time"
    SECOND_HALF = "second_half"
    FULL_TIME = "full_time"


class TeamSide(StrEnum):
    HOME = "home"
    AWAY = "away"


class Position(StrEnum):
    GK = "GK"
    CB = "CB"
    FB = "FB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    W = "W"
    ST = "ST"


class EventType(StrEnum):
    PASS = "pass"
    CARRY = "carry"
    SHOT = "shot"
    SAVE = "save"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    PRESSURE = "pressure"
    FOUL = "foul"
    CARD = "card"
    SUBSTITUTION = "substitution"
    POSSESSION_CHANGE = "possession_change"
    GOAL = "goal"
    SPRINT = "sprint"
    OFFSIDE = "offside"
    PHASE_CHANGE = "phase_change"


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    ON_TARGET = "on_target"
    OFF_TARGET = "off_target"
    BLOCKED = "blocked"
    GOAL = "goal"
    YELLOW = "yellow"
    RED = "red"


class EventSource(StrEnum):
    SIM = "sim"
    CV = "cv"
    REPLAY = "replay"


class MetricName(StrEnum):
    POSSESSION_PCT = "possession_pct"
    PASSES = "passes"
    PASS_ACCURACY_PCT = "pass_accuracy_pct"
    PASS_DIFFICULTY = "pass_difficulty"
    PASS_DISTANCE_M = "pass_distance_m"
    BALL_SPEED_KMH = "ball_speed_kmh"
    SHOT_SPEED_KMH = "shot_speed_kmh"
    PLAYER_SPEED_KMH = "player_speed_kmh"
    DISTANCE_COVERED_M = "distance_covered_m"
    SPRINTS = "sprints"
    SHOTS = "shots"
    SHOTS_ON_TARGET = "shots_on_target"
    XG = "xg"
    XT = "xt"
    TACKLES_WON = "tackles_won"
    PRESSURE_INDEX = "pressure_index"
    MOMENTUM = "momentum"
    CONTROL_CHAOS = "control_chaos"
    RHYTHM_EPM = "rhythm_epm"


class MomentKind(StrEnum):
    GOAL = "goal"
    BIG_CHANCE = "big_chance"
    SAVE = "save"
    MOMENTUM_SWING = "momentum_swing"
    PRESSURE_SURGE = "pressure_surge"
    CONTROL_SHIFT = "control_shift"
    RHYTHM_CHANGE = "rhythm_change"
    SPEED_THRESHOLD = "speed_threshold"
    DISTANCE_MILESTONE = "distance_milestone"
    MILESTONE = "milestone"
    CARD = "card"
    SUBSTITUTION_IMPACT = "substitution_impact"
    PHASE = "phase"


class Persona(StrEnum):
    ANALYST = "analyst"
    CASUAL = "casual"
    BEGINNER = "beginner"


class Language(StrEnum):
    EN = "en"
    FR = "fr"
    AR = "ar"
    ES = "es"


RTL_LANGUAGES: frozenset[Language] = frozenset({Language.AR})


class InsightKind(StrEnum):
    EXPLANATION = "explanation"
    COMMENTARY = "commentary"
    STAT_ALERT = "stat_alert"
    MILESTONE = "milestone"
    RECAP = "recap"


class OverlaySlot(StrEnum):
    LOWER_THIRD = "lower_third"
    PLAYER_TAG = "player_tag"
    STAT_BUBBLE = "stat_bubble"
    TICKER = "ticker"
    RECAP_CARD = "recap_card"


class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    EXPLAIN = "explain"
    NARRATIVE = "narrative"
    RECAP = "recap"
    PERSONA = "persona"
    LANGUAGE = "language"
    VERIFIER = "verifier"
    TEMPLATE = "template"

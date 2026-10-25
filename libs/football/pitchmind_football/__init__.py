"""Pitch geometry and football models shared by the simulator and the stats engine.

All coordinates are in the acting team's frame: it attacks towards x = 105.
"""

from __future__ import annotations

import math

from pitchmind_contracts import PITCH_LENGTH_M, PITCH_WIDTH_M, Position

GOAL_X = PITCH_LENGTH_M
GOAL_Y = PITCH_WIDTH_M / 2
GOAL_WIDTH_M = 7.32


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_point(x: float, y: float) -> tuple[float, float]:
    return round(clamp(x, 0.0, PITCH_LENGTH_M), 1), round(clamp(y, 0.0, PITCH_WIDTH_M), 1)


def flip(point: tuple[float, float]) -> tuple[float, float]:
    """Convert a point to the other team's frame."""
    return round(PITCH_LENGTH_M - point[0], 1), round(PITCH_WIDTH_M - point[1], 1)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def distance_to_goal(point: tuple[float, float]) -> float:
    return distance(point, (GOAL_X, GOAL_Y))


def goal_angle(point: tuple[float, float]) -> float:
    """Angle (radians) subtended by the goal mouth from ``point``."""
    dx = GOAL_X - point[0]
    dy = abs(point[1] - GOAL_Y)
    half = GOAL_WIDTH_M / 2
    if dx <= 0:
        return 0.0
    angle = math.atan2(GOAL_WIDTH_M * dx, dx * dx + dy * dy - half * half)
    return angle if angle >= 0 else angle + math.pi


def expected_goals(point: tuple[float, float], *, under_pressure: bool = False, header: bool = False) -> float:
    """Distance + angle logistic xG model (Soccermatics-style, hand-calibrated).

    Reference values: 6-yard box ~0.54, penalty spot ~0.23, edge of the box ~0.09.
    """
    logit = -1.0 + 1.5 * goal_angle(point) - 0.11 * distance_to_goal(point)
    if under_pressure:
        logit -= 0.35
    if header:
        logit -= 0.6
    return round(1 / (1 + math.exp(-logit)), 3)


def pass_difficulty(start: tuple[float, float], end: tuple[float, float], *, under_pressure: bool) -> float:
    """0 = trivial, 1 = extremely hard. Length, pressure, progression and target zone."""
    length = distance(start, end)
    progression = max(0.0, end[0] - start[0])
    score = 0.12 + length / 60 + (0.22 if under_pressure else 0.0) + min(progression, 30) / 120
    if end[0] > 88.5 and 13.8 < end[1] < 54.2:  # into the penalty box
        score += 0.12
    return round(clamp(score, 0.0, 1.0), 2)


def expected_threat(point: tuple[float, float]) -> float:
    """Smooth xT-style surface: probability that possession here leads to a goal soon.

    A Gaussian bump centred on the goal mouth, roughly matching published xT grids:
    centre circle ~0.004, edge of the box ~0.12, penalty spot ~0.21, six-yard box ~0.30.
    """
    dx = GOAL_X - point[0]
    dy = point[1] - GOAL_Y
    return round(0.004 + 0.32 * math.exp(-(dx * dx) / (2 * 12.0**2) - (dy * dy) / (2 * 14.0**2)), 4)


def running_rate_m_per_min(position: Position, stamina: int) -> float:
    """Estimated distance covered per minute on the pitch (outfield ~110-120 m/min, keepers 55)."""
    return 55.0 if position is Position.GK else 100.0 + stamina * 0.2


def zone(x: float) -> str:
    if x < 35:
        return "own"
    if x < 70:
        return "mid"
    return "final"

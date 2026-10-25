"""Detection rules (Chain of Responsibility): every rule sees every message and may emit Moments.

Each Moment carries:
* ``evidence``: the event ids that prove it (never empty),
* ``metrics``: the only numbers the agents may cite,
* ``fallback_text``: a deterministic sentence used when the agents fail.

Thresholds were calibrated on simulated matches: organic play rarely crosses them,
the scripted demo spells do.
"""

from __future__ import annotations

from pitchmind_contracts import EventType, MatchEvent, Moment, MomentKind, Outcome, Phase, StatSnapshot, TeamSide
from pitchmind_football import distance_to_goal, expected_goals, pass_difficulty

from .context import MatchContext

H, A = TeamSide.HOME, TeamSide.AWAY
PRESSING = (EventType.PRESSURE, EventType.TACKLE, EventType.INTERCEPTION)
OFF_BALL = {EventType.PRESSURE, EventType.SPRINT, EventType.TACKLE}  # may sit between an assist and the shot

BIG_CHANCE_XG = 0.25
SAVE_WAIT_S = 10.0  # emit a saved big chance without the keeper if the SAVE event never arrives
ASSIST_LOOKBACK_S = 15.0
CARD_FOUL_LOOKBACK_S = 60.0
SPEED_RECORD_KMH = 34.0
SURGE_FROM, SURGE_TO, SURGE_LOOKBACK_S, SURGE_COOLDOWN_S = 0.42, 0.55, 360.0, 480.0
SWING_FROM, SWING_TO, SWING_LOOKBACK_S, SWING_COOLDOWN_S = 0.25, 0.45, 480.0, 480.0
SWING_MIN_ATTACKS = 3  # shots + final-third entries needed to call it a swing
CHAOS_FROM, CHAOS_TO, CHAOS_LOOKBACK_S, CHAOS_COOLDOWN_S = 0.35, 0.65, 360.0, 600.0
MAX_EVIDENCE = 8


def _xg(shot: MatchEvent) -> float:
    return expected_goals(shot.start, under_pressure=shot.under_pressure) if shot.start else 0.0


def _latest(events: list[MatchEvent], n: int = MAX_EVIDENCE) -> list[int]:
    return sorted(e.id for e in events[-n:])


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular}" if n == 1 else f"{n} {plural or singular + 's'}"


class Rule:
    """Base rule: override ``on_event`` and/or ``on_snapshot``; return zero or more moments."""

    def on_event(self, ctx: MatchContext, e: MatchEvent) -> list[Moment]:
        return []

    def on_snapshot(self, ctx: MatchContext, s: StatSnapshot) -> list[Moment]:
        return []


class _Cooldown:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._last: dict[object, float] = {}

    def ready(self, key: object, now: float) -> bool:
        last = self._last.get(key)
        return last is None or now - last >= self.seconds

    def mark(self, key: object, now: float) -> None:
        self._last[key] = now


# --------------------------------------------------------------------------- event rules


class GoalRule(Rule):
    def on_event(self, ctx: MatchContext, e: MatchEvent) -> list[Moment]:
        if e.type is not EventType.GOAL or e.team is None:
            return []
        shot = ctx.event(e.related_event_id)
        assist = self._assist(ctx, shot)
        evidence = [ev.id for ev in (assist, shot) if ev is not None] + [e.id]
        metrics: dict[str, float] = {"home_goals": ctx.score[H], "away_goals": ctx.score[A]}
        if shot is not None and shot.start is not None:
            metrics |= {"xg": round(_xg(shot), 2), "distance_to_goal_m": round(distance_to_goal(shot.start), 1)}
            if shot.ball_speed_kmh is not None:
                metrics["shot_speed_kmh"] = shot.ball_speed_kmh
        if assist is not None and assist.start and assist.end:
            metrics |= {
                "pass_difficulty": pass_difficulty(assist.start, assist.end, under_pressure=assist.under_pressure),
                "pass_distance_m": assist.distance_m or 0.0,
            }
        by = f", assisted by {ctx.name(assist.player)}" if assist else ""
        return [
            ctx.moment(
                kind=MomentKind.GOAL,
                importance=1.0,
                team=e.team,
                players=[p for p in (e.player, assist.player if assist else None) if p],
                evidence=sorted(evidence),
                metrics=metrics,
                fallback_text=f"Goal for {ctx.team_name(e.team)}: {ctx.name(e.player)} scores{by}. {ctx.score_line()}.",
            )
        ]

    @staticmethod
    def _assist(ctx: MatchContext, shot: MatchEvent | None) -> MatchEvent | None:
        """The last completed pass to the scorer in the same possession, skipping off-ball events."""
        if shot is None:
            return None
        for ev in reversed(ctx.events):
            if ev.id >= shot.id:
                continue
            if shot.t - ev.t > ASSIST_LOOKBACK_S or ev.type is EventType.POSSESSION_CHANGE:
                return None
            if ev.type is EventType.PASS:
                ok = ev.outcome is Outcome.SUCCESS and ev.receiver == shot.player and ev.team is shot.team
                return ev if ok else None
            if ev.type in OFF_BALL or (ev.type is EventType.CARRY and ev.player == shot.player):
                continue  # a press, a sprint, or the scorer's own dribble after receiving
            return None
        return None


class BigChanceRule(Rule):
    """A high-xG shot that did not go in. Saved shots wait (briefly) for the SAVE event to name the keeper."""

    def __init__(self) -> None:
        self._pending: dict[int, MatchEvent] = {}

    def on_event(self, ctx: MatchContext, e: MatchEvent) -> list[Moment]:
        moments = self._expire(ctx, e.t)
        if e.type is EventType.SHOT and e.outcome is not Outcome.GOAL and _xg(e) >= BIG_CHANCE_XG:
            if e.outcome is Outcome.ON_TARGET:
                self._pending[e.id] = e
            else:
                moments.append(self._moment(ctx, e, keeper=None))
        elif e.type is EventType.SAVE and e.related_event_id in self._pending:
            moments.append(self._moment(ctx, self._pending.pop(e.related_event_id), keeper=e))
        return moments

    def _expire(self, ctx: MatchContext, now: float) -> list[Moment]:
        stale = [shot for shot in self._pending.values() if now - shot.t > SAVE_WAIT_S]
        for shot in stale:
            del self._pending[shot.id]
        return [self._moment(ctx, shot, keeper=None) for shot in stale]

    @staticmethod
    def _moment(ctx: MatchContext, shot: MatchEvent, keeper: MatchEvent | None) -> Moment:
        xg = round(_xg(shot), 2)
        if shot.outcome is Outcome.ON_TARGET:
            how = f"is saved by {ctx.name(keeper.player)}" if keeper else "is saved"
        else:
            how = "is blocked" if shot.outcome is Outcome.BLOCKED else "goes wide"
        metrics: dict[str, float] = {"xg": xg, "saved": 1.0 if shot.outcome is Outcome.ON_TARGET else 0.0}
        if shot.ball_speed_kmh is not None:
            metrics["shot_speed_kmh"] = shot.ball_speed_kmh
        if shot.start:
            metrics["distance_to_goal_m"] = round(distance_to_goal(shot.start), 1)
        return ctx.moment(
            t=shot.t,
            minute=shot.minute,
            kind=MomentKind.BIG_CHANCE,
            importance=round(min(0.9, 0.5 + xg), 2),
            team=shot.team,
            players=[p for p in (shot.player, keeper.player if keeper else None) if p],
            evidence=sorted([shot.id] + ([keeper.id] if keeper else [])),
            metrics=metrics,
            fallback_text=f"Big chance for {ctx.team_name(shot.team)}: {ctx.name(shot.player)}'s shot ({xg} xG) {how}.",
        )


class SpeedRecordRule(Rule):
    """A new top speed for the match, above an elite threshold."""

    def __init__(self) -> None:
        self.record = 0.0

    def on_event(self, ctx: MatchContext, e: MatchEvent) -> list[Moment]:
        speed = e.player_speed_kmh
        if speed is None or e.type not in (EventType.SPRINT, EventType.CARRY) or speed <= self.record:
            return []
        previous, self.record = self.record, speed
        if speed < SPEED_RECORD_KMH:
            return []
        return [
            ctx.moment(
                kind=MomentKind.SPEED_THRESHOLD,
                importance=0.4,
                team=e.team,
                players=[e.player] if e.player else [],
                evidence=[e.id],
                metrics={"player_speed_kmh": speed, "threshold_kmh": SPEED_RECORD_KMH, "previous_record_kmh": previous},
                fallback_text=f"{ctx.name(e.player)} hits {speed} km/h, the fastest sprint of the match.",
            )
        ]


class CardRule(Rule):
    def on_event(self, ctx: MatchContext, e: MatchEvent) -> list[Moment]:
        if e.type is not EventType.CARD:
            return []
        red = e.outcome is Outcome.RED
        foul = next(
            (
                ev
                for ev in reversed(ctx.events)
                if ev.type is EventType.FOUL and ev.player == e.player and e.t - ev.t <= CARD_FOUL_LOOKBACK_S
            ),
            None,
        )
        colour = "Red" if red else "Yellow"
        return [
            ctx.moment(
                kind=MomentKind.CARD,
                importance=0.8 if red else 0.3,
                team=e.team,
                players=[e.player] if e.player else [],
                evidence=sorted([e.id] + ([foul.id] if foul else [])),
                metrics={"red_card": 1.0 if red else 0.0},
                fallback_text=f"{colour} card for {ctx.name(e.player)} ({ctx.team_name(e.team)}).",
            )
        ]


# --------------------------------------------------------------------------- snapshot rules


class PhaseRule(Rule):
    """Half-time and full-time summaries: the facts the Recap agent works from."""

    def __init__(self) -> None:
        self._done: set[Phase] = set()
        self._peaks: dict[TeamSide, float] = {H: 0.0, A: 0.0}

    def on_snapshot(self, ctx: MatchContext, s: StatSnapshot) -> list[Moment]:
        for side, stats in ((H, s.home), (A, s.away)):
            self._peaks[side] = max(self._peaks[side], stats.pressure_index)
        if s.phase not in (Phase.HALF_TIME, Phase.FULL_TIME) or s.phase in self._done:
            return []
        self._done.add(s.phase)
        label = "Half-time" if s.phase is Phase.HALF_TIME else "Full-time"
        metrics = {
            "home_goals": s.score.home,
            "away_goals": s.score.away,
            "home_xg": s.home.xg,
            "away_xg": s.away.xg,
            "home_shots": s.home.shots,
            "away_shots": s.away.shots,
            "home_shots_on_target": s.home.shots_on_target,
            "away_shots_on_target": s.away.shots_on_target,
            "home_possession_pct": s.home.possession_pct,
            "away_possession_pct": s.away.possession_pct,
            "home_pass_accuracy_pct": s.home.pass_accuracy_pct,
            "away_pass_accuracy_pct": s.away.pass_accuracy_pct,
            # Peaks reset at half-time, so at full time these describe the second half only.
            "home_pressure_index_peak_half": self._peaks[H],
            "away_pressure_index_peak_half": self._peaks[A],
        }
        if s.phase is Phase.HALF_TIME:
            self._peaks = {H: 0.0, A: 0.0}
        return [
            ctx.moment(
                t=s.t,
                minute=s.minute,
                kind=MomentKind.PHASE,
                importance=1.0 if s.phase is Phase.FULL_TIME else 0.9,
                team=None,
                players=[],
                evidence=sorted({s.last_event_id, *ctx.goal_ids}),
                metrics=metrics,
                fallback_text=f"{label}: {ctx.score_line()}.",
            )
        ]


class PressureSurgeRule(Rule):
    """A team's pressure index jumps from normal to high within a few minutes."""

    def __init__(self) -> None:
        self._cooldown = _Cooldown(SURGE_COOLDOWN_S)

    def on_snapshot(self, ctx: MatchContext, s: StatSnapshot) -> list[Moment]:
        history = ctx.history(SURGE_LOOKBACK_S)
        moments: list[Moment] = []
        for side in (H, A):
            now = (s.home if side is H else s.away).pressure_index
            before = min((h.home if side is H else h.away).pressure_index for h in history)
            if now < SURGE_TO or before > SURGE_FROM or not self._cooldown.ready(side, s.t):
                continue
            self._cooldown.mark(side, s.t)
            pressing = ctx.recent(PRESSING, team=side)
            high = [e for e in pressing if e.start and e.start[0] > 52.5]
            regains = [e for e in high if e.type is EventType.INTERCEPTION or e.outcome is Outcome.SUCCESS]
            moments.append(
                ctx.moment(
                    kind=MomentKind.PRESSURE_SURGE,
                    importance=0.6,
                    team=side,
                    players=ctx.top_players(high or pressing),
                    evidence=_latest(high or pressing) or [s.last_event_id],
                    metrics={
                        "pressure_index_before": before,
                        "pressure_index_after": now,
                        "window_min": SURGE_LOOKBACK_S / 60,
                        "pressing_actions_5min": len(pressing),
                        "high_regains_5min": len(regains),
                    },
                    fallback_text=f"{ctx.team_name(side)} are pressing hard: pressure index up from {before} to {now}.",
                )
            )
        return moments


class MomentumSwingRule(Rule):
    """Momentum flips from one team to the other, backed by attacking evidence."""

    def __init__(self) -> None:
        self._cooldown = _Cooldown(SWING_COOLDOWN_S)

    def on_snapshot(self, ctx: MatchContext, s: StatSnapshot) -> list[Moment]:
        if not self._cooldown.ready("swing", s.t):
            return []
        history = [h.momentum for h in ctx.history(SWING_LOOKBACK_S)]
        if s.momentum >= SWING_TO and min(history) <= -SWING_FROM:
            side, before = H, min(history)
        elif s.momentum <= -SWING_TO and max(history) >= SWING_FROM:
            side, before = A, max(history)
        else:
            return []
        window = SWING_LOOKBACK_S
        shots = ctx.recent((EventType.SHOT,), team=side, within_s=window)
        entries = [
            e
            for e in ctx.recent((EventType.PASS,), team=side, within_s=window)
            if e.outcome is Outcome.SUCCESS and e.start and e.end and e.start[0] < 70 <= e.end[0]
        ]
        if not shots or len(shots) + len(entries) < SWING_MIN_ATTACKS:
            return []  # the number moved, but there is no attacking evidence to explain it
        self._cooldown.mark("swing", s.t)
        evidence = sorted(e.id for e in (shots + entries[-MAX_EVIDENCE:])[-MAX_EVIDENCE:])
        return [
            ctx.moment(
                kind=MomentKind.MOMENTUM_SWING,
                importance=0.65,
                team=side,
                players=ctx.top_players(shots + entries),
                evidence=evidence or [s.last_event_id],
                metrics={
                    "momentum_before": before,
                    "momentum_after": s.momentum,
                    "window_min": window / 60,
                    "shots_in_window": len(shots),
                    "final_third_entries_in_window": len(entries),
                },
                fallback_text=f"Momentum has swung to {ctx.team_name(side)}: {_plural(len(shots), 'shot')} and "
                f"{_plural(len(entries), 'entry', 'entries')} into the final third in the last "
                f"{int(window // 60)} minutes.",
            )
        ]


class ControlShiftRule(Rule):
    """The match turns from controlled to chaotic."""

    def __init__(self) -> None:
        self._cooldown = _Cooldown(CHAOS_COOLDOWN_S)

    def on_snapshot(self, ctx: MatchContext, s: StatSnapshot) -> list[Moment]:
        history = [h.control_chaos for h in ctx.history(CHAOS_LOOKBACK_S)]
        before = min(history)
        if s.control_chaos < CHAOS_TO or before > CHAOS_FROM or not self._cooldown.ready("chaos", s.t):
            return []
        if ctx.emitted_since(MomentKind.PRESSURE_SURGE, CHAOS_LOOKBACK_S):
            return []  # the turnovers are explained by a team's press, already announced
        self._cooldown.mark("chaos", s.t)
        turnovers = ctx.recent((EventType.POSSESSION_CHANGE,))
        fouls = ctx.recent((EventType.FOUL, EventType.CARD))
        evidence = sorted(e.id for e in sorted(turnovers + fouls, key=lambda e: e.id)[-10:])
        return [
            ctx.moment(
                kind=MomentKind.CONTROL_SHIFT,
                importance=0.6,
                team=None,
                players=ctx.top_players(fouls),
                evidence=evidence or [s.last_event_id],
                metrics={
                    "control_chaos_before": before,
                    "control_chaos_after": s.control_chaos,
                    "turnovers_5min": len(turnovers),
                    "fouls_5min": len([e for e in fouls if e.type is EventType.FOUL]),
                    "rhythm_epm": s.rhythm_epm,
                },
                fallback_text=f"The match has turned chaotic: {_plural(len(turnovers), 'turnover')} in 5 minutes, "
                f"control-chaos index up from {before} to {s.control_chaos}.",
            )
        ]


def default_rules() -> list[Rule]:
    return [
        GoalRule(),
        BigChanceRule(),
        SpeedRecordRule(),
        CardRule(),
        PhaseRule(),
        PressureSurgeRule(),
        MomentumSwingRule(),
        ControlShiftRule(),
    ]

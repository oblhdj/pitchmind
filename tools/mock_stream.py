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
from itertools import pairwise
from pathlib import Path

from mock_moments import MOMENTS
from mock_script import (
    AWAY,
    EVENTS,
    FT_T,
    HOME,
    HT_T,
    KEY,
    MATCH_ID,
    SEGMENTS,
    SPEED_ALERT,
    SUBS,
    Scripted,
    Text,
    minute_of,
    phase_of,
)
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
    Overlay,
    OverlayMetric,
    OverlaySlot,
    Phase,
    Player,
    PlayerStats,
    Position,
    Score,
    StatSnapshot,
    TeamSide,
    TeamStats,
    parse_wire,
)
from pitchmind_football import running_rate_m_per_min
from pitchmind_simulator.league import build_match_meta

Wire = MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay
Timed = tuple[float, int, Wire]

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


def _team_stats(side: TeamSide, t: float) -> TeamStats:
    home = side is HOME
    minutes = t / 60
    home_poss = interp("home_poss", t)
    xg = interp("home_xg" if home else "away_xg", t)
    return TeamStats(
        possession_pct=round(home_poss if home else 100 - home_poss, 1),
        passes=int(minutes * (5.1 if home else 4.3)),
        pass_accuracy_pct=83.4 if home else 79.1,
        avg_pass_difficulty=0.42 if home else 0.39,
        shots=math.floor(interp("home_shots" if home else "away_shots", t)),
        shots_on_target=math.floor(interp("home_sot" if home else "away_sot", t)),
        xg=round(xg, 2),
        xt=round(xg * 0.85, 2),
        tackles_won=int(minutes * (0.19 if home else 0.21)),
        pressure_index=round(interp("home_pi" if home else "away_pi", t), 2),
        distance_covered_m=round(minutes * 1165),
    )


def _one_player(
    p: Player, side: TeamSide, mins: float, mine: list[MatchEvent], xg_by_id: dict[int, float]
) -> PlayerStats:
    shots = [e for e in mine if e.type is EventType.SHOT]
    sprint_speeds = [e.player_speed_kmh for e in mine if e.player_speed_kmh is not None]
    touches = int(mins * _TOUCH_RATE[p.position])
    base_speed = 24 + p.attributes.pace * 0.1
    return PlayerStats(
        player_id=p.id,
        team=side,
        touches=touches,
        passes=int(touches * 0.75),
        pass_accuracy_pct=round(min(99.0, 70 + p.attributes.passing * 0.2), 1),
        shots=len(shots),
        xg=round(sum(xg_by_id.get(e.id, 0.0) for e in shots), 2),
        tackles_won=int(mins * p.attributes.defending / 100 * 0.05),
        distance_covered_m=round(mins * running_rate_m_per_min(p.position, p.attributes.stamina)),
        top_speed_kmh=round(max([base_speed, *sprint_speeds]), 1),
        sprints=int(mins * p.attributes.pace / 700) + sum(e.type is EventType.SPRINT for e in mine),
    )


def _player_stats(meta: MatchMeta, past: list[MatchEvent], xg_by_id: dict[int, float], t: float) -> list[PlayerStats]:
    players: list[PlayerStats] = []
    for team in (meta.home, meta.away):
        starters = set(team.starting_xi)
        for p in team.players:
            mins = _minutes_played(p.id, starters, t)
            if mins > 0:
                players.append(_one_player(p, team.side, mins, [e for e in past if e.player == p.id], xg_by_id))
    return players


def build_snapshot(t: float, meta: MatchMeta, events: list[MatchEvent], ids: dict[str, int]) -> StatSnapshot:
    past = [e for e in events if e.t <= t]
    goals = [e for e in past if e.type is EventType.GOAL]
    xg_by_id = {ids[ev.key]: ev.xg for ev in EVENTS if ev.type is EventType.SHOT}
    return StatSnapshot(
        match_id=MATCH_ID,
        t=t,
        minute=minute_of(t),
        phase=Phase.HALF_TIME if t == HT_T else phase_of(t),
        last_event_id=max((e.id for e in past), default=0),
        score=Score(home=sum(e.team is HOME for e in goals), away=sum(e.team is AWAY for e in goals)),
        home=_team_stats(HOME, t),
        away=_team_stats(AWAY, t),
        momentum=round(interp("momentum", t), 2),
        control_chaos=round(interp("control_chaos", t), 2),
        rhythm_epm=round(interp("rhythm", t), 1),
        players=_player_stats(meta, past, xg_by_id, t),
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


def _moment_for(sm: Scripted, ids: dict[str, int]) -> Moment:
    return Moment(
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


def _claims_for(sm: Scripted, text: Text, ids: dict[str, int]) -> list[Claim]:
    return [
        Claim(text=ct, evidence=[ids[k] for k in keys], metrics={m: sm.metrics[m] for m in mkeys})
        for ct, (keys, mkeys) in zip(text.claims, sm.claims, strict=True)
    ]


def _insight_for(sm: Scripted, moment: Moment, seg_name: str, text: Text, i: int, ids: dict[str, int]) -> Insight:
    seg = SEGMENTS[seg_name]
    delay = 6.0 if sm.insight_kind is InsightKind.RECAP else 4.0
    if seg_name in sm.template_segments:  # agents "failed": deterministic template text
        return Insight(
            id=f"ins-{MATCH_ID}-{sm.n}-{seg_name}",
            match_id=MATCH_ID,
            moment_id=moment.id,
            t=sm.t + delay + i * 0.5,
            kind=sm.insight_kind,
            segment=seg,
            headline="Match update",
            body=sm.fallback,
            claims=[],
            verified=True,
            fallback=True,
            agent_trace=[AgentName.ORCHESTRATOR, AgentName.EXPLAIN, AgentName.TEMPLATE],
            model=None,
            latency_ms=900,
        )
    return Insight(
        id=f"ins-{MATCH_ID}-{sm.n}-{seg_name}",
        match_id=MATCH_ID,
        moment_id=moment.id,
        t=sm.t + delay + i * 0.5,
        kind=sm.insight_kind,
        segment=seg,
        headline=text.headline,
        body=text.body,
        claims=_claims_for(sm, text, ids),
        verified=True,
        fallback=False,
        agent_trace=_trace(sm.insight_kind, seg.language),
        model="mock",
        latency_ms=2100 + (sm.n * 731 + i * 389) % 4300,
    )


def _overlay_for(sm: Scripted, moment: Moment, insight: Insight, overlay_id: str) -> Overlay:
    seg = insight.segment
    metric = None
    if sm.metric:
        name, mkey, unit = sm.metric
        metric = OverlayMetric(name=name, value=sm.metrics[mkey], unit=unit)
    return Overlay(
        overlay_id=overlay_id,
        match_id=MATCH_ID,
        insight_id=insight.id,
        show_at=insight.t + 1,
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
    )


def _speed_alert(ids: dict[str, int], overlay_n: int) -> list[Timed]:
    """The 72' stat alert: a moment and player-tag overlays straight from a threshold, no agent."""
    alert = SPEED_ALERT
    ev_id = ids[alert.event]
    moment = Moment(
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
    )
    out: list[Timed] = [(alert.t + 1, 3, moment)]
    for seg_name, title in alert.titles.items():
        seg = SEGMENTS[seg_name]
        overlay_n += 1
        overlay = Overlay(
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
        )
        out.append((alert.t + 1.5, 5, overlay))
    return out


def build_story(ids: dict[str, int]) -> list[Timed]:
    """Moments, insights and overlays as (publish time, order, message)."""
    out: list[Timed] = []
    overlay_n = 0
    for sm in MOMENTS:
        moment = _moment_for(sm, ids)
        out.append((sm.t + 1, 3, moment))
        for i, (seg_name, text) in enumerate(sm.texts.items()):
            insight = _insight_for(sm, moment, seg_name, text, i, ids)
            overlay_n += 1
            out.append((insight.t, 4, insight))
            out.append((insight.t, 5, _overlay_for(sm, moment, insight, f"ov-{overlay_n}")))
    return out + _speed_alert(ids, overlay_n)


def build_stream() -> tuple[MatchMeta, list[Wire]]:
    meta = build_match_meta(MATCH_ID)
    events, ids = build_events()

    snapshot_times = {float(s) for s in range(0, int(FT_T) + 1, 300)} | {HT_T, FT_T}
    snapshot_times |= {sm.t + 2 for sm in MOMENTS if sm.t not in (HT_T, FT_T)}
    snapshot_times.add(SPEED_ALERT.t + 2)

    timeline: list[Timed] = [(0.0, 0, meta)]
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

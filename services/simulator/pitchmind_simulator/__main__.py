"""Run a synthetic match.

Examples (repo root):
    python -m pitchmind_simulator                              # demo match -> data/sim/M001.jsonl
    python -m pitchmind_simulator --scenario organic --seed 42 --match-id M042
    python -m pitchmind_simulator --live --speed 20            # stream to stdout in (scaled) real time
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from pitchmind_contracts import EventType, MatchEvent, Outcome, TeamSide

from .engine import MatchEngine
from .league import build_match_meta
from .scenario import SCENARIOS


def positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {raw}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="demo-comeback")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--match-id", default="M001")
    parser.add_argument("--out", type=Path, default=None, help="JSONL path (default data/sim/<match-id>.jsonl)")
    parser.add_argument("--live", action="store_true", help="print events to stdout, paced by match time")
    parser.add_argument("--speed", type=positive_float, default=1.0, help="live pacing factor (20 = 20x real time)")
    args = parser.parse_args()

    meta = build_match_meta(args.match_id, seed=args.seed)
    engine = MatchEngine(meta, SCENARIOS[args.scenario], seed=args.seed)

    if args.live:
        wall_start, previous_t = time.monotonic(), 0.0
        for msg in engine.run():
            if isinstance(msg, MatchEvent) and msg.t > previous_t:
                target = wall_start + msg.t / args.speed
                time.sleep(max(0.0, target - time.monotonic()))
                previous_t = msg.t
            sys.stdout.write(msg.model_dump_json() + "\n")
            sys.stdout.flush()
        return

    messages = list(engine.run())
    out = args.out or Path("data/sim") / f"{args.match_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(m.model_dump_json() for m in messages) + "\n", encoding="utf-8")

    events = [m for m in messages if isinstance(m, MatchEvent)]
    types = Counter(e.type.value for e in events)
    passes = [e for e in events if e.type is EventType.PASS]
    accuracy = 100 * sum(e.outcome is Outcome.SUCCESS for e in passes) / max(1, len(passes))
    print(f"{args.scenario} seed={args.seed}: {len(events)} events -> {out}")
    score = f"{engine.score[TeamSide.HOME]}-{engine.score[TeamSide.AWAY]}"
    print(f"score {score} | pass accuracy {accuracy:.1f}% | {dict(types)}")


if __name__ == "__main__":
    main()

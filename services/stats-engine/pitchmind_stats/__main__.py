"""Compute stat snapshots for a simulated match.

Examples (repo root):
    python -m pitchmind_simulator                       # writes data/sim/M001.jsonl
    python -m pitchmind_stats data/sim/M001.jsonl       # writes data/sim/M001.stats.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pitchmind_contracts import MatchEvent, MatchMeta, parse_wire

from .engine import replay


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("events", type=Path, help="JSONL file: MatchMeta line followed by MatchEvent lines")
    parser.add_argument("--out", type=Path, default=None, help="default: <events>.stats.jsonl")
    parser.add_argument("--every", type=float, default=60.0, help="snapshot interval in match seconds")
    args = parser.parse_args(argv)

    meta: MatchMeta | None = None
    events: list[MatchEvent] = []
    for line in args.events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        msg = parse_wire(line)
        if isinstance(msg, MatchMeta):
            meta = msg
        elif isinstance(msg, MatchEvent):
            events.append(msg)
    if meta is None:
        parser.error(f"{args.events} has no match_meta line")
    if not events:
        parser.error(f"{args.events} has no match_event lines")

    snapshots = replay(meta, events, snapshot_every_s=args.every)
    out = args.out or args.events.with_suffix(".stats.jsonl")
    out.write_text("\n".join(s.model_dump_json() for s in snapshots) + "\n", encoding="utf-8")

    final = snapshots[-1]
    h, a = final.home, final.away
    print(f"{len(snapshots)} snapshots -> {out}")
    print(
        f"FT {final.score.home}-{final.score.away} | possession {h.possession_pct}-{a.possession_pct} | "
        f"shots {h.shots}-{a.shots} | xG {h.xg}-{a.xg} | pass acc {h.pass_accuracy_pct}-{a.pass_accuracy_pct}"
    )


if __name__ == "__main__":
    main()

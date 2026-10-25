"""Detect moments in a simulated match.

Examples (repo root):
    python -m pitchmind_simulator                       # writes data/sim/M001.jsonl
    python -m pitchmind_moments data/sim/M001.jsonl     # writes data/sim/M001.moments.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pitchmind_contracts import MatchEvent, MatchMeta, parse_wire
from pitchmind_stats import replay

from .detector import detect


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("events", type=Path, help="JSONL file: MatchMeta line followed by MatchEvent lines")
    parser.add_argument("--out", type=Path, default=None, help="default: <events>.moments.jsonl")
    args = parser.parse_args(argv)

    meta: MatchMeta | None = None
    events: list[MatchEvent] = []
    for line in args.events.read_text(encoding="utf-8").splitlines():
        if line.strip():
            msg = parse_wire(line)
            if isinstance(msg, MatchMeta):
                meta = msg
            elif isinstance(msg, MatchEvent):
                events.append(msg)
    if meta is None:
        parser.error(f"{args.events} has no match_meta line")
    if not events:
        parser.error(f"{args.events} has no match_event lines")

    moments = detect(meta, events, replay(meta, events))
    out = args.out or args.events.with_suffix(".moments.jsonl")
    out.write_text("".join(m.model_dump_json() + "\n" for m in moments), encoding="utf-8")

    print(f"{len(moments)} moments -> {out}")
    for m in moments:
        print(f"  {m.minute:3d}'  {m.kind.value:17s} {m.importance:.2f}  {m.fallback_text}")


if __name__ == "__main__":
    main()

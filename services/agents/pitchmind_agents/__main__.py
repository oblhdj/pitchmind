"""Replay a wire stream through the agents.

    python -m pitchmind_agents                                    # mock LLM, demo match, insights to stdout
    python -m pitchmind_agents --llm foundry --env-file .env --output data/sim/insights.jsonl
    python -m pitchmind_agents --disable narrative                # failure-recovery demo
    python -m pitchmind_agents --llm foundry --env-file .env --trace foundry   # traces in Foundry

Reads JSONL wire messages (match_meta, match_event, stat_snapshot, moment), sends every
moment through the workflow and writes one insight per line, as soon as each is ready.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from pitchmind_contracts import AgentName, Insight

from .agents import AgentTeam, ClientSet
from .config import AgentsConfig
from .mock_llm import mock_client_set
from .runtime import load_env_file, read_wire, replay
from .segments import parse_segments
from .service import AgentsService
from .telemetry import configure_tracing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pitchmind_agents", description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=Path("data/mock/stream.jsonl"), help="wire JSONL to replay")
    parser.add_argument("--output", type=Path, help="insights JSONL (default: stdout)")
    parser.add_argument("--llm", choices=["mock", "foundry"], default="mock")
    parser.add_argument("--segments", default="demo", help='"demo", "all", or segment keys separated by ";"')
    parser.add_argument("--judge", action="store_true", help="LLM judge on writer and segment drafts")
    parser.add_argument(
        "--disable", action="append", type=AgentName, default=[], metavar="AGENT", help="kill an agent (repeatable)"
    )
    parser.add_argument("--env-file", type=Path, help="load KEY=VALUE lines, e.g. .env")
    parser.add_argument(
        "--trace", choices=["foundry", "otlp", "console"], help="export OpenTelemetry traces (foundry = App Insights)"
    )
    parser.add_argument("--trace-content", action="store_true", help="include prompts and replies in traces (dev only)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.env_file:
        load_env_file(args.env_file)
    try:
        config = AgentsConfig.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    disabled = config.disabled_agents | set(args.disable)
    config = replace(config, judge=config.judge or args.judge, disabled_agents=disabled)

    clients: ClientSet
    if args.llm == "foundry":
        from .clients import foundry_client_set

        clients = foundry_client_set()
    else:
        clients = mock_client_set()
    service = AgentsService(AgentTeam(clients, config), parse_segments(args.segments))

    with ExitStack() as stack:
        out: TextIO
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            out = stack.enter_context(args.output.open("w", encoding="utf-8"))
        else:
            out = sys.stdout
            if isinstance(out, io.TextIOWrapper):
                out.reconfigure(encoding="utf-8")  # Arabic text survives a redirect on Windows (cp1252)

        def write(insight: Insight) -> None:
            out.write(insight.model_dump_json() + "\n")
            out.flush()

        async def run() -> list[Insight]:
            if args.trace:
                writer = clients.clients[AgentName.NARRATIVE]
                await configure_tracing(args.trace, client=writer, sensitive=args.trace_content)
            return await replay(service, read_wire(args.input), on_insight=write)

        insights = asyncio.run(run())
    if args.output:
        print(f"{len(insights)} insights -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

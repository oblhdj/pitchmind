"""Run PitchMind live: simulator -> stats -> moments -> agents -> render -> WebSocket.

Examples (repo root):
    python -m pitchmind_runner                                   # demo match, 10x, offline agents
    python -m pitchmind_runner --speed 3 --llm foundry --env-file .env --record data/sim/demo.jsonl
    python -m pitchmind_runner --replay data/sim/demo.jsonl --speed 10

Then open the frontend in live mode: http://localhost:3000/?mode=live
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pitchmind_agents import LLM_AGENTS, AgentsConfig, parse_segments
from pitchmind_agents.runtime import load_env_file
from pitchmind_contracts import AgentName
from pitchmind_simulator import SCENARIOS
from websockets.asyncio.server import serve

from .gateway import Gateway
from .pipeline import Pipeline, PipelineConfig, read_recording, replay_recording

logger = logging.getLogger("pitchmind_runner")


def non_negative(raw: str) -> float:
    value = float(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {raw}")
    return value


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--speed", type=non_negative, default=10.0, help="match speed (1 = real time, 0 = instant)")
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="demo-comeback")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--match-id", default="M001")
    p.add_argument("--segments", default="demo", help='"demo", "all", or segment keys separated by ";"')
    p.add_argument("--llm", choices=["mock", "foundry"], default="mock")
    p.add_argument("--env-file", type=Path, help="KEY=VALUE file, e.g. .env (FOUNDRY_* settings)")
    p.add_argument(
        "--disable",
        action="append",
        default=[],
        choices=[a.value for a in LLM_AGENTS],
        help="kill an agent for the failure-recovery demo (repeatable)",
    )
    p.add_argument("--record", type=Path, help="write every message to this JSONL file")
    p.add_argument("--replay", type=Path, help="serve a recorded JSONL file instead of running the pipeline")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    return p.parse_args(argv)


async def run(args: argparse.Namespace) -> None:
    gateway = Gateway(record=args.record)
    async with serve(gateway.handler, args.host, args.port):
        logger.info("live feed on ws://%s:%d/ws  ->  open http://localhost:3000/?mode=live", args.host, args.port)
        if args.replay:
            messages = read_recording(args.replay)
            logger.info("replaying %d messages from %s at %gx", len(messages), args.replay, args.speed)
            await replay_recording(messages, gateway, args.speed)
        else:
            config = PipelineConfig(
                segments=parse_segments(args.segments),
                scenario=args.scenario,
                seed=args.seed,
                match_id=args.match_id,
                speed=args.speed,
                llm=args.llm,
                agents=AgentsConfig(disabled_agents=frozenset(AgentName(name) for name in args.disable)),
            )
            pipeline = Pipeline(config, gateway)
            pipeline.start()
            logger.info("playing %s (%s agents) at %gx", config.scenario, config.llm, config.speed)
            await pipeline.play()
            await pipeline.drain(timeout_s=600)
            logger.info("full time: %d insights, %d overlays", len(gateway.insights), len(gateway.overlays))
        gateway.close()
        logger.info("match over; still serving the replay to new clients (Ctrl+C to stop)")
        await asyncio.Future()  # serve until interrupted


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.env_file:
        load_env_file(args.env_file)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)


if __name__ == "__main__":
    main()

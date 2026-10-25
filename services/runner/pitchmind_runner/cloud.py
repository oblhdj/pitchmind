"""Run one pipeline stage as its own service (one Azure Container App per stage).

    python -m pitchmind_runner.cloud simulator|stats|moments|agents|render|gateway

Configuration comes from the environment, so the same image runs every stage:

    BUS_BACKEND=eventhubs  EVENTHUB_NAMESPACE=<name>.servicebus.windows.net
    SEGMENTS=demo          LLM=mock|foundry        (agents, render)
    SPEED=10  SCENARIO=demo-comeback  MATCH_PAUSE_S=30   (simulator: loops matches forever)
    PORT=8765                                            (gateway: WebSocket on 0.0.0.0)

Locally, ``python -m pitchmind_runner`` runs every stage in one process instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Mapping

from pitchmind_agents import AgentsConfig, configure_tracing, parse_segments
from pitchmind_bus import Bus, make_bus
from pitchmind_render import OverlayRenderer
from pitchmind_simulator import SCENARIOS, build_match_meta
from websockets.asyncio.server import serve

from .gateway import MAX_CLIENT_FRAME, Gateway
from .pipeline import PipelineConfig, build_agents
from .stages import agents_stage, moments_stage, render_stage, simulator_stage, stats_stage

logger = logging.getLogger("pitchmind_runner.cloud")

STAGES = ("simulator", "stats", "moments", "agents", "render", "gateway")


def config_from_env(env: Mapping[str, str]) -> PipelineConfig:
    return PipelineConfig(
        segments=parse_segments(env.get("SEGMENTS", "demo")),
        scenario=env.get("SCENARIO", "demo-comeback"),
        seed=int(env.get("SEED", "7")),
        speed=float(env.get("SPEED", "10")),
        llm=env.get("LLM", "mock"),
        agents=AgentsConfig.from_env(env),
    )


async def loop_matches(bus: Bus, config: PipelineConfig, pause_s: float) -> None:
    """Play the demo match again and again, so anyone opening the app sees a live game."""
    scenario = SCENARIOS[config.scenario]
    n = 0
    while True:
        n += 1
        meta = build_match_meta(f"M{n:03d}", seed=config.seed)
        logger.info("kick-off: match %s (%s) at %gx", meta.match_id, scenario.name, config.speed)
        await simulator_stage(bus, meta, scenario, config.seed, config.speed)
        await asyncio.sleep(pause_s)


async def setup_observability(env: Mapping[str, str]) -> bool:
    """Send OpenTelemetry traces (agent workflow spans, verifier rejections) to Application Insights.

    A tracing problem never stops a stage: it is logged and the stage runs untraced.
    """
    connection = env.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection:
        return False
    try:
        await configure_tracing("foundry", connection_string=connection)
    except Exception:
        logger.exception("could not configure Application Insights tracing; continuing without it")
        return False
    logger.info("tracing to Application Insights")
    return True


async def run_stage(stage: str, env: Mapping[str, str]) -> None:
    await setup_observability(env)
    bus = make_bus(env)
    config = config_from_env(env)
    try:
        if stage == "simulator":
            await loop_matches(bus, config, float(env.get("MATCH_PAUSE_S", "30")))
        elif stage == "stats":
            await stats_stage(bus)
        elif stage == "moments":
            await moments_stage(bus)
        elif stage == "agents":
            await agents_stage(bus, build_agents(config))
        elif stage == "render":
            await render_stage(bus, OverlayRenderer(config.segments))
        elif stage == "gateway":
            gateway = Gateway()
            consumer = gateway.run(bus)
            port = int(env.get("PORT", "8765"))
            # Inside the container, listening on all interfaces is required; ingress is the public edge.
            async with serve(gateway.handler, "0.0.0.0", port, max_size=MAX_CLIENT_FRAME):  # nosec B104
                logger.info("gateway listening on :%s/ws", env.get("PORT", "8765"))
                await consumer
        else:
            raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")
    finally:
        await bus.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=STAGES)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_stage(args.stage, os.environ))


if __name__ == "__main__":
    main()

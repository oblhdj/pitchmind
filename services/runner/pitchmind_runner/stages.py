"""The pipeline stages, each an independent consumer on the bus.

    simulator --match-events--> stats --match-stats--> moments --match-moments--> agents
                                                                                    |
    gateway <--match-overlays-- render <----------------match-insights--------------+

Every stage only talks to the bus, exactly as the separate Container Apps do in Azure, so
running them in one process locally exercises the same message flow.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from typing import Any

from pitchmind_agents import AgentsService
from pitchmind_bus import Bus, Wire
from pitchmind_contracts import Insight, MatchEvent, MatchMeta, Moment, Overlay, StatSnapshot, Topic
from pitchmind_moments import MomentDetector
from pitchmind_render import OverlayRenderer
from pitchmind_simulator import MatchEngine, Scenario
from pitchmind_stats import StatsEngine

logger = logging.getLogger(__name__)

Handler = Callable[[Wire], Awaitable[None]]
Stage = Coroutine[Any, Any, None]

KEEP_MATCHES = 3  # per-match state a stage keeps; the always-on demo starts new matches forever
META_WAIT_S = 5.0  # how long stats wait for their match's metadata before they are skipped


def forget_oldest(*stores: dict[str, Any]) -> None:
    for store in stores:
        while len(store) > KEEP_MATCHES:
            store.pop(next(iter(store)))  # dicts keep insertion order: the oldest match goes first


def consume(bus: Bus, topics: Sequence[Topic], group: str, handler: Handler) -> Stage:
    """Subscribe to ``topics`` *now*, and return the coroutine that handles their messages.

    Subscribing eagerly (not when the task first runs) guarantees a stage created before
    the match starts never misses its first messages, such as the match metadata.
    A failing message is logged and skipped: one bad message never stops a live stage.
    """
    subscriptions = [(topic, bus.subscribe(topic, group)) for topic in topics]

    async def one(topic: Topic, messages: AsyncIterator[Wire]) -> None:
        async for message in messages:
            try:
                await handler(message)
            except Exception:
                logger.exception("%s: failed on a %s message from %s", group, message.msg, topic)

    async def run() -> None:
        await asyncio.gather(*(one(topic, messages) for topic, messages in subscriptions))

    return run()


async def simulator_stage(
    bus: Bus, meta: MatchMeta, scenario: Scenario, seed: int, speed: float, meta_every_s: float = 0
) -> None:
    """Play the match onto ``match-events``. ``speed`` 0 means as fast as possible.

    ``meta_every_s`` > 0 re-announces the match metadata that often (wall clock), so a stage
    that starts or restarts mid-match (separate Container Apps reading from the latest
    position) still learns the match instead of ignoring it until the next kick-off.
    """
    loop = asyncio.get_running_loop()
    started = announced = loop.time()
    for message in MatchEngine(meta, scenario, seed).run():
        if isinstance(message, MatchEvent):
            if speed > 0:
                await asyncio.sleep(max(0.0, started + message.t / speed - loop.time()))
            else:
                await asyncio.sleep(0)  # let the consumers run
            if meta_every_s > 0 and loop.time() - announced >= meta_every_s:
                await bus.publish(Topic.MATCH_EVENTS, meta)
                announced = loop.time()
        await bus.publish(Topic.MATCH_EVENTS, message)
    logger.info("simulator: match %s finished", meta.match_id)


def warn_once(stage: str) -> Callable[[str], None]:
    """Log, once per match, that ``stage`` gets messages for a match whose metadata it has not seen."""
    warned: set[str] = set()

    def warn(match_id: str) -> None:
        if match_id not in warned:
            warned.add(match_id)
            logger.warning(
                "%s: no metadata yet for match %s; its messages are skipped until it arrives", stage, match_id
            )

    return warn


def stats_stage(bus: Bus) -> Stage:
    engines: dict[str, StatsEngine] = {}
    unknown = warn_once("stats")

    async def handle(message: Wire) -> None:
        if isinstance(message, MatchMeta):
            if message.match_id not in engines:  # a repeat is the simulator's re-announcement
                engines[message.match_id] = StatsEngine(message)
                forget_oldest(engines)
        elif isinstance(message, MatchEvent):
            if (engine := engines.get(message.match_id)) is None:
                unknown(message.match_id)
            elif (snapshot := engine.apply(message)) is not None:
                await bus.publish(Topic.MATCH_STATS, snapshot)

    return consume(bus, [Topic.MATCH_EVENTS], "stats", handle)


def moments_stage(bus: Bus) -> Stage:
    detectors: dict[str, MomentDetector] = {}
    ready: dict[str, asyncio.Event] = {}
    gave_up: set[str] = set()  # matches whose metadata did not come in time (stage started late)
    unknown = warn_once("moments")

    def gate(match_id: str) -> asyncio.Event:
        return ready.setdefault(match_id, asyncio.Event())

    async def publish(moments: list[Moment]) -> None:
        for moment in moments:
            await bus.publish(Topic.MATCH_MOMENTS, moment)

    async def handle(message: Wire) -> None:
        if isinstance(message, MatchMeta):
            if message.match_id not in detectors:  # a repeat is the simulator's re-announcement
                detectors[message.match_id] = MomentDetector(message)
            gate(message.match_id).set()
            forget_oldest(detectors, ready)
        elif isinstance(message, MatchEvent):
            if (detector := detectors.get(message.match_id)) is None:
                unknown(message.match_id)
            else:
                await publish(detector.on_event(message))
        elif isinstance(message, StatSnapshot):
            match_id = message.match_id
            if match_id not in detectors and match_id not in gave_up:
                # Stats may outrun the metadata on the other topic; wait a little, but never forever:
                # this loop serves every match, and a late-started stage may never see this one's.
                try:
                    await asyncio.wait_for(gate(match_id).wait(), META_WAIT_S)
                except TimeoutError:
                    gave_up.add(match_id)
            if (detector := detectors.get(match_id)) is None:
                unknown(match_id)
            else:
                await publish(detector.on_snapshot(message))

    return consume(bus, [Topic.MATCH_EVENTS, Topic.MATCH_STATS], "moments", handle)


def agents_stage(bus: Bus, service: AgentsService) -> Stage:
    """Context flows in from events and stats; each moment fans out to one insight per segment."""

    async def handle(message: Wire) -> None:
        if isinstance(message, Moment):
            async for insight in service.stream(message):
                await bus.publish(Topic.MATCH_INSIGHTS, insight)
        elif not isinstance(message, Insight | Overlay):
            await service.handle(message)

    return consume(bus, [Topic.MATCH_EVENTS, Topic.MATCH_STATS, Topic.MATCH_MOMENTS], "agents", handle)


def render_stage(bus: Bus, renderer: OverlayRenderer) -> Stage:
    async def handle(message: Wire) -> None:
        for overlay in renderer.observe(message):
            await bus.publish(Topic.MATCH_OVERLAYS, overlay)

    return consume(bus, [Topic.MATCH_EVENTS, Topic.MATCH_MOMENTS, Topic.MATCH_INSIGHTS], "render", handle)

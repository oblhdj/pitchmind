"""Stages that start after kick-off (separate Container Apps, consumers at the latest position)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pitchmind_bus import InMemoryBus, Wire
from pitchmind_contracts import MatchEvent, MatchMeta, StatSnapshot, Topic, parse_wire
from pitchmind_runner import Gateway
from pitchmind_runner.stages import simulator_stage, stats_stage
from pitchmind_simulator import SCENARIOS, MatchEngine, build_match_meta
from pitchmind_stats import StatsEngine

SCENARIO = SCENARIOS["demo-comeback"]


def demo_events(meta: MatchMeta) -> list[MatchEvent]:
    return [m for m in MatchEngine(meta, SCENARIO, 7).run() if isinstance(m, MatchEvent)]


async def collect(messages: AsyncIterator[Wire], into: list[Wire]) -> None:
    async for message in messages:
        into.append(message)


async def settle(bus: InMemoryBus) -> None:
    while bus.busy():
        await asyncio.sleep(0.01)


def metas_published(meta_every_s: float) -> list[MatchMeta]:
    async def scenario() -> list[Wire]:
        bus = InMemoryBus()
        seen: list[Wire] = []
        probe = asyncio.create_task(collect(bus.subscribe(Topic.MATCH_EVENTS, "probe"), seen))
        await simulator_stage(bus, build_match_meta("M001"), SCENARIO, 7, 0, meta_every_s)
        await bus.close()
        await probe
        return seen

    seen = asyncio.run(scenario())
    assert isinstance(seen[0], MatchMeta)
    return [m for m in seen if isinstance(m, MatchMeta)]


def test_the_simulator_re_announces_the_match_only_when_asked() -> None:
    assert len(metas_published(0)) == 1
    repeated = metas_published(1e-6)
    assert len(repeated) > 1 and {m.match_id for m in repeated} == {"M001"}


def test_a_stage_that_missed_kick_off_joins_at_the_next_announcement(caplog: pytest.LogCaptureFixture) -> None:
    meta = build_match_meta("M001")
    events = demo_events(meta)

    async def scenario() -> tuple[int, list[Wire]]:
        bus = InMemoryBus()
        snapshots: list[Wire] = []
        probe = asyncio.create_task(collect(bus.subscribe(Topic.MATCH_STATS, "probe"), snapshots))
        await bus.publish(Topic.MATCH_EVENTS, meta)  # kick-off, before the stats stage is up
        stage = asyncio.create_task(stats_stage(bus))
        for event in events[:200]:
            await bus.publish(Topic.MATCH_EVENTS, event)
        await settle(bus)
        missed = len(snapshots)
        for chunk in (events[200:400], events[400:]):
            await bus.publish(Topic.MATCH_EVENTS, meta)  # re-announcement: joins once, never resets
            for event in chunk:
                await bus.publish(Topic.MATCH_EVENTS, event)
        await settle(bus)
        await bus.close()
        await asyncio.gather(stage, probe)
        return missed, snapshots

    with caplog.at_level(logging.WARNING, logger="pitchmind_runner.stages"):
        missed, snapshots = asyncio.run(scenario())

    assert missed == 0
    assert [r.getMessage() for r in caplog.records].count(
        "stats: no metadata yet for match M001; its messages are skipped until it arrives"
    ) == 1
    # One engine from the first announcement on: the same numbers as an engine that saw events[200:].
    reference = StatsEngine(meta)
    expected = [s for e in events[200:] if (s := reference.apply(e)) is not None]
    assert snapshots and all(isinstance(s, StatSnapshot) for s in snapshots)
    assert snapshots[-1].model_dump_json() == expected[-1].model_dump_json()


def test_the_gateway_keeps_its_history_through_re_announcements(tmp_path: Path) -> None:
    meta = build_match_meta("M001")
    first = demo_events(meta)[0]
    record = tmp_path / "match.jsonl"
    gateway = Gateway(record=record)
    gateway.observe(meta)
    gateway.observe(first)
    gateway.observe(meta)
    assert gateway.meta == meta and list(gateway.events) == [first]

    following = build_match_meta("M002")
    gateway.observe(following)
    gateway.close()
    assert gateway.meta == following and not gateway.events
    recorded = [parse_wire(line) for line in record.read_text(encoding="utf-8").splitlines()]
    assert [m.match_id for m in recorded if isinstance(m, MatchMeta)] == ["M001", "M002"]

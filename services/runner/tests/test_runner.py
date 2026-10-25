import asyncio
import json
from collections import Counter
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote

import pytest
from pitchmind_agents import AgentsService, parse_segments
from pitchmind_bus import Wire
from pitchmind_contracts import (
    Insight,
    InsightKind,
    MatchMeta,
    Moment,
    MomentKind,
    Overlay,
    OverlaySlot,
    parse_wire,
)
from pitchmind_runner import Gateway, Pipeline, PipelineConfig, cloud, read_recording, replay_recording
from pitchmind_runner.__main__ import parse_args
from pitchmind_runner.cloud import config_from_env
from pitchmind_runner.cloud import main as cloud_main
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

SEGMENTS = parse_segments("demo")
ARABIC = "casual|ar|club:home|player:*|metric:*"


def segment_of(message: Insight | Overlay) -> str:
    return message.segment.key if isinstance(message, Insight) else message.segment_key


async def run_match(gateway: Gateway) -> None:
    pipeline = Pipeline(PipelineConfig(segments=SEGMENTS, speed=0), gateway)
    pipeline.start()
    await pipeline.play()
    await pipeline.drain(timeout_s=120)
    await pipeline.stop()


@pytest.fixture(scope="module")
def played(tmp_path_factory: pytest.TempPathFactory) -> tuple[Gateway, Path]:
    record = tmp_path_factory.mktemp("rec") / "match.jsonl"
    gateway = Gateway(record=record)
    asyncio.run(run_match(gateway))
    gateway.close()
    return gateway, record


def test_the_whole_pipeline_tells_the_demo_story(played: tuple[Gateway, Path]) -> None:
    gateway, _ = played
    kinds = Counter(m.kind for m in gateway.moments)
    assert kinds[MomentKind.GOAL] == 3 and kinds[MomentKind.PHASE] == 2 and kinds[MomentKind.SPEED_THRESHOLD] == 1
    keys = {s.key for s in SEGMENTS}
    assert {i.segment.key for i in gateway.insights} == keys
    assert {o.segment_key for o in gateway.overlays} == keys
    insight_ids = {i.id for i in gateway.insights}
    assert all(o.insight_id in insight_ids for o in gateway.overlays if o.insight_id)
    assert any(o.slot is OverlaySlot.RECAP_CARD for o in gateway.overlays)
    assert any(o.slot is OverlaySlot.PLAYER_TAG and o.player_id == "H11" for o in gateway.overlays)
    assert gateway.snapshot is not None and (gateway.snapshot.score.home, gateway.snapshot.score.away) == (2, 1)


def test_every_overlay_is_grounded_in_its_moment(played: tuple[Gateway, Path]) -> None:
    gateway, _ = played
    evidence = {m.id: set(m.evidence) for m in gateway.moments}
    insights = {i.id: i for i in gateway.insights}
    for overlay in gateway.overlays:
        if overlay.insight_id:
            moment_id = insights[overlay.insight_id].moment_id
            assert moment_id is not None and set(overlay.evidence) <= evidence[moment_id]


def test_websocket_client_gets_catch_up_filtered_to_its_segment_and_can_switch(
    played: tuple[Gateway, Path],
) -> None:
    gateway, _ = played
    analyst = SEGMENTS[0].key

    async def scenario() -> tuple[list[Wire], list[Wire]]:
        async with serve(gateway.handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/ws?segment={quote(ARABIC)}") as ws:
                first = [parse_wire(await ws.recv()) for _ in range(len(gateway.catch_up(ARABIC)))]
                await ws.send(json.dumps({"type": "subscribe", "segment_key": analyst}))
                switched = [parse_wire(await ws.recv()) for _ in range(len(gateway.segment_history(analyst)))]
        return first, switched

    first, switched = asyncio.run(scenario())
    assert isinstance(first[0], MatchMeta)
    personal = [m for m in first if isinstance(m, Insight | Overlay)]
    assert personal and all(segment_of(m) == ARABIC for m in personal)
    assert switched and all(segment_of(m) == analyst for m in switched if isinstance(m, Insight | Overlay))


def test_unknown_paths_are_refused(played: tuple[Gateway, Path]) -> None:
    gateway, _ = played

    async def scenario() -> int | None:
        async with serve(gateway.handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/elsewhere") as ws:
                await ws.wait_closed()
                return ws.close_code

    assert asyncio.run(scenario()) == 1008


def test_drain_waits_for_slow_agents_so_the_recording_is_complete(
    played: tuple[Gateway, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review H1: a real model works on the last moment after every queue is empty."""
    gateway, _ = played
    real_stream = AgentsService.stream

    async def slow_stream(self: AgentsService, moment: Moment) -> AsyncGenerator[Insight]:
        await asyncio.sleep(0.15)
        async for insight in real_stream(self, moment):
            yield insight

    monkeypatch.setattr(AgentsService, "stream", slow_stream)
    slow = Gateway()
    asyncio.run(run_match(slow))
    assert len(slow.insights) == len(gateway.insights)
    assert slow.insights[-1].kind is InsightKind.RECAP  # the full-time recap made it


def test_catch_up_is_never_interleaved_with_live_messages(played: tuple[Gateway, Path]) -> None:
    """Review M1: live messages that arrive during a client's catch-up are sent after it."""
    gateway, _ = played
    late = Gateway()
    for message in [*gateway.catch_up(None)[:50]]:
        late.observe(message)
    live = gateway.overlays[-1]
    history = late.catch_up(None)

    class FakeClient:
        def __init__(self) -> None:
            self.request = SimpleNamespace(path="/ws")
            self.sent: list[str] = []

        async def send(self, text: str) -> None:
            if len(self.sent) == 1:
                late.observe(live)  # arrives while the catch-up is still being sent
            self.sent.append(text)

        def __aiter__(self) -> "FakeClient":
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

    client = FakeClient()
    asyncio.run(late.handler(cast(Any, client)))
    received = [parse_wire(text) for text in client.sent]
    assert received[: len(history)] == history
    assert received[len(history) :] == [live]


def test_disable_rejects_unknown_agents() -> None:
    """Review M2: a typo must fail loudly, not silently skip the failure-recovery demo."""
    with pytest.raises(SystemExit):
        parse_args(["--disable", "narative"])
    assert parse_args(["--disable", "narrative"]).disable == ["narrative"]


def test_cloud_stage_config_comes_from_the_environment() -> None:
    config = config_from_env(
        {"SEGMENTS": "demo", "SPEED": "6", "LLM": "mock", "PITCHMIND_DISABLED_AGENTS": "narrative"}
    )
    assert config.speed == 6 and config.llm == "mock" and len(config.segments) == len(SEGMENTS)
    assert {a.value for a in config.agents.disabled_agents} == {"narrative"}
    with pytest.raises(SystemExit):
        cloud_main(["not-a-stage"])


def test_tracing_is_configured_only_with_a_connection_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M1: the App Insights connection string must actually turn tracing on."""
    calls: list[str | None] = []

    async def fake_configure(target: str, *, connection_string: str | None = None) -> None:
        calls.append(connection_string)

    monkeypatch.setattr(cloud, "configure_tracing", fake_configure)
    assert asyncio.run(cloud.setup_observability({})) is False
    assert asyncio.run(cloud.setup_observability({"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=x"}))
    assert calls == ["InstrumentationKey=x"]

    async def broken(target: str, *, connection_string: str | None = None) -> None:
        raise RuntimeError("exporter unavailable")

    monkeypatch.setattr(cloud, "configure_tracing", broken)
    assert asyncio.run(cloud.setup_observability({"APPLICATIONINSIGHTS_CONNECTION_STRING": "x"})) is False


def test_subscribe_is_throttled(played: tuple[Gateway, Path]) -> None:
    """Review M4: switching segment resends history, so it is limited to once per second."""
    gateway, _ = played
    sent: list[str] = []

    class FakeClient:
        async def send(self, text: str) -> None:
            sent.append(text)

    client = cast(Any, FakeClient())
    message = json.dumps({"type": "subscribe", "segment_key": ARABIC})

    async def scenario() -> tuple[int, int]:
        await gateway._on_client_message(client, message)
        first = len(sent)
        await gateway._on_client_message(client, message)  # immediately again: ignored
        return first, len(sent)

    first, after_spam = asyncio.run(scenario())
    assert first > 0 and after_spam == first
    gateway.clients.pop(client, None)


def test_a_recorded_match_replays_identically(played: tuple[Gateway, Path]) -> None:
    gateway, record = played
    replayed = Gateway()
    asyncio.run(replay_recording(read_recording(record), replayed, speed=0))
    assert [i.id for i in replayed.insights] == [i.id for i in gateway.insights]
    assert [o.overlay_id for o in replayed.overlays] == [o.overlay_id for o in gateway.overlays]
    assert replayed.snapshot == gateway.snapshot

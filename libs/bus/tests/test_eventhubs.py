"""EventHubsBus against fake SDK clients: no network, no Azure account."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pitchmind_bus import eventhubs
from pitchmind_bus.eventhubs import EventHubsBus
from pitchmind_contracts import EventType, MatchEvent, Phase, Topic

OnEvent = Callable[[Any, Any], Awaitable[None]]


def event(i: int, match_id: str = "M7") -> MatchEvent:
    return MatchEvent(id=i, match_id=match_id, t=float(i), minute=0, phase=Phase.FIRST_HALF, type=EventType.FOUL)


class FakeCredential:
    async def close(self) -> None:
        pass


class FakeBatch(list[Any]):
    def __init__(self, partition_key: str) -> None:
        super().__init__()
        self.partition_key = partition_key

    def add(self, item: Any) -> None:  # EventDataBatch.add
        self.append(item)


class FakeProducer:
    sent: list[FakeBatch] = []  # noqa: RUF012 (shared on purpose: collects batches from every instance)
    hubs: list[str] = []  # noqa: RUF012 (one entry per producer created)

    def __init__(self, **kwargs: Any) -> None:
        FakeProducer.hubs.append(kwargs["eventhub_name"])

    async def create_batch(self, partition_key: str) -> FakeBatch:
        return FakeBatch(partition_key)

    async def send_batch(self, batch: FakeBatch) -> None:
        FakeProducer.sent.append(batch)

    async def close(self) -> None:
        pass


class FakeEvent:
    def __init__(self, body: str) -> None:
        self._body = body

    def body_as_str(self) -> str:
        return self._body


def fake_consumer(behaviour: Callable[[OnEvent], Awaitable[None]]) -> type:
    class FakeConsumer:
        def __init__(self, **kwargs: Any) -> None:
            self.group = kwargs["consumer_group"]

        async def __aenter__(self) -> "FakeConsumer":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

        async def receive(self, on_event: OnEvent, starting_position: str) -> None:
            assert starting_position == "@latest"
            await behaviour(on_event)

        async def close(self) -> None:
            pass

    return FakeConsumer


def test_publish_partitions_by_match(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeProducer.sent, FakeProducer.hubs = [], []
    monkeypatch.setattr(eventhubs, "EventHubProducerClient", FakeProducer)

    async def scenario() -> None:
        bus = EventHubsBus("ns.servicebus.windows.net", credential=FakeCredential())
        await bus.publish(Topic.MATCH_EVENTS, event(1, "M7"))
        await bus.publish(Topic.MATCH_EVENTS, event(2, "M9"))
        await bus.close()

    asyncio.run(scenario())
    assert [b.partition_key for b in FakeProducer.sent] == ["M7", "M9"]
    assert FakeProducer.hubs == [Topic.MATCH_EVENTS.value]  # one producer per topic, reused
    assert len(FakeProducer.sent[0]) == 1


def test_received_messages_are_parsed_and_bad_ones_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def deliver(on_event: OnEvent) -> None:
        await on_event(None, FakeEvent("not json"))  # dropped, logged
        await on_event(None, None)  # no event in this callback
        await on_event(None, FakeEvent(event(5).model_dump_json()))
        await asyncio.Event().wait()  # keep receiving until closed

    monkeypatch.setattr(eventhubs, "EventHubConsumerClient", fake_consumer(deliver))

    async def scenario() -> int:
        bus = EventHubsBus("ns.servicebus.windows.net", credential=FakeCredential())
        sub = bus.subscribe(Topic.MATCH_EVENTS, "stats")
        received = await anext(sub)
        await bus.close()
        assert isinstance(received, MatchEvent)
        return received.id

    assert asyncio.run(scenario()) == 5


def test_a_dead_receive_loop_fails_the_stage_instead_of_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M2: a crashed receiver must surface, so Container Apps restarts the stage."""

    async def crash(on_event: OnEvent) -> None:
        raise ConnectionError("unauthorized")

    monkeypatch.setattr(eventhubs, "EventHubConsumerClient", fake_consumer(crash))

    async def scenario() -> BaseException | None:
        bus = EventHubsBus("ns.servicebus.windows.net", credential=FakeCredential())
        sub = bus.subscribe(Topic.MATCH_EVENTS, "stats")
        try:
            with pytest.raises(RuntimeError, match="receive loop stopped") as info:
                await asyncio.wait_for(anext(sub), timeout=2)
            return info.value.__cause__
        finally:
            await bus.close()

    assert isinstance(asyncio.run(scenario()), ConnectionError)

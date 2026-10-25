import asyncio
from collections.abc import AsyncIterator

import pytest
from pitchmind_bus import InMemoryBus, Wire, make_bus
from pitchmind_contracts import EventType, MatchEvent, Phase, Topic


def event(i: int) -> MatchEvent:
    return MatchEvent(id=i, match_id="M1", t=float(i), minute=0, phase=Phase.FIRST_HALF, type=EventType.PHASE_CHANGE)


async def take(messages: AsyncIterator[Wire], n: int) -> list[Wire]:
    out: list[Wire] = []
    async for m in messages:
        out.append(m)
        if len(out) == n:
            break
    return out


def test_every_group_gets_every_message_in_order() -> None:
    async def scenario() -> tuple[list[Wire], list[Wire]]:
        bus = InMemoryBus()
        a, b = bus.subscribe(Topic.MATCH_EVENTS, "a"), bus.subscribe(Topic.MATCH_EVENTS, "b")
        for i in range(5):
            await bus.publish(Topic.MATCH_EVENTS, event(i))
        return await take(a, 5), await take(b, 5)

    got_a, got_b = asyncio.run(scenario())
    assert [m.id for m in got_a if isinstance(m, MatchEvent)] == [0, 1, 2, 3, 4]
    assert got_a == got_b


def test_topics_are_isolated_and_late_subscribers_miss_earlier_messages() -> None:
    async def scenario() -> int:
        bus = InMemoryBus()
        await bus.publish(Topic.MATCH_EVENTS, event(0))  # nobody subscribed yet
        late = bus.subscribe(Topic.MATCH_EVENTS, "late")
        stats = bus.subscribe(Topic.MATCH_STATS, "late")
        await bus.publish(Topic.MATCH_EVENTS, event(1))
        assert bus.pending() == 1
        (only,) = await take(late, 1)
        await bus.close()
        assert await take(stats, 1) == []
        assert isinstance(only, MatchEvent)
        return only.id

    assert asyncio.run(scenario()) == 1


def test_wire_fidelity_delivers_a_parsed_copy() -> None:
    async def scenario() -> tuple[MatchEvent, Wire]:
        bus = InMemoryBus()
        sub = bus.subscribe(Topic.MATCH_EVENTS, "g")
        original = event(3)
        await bus.publish(Topic.MATCH_EVENTS, original)
        (received,) = await take(sub, 1)
        return original, received

    original, received = asyncio.run(scenario())
    assert received == original and received is not original


def test_a_message_being_handled_still_counts_as_busy() -> None:
    async def scenario() -> list[int]:
        bus = InMemoryBus()
        sub = bus.subscribe(Topic.MATCH_EVENTS, "g")
        await bus.publish(Topic.MATCH_EVENTS, event(1))
        seen = [bus.busy()]  # queued
        await anext(sub)
        seen.append(bus.busy())  # taken, handler still working: in flight
        await bus.publish(Topic.MATCH_EVENTS, event(2))
        await anext(sub)  # asking for the next one finishes the first
        seen.append(bus.busy())
        await bus.close()
        await take(sub, 1)  # the stream ends: nothing left in flight
        seen.append(bus.busy())
        return seen

    assert asyncio.run(scenario()) == [1, 1, 1, 0]


def test_make_bus_picks_the_backend_from_the_environment() -> None:
    assert isinstance(make_bus({}), InMemoryBus)
    assert isinstance(make_bus({"BUS_BACKEND": "local"}), InMemoryBus)
    with pytest.raises(ValueError, match="EVENTHUB_NAMESPACE"):
        make_bus({"BUS_BACKEND": "eventhubs"})
    with pytest.raises(ValueError, match="BUS_BACKEND"):
        make_bus({"BUS_BACKEND": "kafka"})


def test_event_hubs_backend_uses_the_fully_qualified_namespace() -> None:
    async def scenario() -> str:
        bus = make_bus({"BUS_BACKEND": "eventhubs", "EVENTHUB_NAMESPACE": "pitchmind-eh-abc123"})
        namespace = str(getattr(bus, "namespace", ""))
        await bus.close()  # nothing was opened: closing must still be clean
        return namespace

    assert asyncio.run(scenario()) == "pitchmind-eh-abc123.servicebus.windows.net"


def test_close_stops_iteration_and_rejects_publishing() -> None:
    async def scenario() -> None:
        bus = InMemoryBus()
        sub = bus.subscribe(Topic.MATCH_EVENTS, "g")
        await bus.close()
        assert await take(sub, 1) == []
        with pytest.raises(RuntimeError, match="closed"):
            await bus.publish(Topic.MATCH_EVENTS, event(1))

    asyncio.run(scenario())

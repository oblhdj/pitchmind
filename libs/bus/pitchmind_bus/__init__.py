"""Message bus: one publish/subscribe interface for every PitchMind service.

Locally the services run in one process on ``InMemoryBus``; in Azure the same code runs
on Event Hubs (one hub per ``Topic``, partition key ``match_id``). Semantics follow Event
Hubs: each *consumer group* receives every message of a topic, in publish order;
subscribers that join later only see what is published after they joined.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping
from typing import Protocol, cast

from pitchmind_contracts import Insight, MatchEvent, MatchMeta, Moment, Overlay, StatSnapshot, Topic, parse_wire

Wire = MatchMeta | MatchEvent | StatSnapshot | Moment | Insight | Overlay


class Bus(Protocol):
    async def publish(self, topic: Topic, message: Wire) -> None: ...

    def subscribe(self, topic: Topic, group: str) -> AsyncIterator[Wire]:
        """Register now (so nothing published after this call is missed) and iterate later."""
        ...

    async def close(self) -> None: ...


_CLOSED = object()


class _Subscription:
    """A consumer's view of one (topic, group) queue.

    A message counts as *in flight* from the moment the consumer takes it until it asks for
    the next one, i.e. while its handler is still working on it (an agent waiting on a model).
    """

    def __init__(self, bus: InMemoryBus, queue: asyncio.Queue[object]) -> None:
        self._bus = bus
        self._queue = queue
        self._holding = False

    def __aiter__(self) -> _Subscription:
        return self

    async def __anext__(self) -> Wire:
        if self._holding:  # the previous message is done
            self._holding = False
            self._bus._in_flight -= 1
        item = await self._queue.get()
        if item is _CLOSED:
            await self._queue.put(_CLOSED)  # let other iterators of the same group stop too
            raise StopAsyncIteration
        self._holding = True
        self._bus._in_flight += 1
        return cast(Wire, item)


class InMemoryBus:
    """In-process bus with Event Hubs semantics.

    ``wire_fidelity`` (default on) serialises every message to JSON and parses it back,
    exactly as it would cross a real broker, so contract problems show up locally.
    """

    def __init__(self, *, wire_fidelity: bool = True) -> None:
        self.wire_fidelity = wire_fidelity
        self._queues: dict[Topic, dict[str, asyncio.Queue[object]]] = defaultdict(dict)
        self._closed = False
        self._in_flight = 0
        self.published: dict[Topic, int] = defaultdict(int)

    async def publish(self, topic: Topic, message: Wire) -> None:
        if self._closed:
            raise RuntimeError("bus is closed")
        self.published[topic] += 1
        for queue in self._queues[topic].values():
            await queue.put(parse_wire(message.model_dump_json()) if self.wire_fidelity else message)

    def subscribe(self, topic: Topic, group: str) -> AsyncIterator[Wire]:
        queue = self._queues[topic].setdefault(group, asyncio.Queue())
        if self._closed:
            queue.put_nowait(_CLOSED)
        return _Subscription(self, queue)

    def pending(self) -> int:
        """Messages published but not yet taken by a consumer."""
        marker = 1 if self._closed else 0  # after close() every queue holds exactly one end-of-stream marker
        return sum(max(0, q.qsize() - marker) for groups in self._queues.values() for q in groups.values())

    def busy(self) -> int:
        """Queued messages plus messages a consumer is still handling: 0 means the pipeline is quiet."""
        return self.pending() + self._in_flight

    async def close(self) -> None:
        self._closed = True
        for groups in self._queues.values():
            for queue in groups.values():
                await queue.put(_CLOSED)


def make_bus(env: Mapping[str, str] | None = None) -> Bus:
    """The bus selected by ``BUS_BACKEND``: ``local`` (default, in-memory) or ``eventhubs``.

    ``eventhubs`` needs ``EVENTHUB_NAMESPACE`` (e.g. ``pitchmind-eh.servicebus.windows.net``)
    and an Entra ID identity (Managed Identity in Azure, ``az login`` locally).
    """
    env = os.environ if env is None else env
    backend = env.get("BUS_BACKEND", "local").strip().lower()
    if backend in ("local", "memory"):
        return InMemoryBus()
    if backend == "eventhubs":
        namespace = env.get("EVENTHUB_NAMESPACE", "").strip()
        if not namespace:
            raise ValueError("BUS_BACKEND=eventhubs needs EVENTHUB_NAMESPACE")
        from .eventhubs import EventHubsBus  # optional dependency: pip install pitchmind-bus[eventhubs]

        return EventHubsBus(namespace if "." in namespace else f"{namespace}.servicebus.windows.net")
    raise ValueError(f"BUS_BACKEND must be 'local' or 'eventhubs', got {backend!r}")


__all__ = ["Bus", "InMemoryBus", "Wire", "make_bus"]

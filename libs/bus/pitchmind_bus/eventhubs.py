"""Azure Event Hubs backend for the bus: one hub per ``Topic``, partition key ``match_id``.

Authentication is Entra ID only (Managed Identity in Azure, ``az login`` locally): no keys
or connection strings anywhere. Each stage reads with its own consumer group, so every
stage sees every message, in order within a match (one match = one partition).

Consumers start at the latest position: a stage that restarts mid-match resumes with new
messages, which is the right trade-off for a live broadcast (no replay storm on restart).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient, PartitionContext
from azure.identity.aio import DefaultAzureCredential
from pitchmind_contracts import Topic, parse_wire

from . import Wire

logger = logging.getLogger(__name__)

_CLOSED = object()


class _Failed:
    """The receive loop died: carried through the queue so the consuming stage fails loudly."""

    def __init__(self, error: BaseException) -> None:
        self.error = error


class _HubSubscription:
    def __init__(self, queue: asyncio.Queue[object]) -> None:
        self._queue = queue

    def __aiter__(self) -> _HubSubscription:
        return self

    async def __anext__(self) -> Wire:
        item = await self._queue.get()
        if item is _CLOSED:
            await self._queue.put(_CLOSED)
            raise StopAsyncIteration
        if isinstance(item, _Failed):
            # Crash the stage instead of idling forever: Container Apps restarts the process.
            raise RuntimeError("Event Hubs receive loop stopped") from item.error
        return cast(Wire, item)


class EventHubsBus:
    def __init__(self, namespace: str, *, credential: Any | None = None) -> None:
        """``namespace`` is the fully qualified name, e.g. ``pitchmind-eh.servicebus.windows.net``."""
        self.namespace = namespace
        self._credential = credential or DefaultAzureCredential()
        self._producers: dict[Topic, EventHubProducerClient] = {}
        self._consumers: list[EventHubConsumerClient] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._queues: list[asyncio.Queue[object]] = []

    def _producer(self, topic: Topic) -> EventHubProducerClient:
        if topic not in self._producers:
            self._producers[topic] = EventHubProducerClient(
                fully_qualified_namespace=self.namespace, eventhub_name=topic.value, credential=self._credential
            )
        return self._producers[topic]

    async def publish(self, topic: Topic, message: Wire) -> None:
        producer = self._producer(topic)
        batch = await producer.create_batch(partition_key=message.match_id)
        batch.add(EventData(message.model_dump_json()))
        await producer.send_batch(batch)

    def subscribe(self, topic: Topic, group: str) -> AsyncIterator[Wire]:
        """Start receiving now (the caller must be inside a running event loop)."""
        queue: asyncio.Queue[object] = asyncio.Queue()
        consumer = EventHubConsumerClient(
            fully_qualified_namespace=self.namespace,
            eventhub_name=topic.value,
            consumer_group=group,
            credential=self._credential,
        )

        async def on_event(_: PartitionContext, event: EventData | None) -> None:
            if event is None:
                return
            try:
                await queue.put(parse_wire(event.body_as_str()))
            except ValueError:
                logger.exception("%s/%s: dropped an unreadable message", topic.value, group)

        async def receive() -> None:
            async with consumer:
                await consumer.receive(on_event=on_event, starting_position="@latest")

        def on_done(task: asyncio.Task[None]) -> None:
            if not task.cancelled() and (error := task.exception()) is not None:
                logger.error("%s/%s: receive loop failed: %r", topic.value, group, error)
                queue.put_nowait(_Failed(error))

        task = asyncio.get_running_loop().create_task(receive())
        task.add_done_callback(on_done)
        self._consumers.append(consumer)
        self._queues.append(queue)
        self._tasks.append(task)
        return _HubSubscription(queue)

    async def close(self) -> None:
        for consumer in self._consumers:
            await consumer.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for producer in self._producers.values():
            await producer.close()
        for queue in self._queues:
            await queue.put(_CLOSED)
        await self._credential.close()

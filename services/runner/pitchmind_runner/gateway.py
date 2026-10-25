"""WebSocket gateway: the live feed for the second-screen app, the overlay page and the studio.

Protocol (the one apps/web speaks in ``mode=live``):

* connect to ``ws://<host>:<port>/ws?segment=<urlencoded segment key>`` (segment optional),
* the server sends one wire-message JSON per frame: a catch-up first (``match_meta``,
  recent ``match_event``s, the latest ``stat_snapshot``, ``moment``s, then this segment's
  ``insight``s and ``overlay``s), then everything live,
* insights and overlays are filtered to the client's segment; everything else goes to all,
* the client may send ``{"type": "subscribe", "segment_key": "..."}`` to switch segment.

In Azure the same frames go out through Web PubSub, with segment keys as groups.

Security: this local server binds to 127.0.0.1, has no authentication and does not check
the ``Origin`` header, so any page open in the same browser could read the (synthetic,
non-sensitive) feed. It is a development server; in Azure, Web PubSub issues per-client
access tokens instead.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import TextIO
from urllib.parse import parse_qs, urlsplit

from pitchmind_bus import Bus, Wire
from pitchmind_contracts import Insight, MatchEvent, MatchMeta, Moment, Overlay, StatSnapshot, Topic
from websockets.asyncio.server import ServerConnection, broadcast

from .stages import Stage, consume

logger = logging.getLogger(__name__)

HISTORY_EVENTS = 300  # recent events sent to a client that joins mid-match


def wants(segment: str | None, message: Wire) -> bool:
    """Does a client watching ``segment`` (None = every segment) get this message?"""
    if isinstance(message, Insight):
        return segment is None or message.segment.key == segment
    if isinstance(message, Overlay):
        return segment is None or message.segment_key == segment
    return True


class Gateway:
    def __init__(self, *, record: Path | None = None) -> None:
        self.meta: MatchMeta | None = None
        self.events: deque[MatchEvent] = deque(maxlen=HISTORY_EVENTS)
        self.snapshot: StatSnapshot | None = None
        self.moments: list[Moment] = []
        self.insights: list[Insight] = []
        self.overlays: list[Overlay] = []
        self.clients: dict[ServerConnection, str | None] = {}
        # Clients still receiving their catch-up: live messages wait here so order is kept.
        self._catching_up: dict[ServerConnection, list[str]] = {}
        self._record: TextIO | None = None
        if record is not None:
            record.parent.mkdir(parents=True, exist_ok=True)
            self._record = record.open("w", encoding="utf-8")

    # ------------------------------------------------------------- state

    def observe(self, message: Wire) -> None:
        """Remember the message for late joiners, record it, and push it to live clients."""
        match message:
            case MatchMeta():
                self._reset(message)
            case MatchEvent():
                self.events.append(message)
            case StatSnapshot():
                self.snapshot = message
            case Moment():
                self.moments.append(message)
            case Insight():
                self.insights.append(message)
            case Overlay():
                self.overlays.append(message)
        text = message.model_dump_json()
        if self._record is not None:
            self._record.write(text + "\n")
            self._record.flush()
        targets: list[ServerConnection] = []
        for ws, segment in self.clients.items():
            if not wants(segment, message):
                continue
            if ws in self._catching_up:
                self._catching_up[ws].append(text)  # sent after the catch-up, in order
            else:
                targets.append(ws)
        if targets:
            broadcast(targets, text)

    def _reset(self, meta: MatchMeta) -> None:
        self.meta = meta
        self.events.clear()
        self.snapshot = None
        self.moments, self.insights, self.overlays = [], [], []

    def catch_up(self, segment: str | None) -> list[Wire]:
        head: list[Wire] = [self.meta] if self.meta else []
        head += list(self.events)
        head += [self.snapshot] if self.snapshot else []
        return head + list(self.moments) + self.segment_history(segment)

    def segment_history(self, segment: str | None) -> list[Wire]:
        personal: list[Wire] = [i for i in self.insights if wants(segment, i)]
        return personal + [o for o in self.overlays if wants(segment, o)]

    def close(self) -> None:
        if self._record is not None:
            self._record.close()
            self._record = None

    # ------------------------------------------------------------- serving

    async def handler(self, ws: ServerConnection) -> None:
        url = urlsplit(ws.request.path if ws.request else "/ws")
        if url.path not in ("/ws", "/"):
            await ws.close(1008, "connect to /ws")
            return
        segment = parse_qs(url.query).get("segment", [""])[0] or None
        logger.info("client connected (%s), %d watching", segment or "all segments", len(self.clients) + 1)
        try:
            await self._send_in_order(ws, segment, self.catch_up(segment))
            async for raw in ws:
                await self._on_client_message(ws, raw)
        finally:
            self.clients.pop(ws, None)
            self._catching_up.pop(ws, None)

    async def _send_in_order(self, ws: ServerConnection, segment: str | None, history: list[Wire]) -> None:
        """Send ``history``, then whatever arrived live meanwhile, then switch the client to live.

        Sending is async, so live messages can arrive mid-history; they are buffered for this
        client instead of being interleaved with older messages.
        """
        self._catching_up[ws] = []
        self.clients[ws] = segment
        for message in history:
            await ws.send(message.model_dump_json())
        buffered = self._catching_up[ws]
        while buffered:  # new messages may arrive while the buffer is flushed
            await ws.send(buffered.pop(0))
        del self._catching_up[ws]

    async def _on_client_message(self, ws: ServerConnection, raw: str | bytes) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            return
        if not isinstance(data, dict) or data.get("type") != "subscribe":
            return
        key = data.get("segment_key")
        segment = key if isinstance(key, str) and key else None
        await self._send_in_order(ws, segment, self.segment_history(segment))

    def run(self, bus: Bus) -> Stage:
        """Subscribe to every topic now; the returned coroutine fans messages out to clients."""

        async def handle(message: Wire) -> None:
            self.observe(message)

        return consume(bus, list(Topic), "gateway", handle)

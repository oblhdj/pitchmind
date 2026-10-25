"""Helpers shared by the command-line tools: environment files, wire files, replay."""

from __future__ import annotations

import codecs
import logging
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from pitchmind_contracts import Insight, Moment, parse_wire

from .service import AgentsService, WireIn

logger = logging.getLogger(__name__)

_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _env_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]  # quoted: taken as is, "#" included
    return raw.split(" #", 1)[0].strip()  # unquoted: a " #" starts a comment


def load_env_file(path: Path) -> None:
    """``KEY=VALUE`` lines (``.env`` style) into the environment; variables already set win.

    Handles the files Windows tools write: UTF-8 with or without BOM and UTF-16 (PowerShell 5
    ``>``), plus ``export KEY=...``, quoted values and comments. Bad lines are skipped with a warning.
    """
    data = path.read_bytes()
    utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    text = data.decode("utf-16" if utf16 else "utf-8-sig")
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.removeprefix("export ").partition("=")
        key = key.strip()
        if not sep or not _ENV_KEY.fullmatch(key):
            logger.warning("%s:%d: skipped, expected KEY=VALUE", path, number)
            continue
        os.environ.setdefault(key, _env_value(value.strip()))


def read_wire(path: Path) -> Iterator[WireIn]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield parse_wire(line)


async def replay(
    service: AgentsService,
    messages: Iterable[WireIn],
    on_insight: Callable[[Insight], None] | None = None,
) -> list[Insight]:
    """Feed messages in order; each insight goes to ``on_insight`` as soon as it is ready."""
    insights: list[Insight] = []
    for msg in messages:
        if not isinstance(msg, Moment):
            await service.handle(msg)
            continue
        produced: list[Insight] = []
        async for insight in service.stream(msg):
            produced.append(insight)
            if on_insight is not None:
                on_insight(insight)
        if produced:
            fallbacks = sum(i.fallback for i in produced)
            slowest = max(i.latency_ms or 0 for i in produced)
            print(f"{msg.id}: {len(produced)} insights, {fallbacks} fallback, {slowest} ms", file=sys.stderr)
        insights.extend(produced)
    return insights

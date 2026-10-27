# Contracts (v1.0)

The single source of truth for every message between services and the frontend.

| Who | Use |
|---|---|
| Python services | `from pitchmind_contracts import MatchEvent, Moment, Insight, ...` |
| Frontend (TS) | `import type { WireMessage, Overlay, ... } from "<path>/contracts/ts"` |
| Anything else | JSON Schemas in `schemas/` |

`pitchmind_contracts/models.py` is the source. `schemas/` and `ts/index.ts` are **generated**. Never edit them by hand:

```powershell
.\.venv\Scripts\python.exe -m pitchmind_contracts.generate
```

## Messages (pipeline order)

| `msg` | Model | Producer → consumer | Topic |
|---|---|---|---|
| `match_meta` | `MatchMeta` | simulator → everyone | `match-events` (first message) |
| `match_event` | `MatchEvent` | simulator / CV → stats engine | `match-events` |
| `stat_snapshot` | `StatSnapshot` | stats engine → moment detector, frontend | `match-stats` |
| `moment` | `Moment` | moment detector → agents | `match-moments` |
| `insight` | `Insight` | agents → render, frontend ("Why?" panel) | `match-insights` |
| `overlay` | `Overlay` | render → overlay page, second-screen app | `match-overlays` → Web PubSub |

Every message has a `msg` field. In TypeScript, `switch (m.msg)` narrows `WireMessage` to the right type.

## Conventions

- **Time:** `t` = seconds of play since kick-off, continuous across both halves (no break). `minute` = broadcast minute. In the first half, `46` means **45+1**.
- **Pitch:** 105 × 68 m. Coordinates are **relative to the acting team, which always attacks towards x = 105**. Flip for drawing when needed.
- **Ids:** players `H10` / `A9`; events are increasing integers; moments `mom-<match>-<n>`.
- **Segments:** `persona|language|club:<home|away|*>|player:<id|*>|metric:<name|*>`, e.g. `casual|ar|club:home|player:*|metric:*`. Overlays carry `segment_key`; a client shows overlays whose key matches its fan profile.
- **Evidence:** every `Claim` must cite ≥ 1 event id. Non-fallback insights must have ≥ 1 claim. `fallback: true` means template text, shown when agents failed. The UI may show a small "auto" badge.
- **RTL:** `overlay.rtl` is true for Arabic. Set `dir="rtl"` on the element.

## Mock stream (for frontend work before the backend exists)

```powershell
.\.venv\Scripts\python.exe tools\mock_stream.py
```

Writes `data/mock/match_meta.json` and `data/mock/stream.jsonl`, a full scripted demo match (143 messages, one JSON per line, sorted by time):

| Minute | What happens |
|---|---|
| 9' | Harbour United score (Halvorsen) |
| 27' | North City pressing surge |
| 33' | Haddad big chance, saved |
| HT | Recap card, 0-1 |
| 58' | Momentum swings to North City |
| 61' | Kaya equalises (Haddad assist) |
| 72' | Arai 35.2 km/h, player-tag stat alert (no LLM) |
| 80' | Match turns chaotic. Analyst insight is a **template fallback** |
| 86' | Haddad winner, 2-1 |
| FT | Recap card |

Segments in the mock: `analyst|en`, `casual|ar|club:home`, `beginner|fr`, and player-focus `casual|en|player:H10`.

To "play" it live in the UI, emit each line when `elapsed × speed ≥ t` (or `show_at` for overlays), e.g. at 20× speed the whole match lasts about 5 minutes.

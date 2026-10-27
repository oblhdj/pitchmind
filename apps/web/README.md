# PitchMind web

One Next.js app (App Router, TypeScript, Tailwind v4) with three routes:

| Route | For | What it shows |
|---|---|---|
| `/` | Fans (second screen) | Score and minute, a broadcast preview with the overlays on air, the personalised insight feed with a **Why?** panel (claims, cited event ids and those events), match stats with a momentum chart, and player focus |
| `/overlay` | Broadcast (OBS/vMix browser source) | Transparent 16:9 graphics for one segment: `lower_third`, `player_tag`, `stat_bubble`, `ticker`, `recap_card`, plus a score bug |
| `/studio` | Producer | Every active segment side by side, each with its own preview, and an **On air / Hold** switch per insight |

The fan's persona, language, club and player build the segment key `persona|lang|club:X|player:Y|metric:*`. Arabic renders right to left (`dir="rtl"`, logical CSS properties), and the whole UI is translated (EN, FR, AR, ES). Template fallbacks (`fallback: true`) carry an **auto** badge. Holding an insight in `/studio` takes its overlay off `/overlay` and `/` in every tab of the same browser.

Wire types are imported from `contracts/ts/index.ts` (generated; never copied).

## Run

```powershell
cd apps/web
npm install
npm run dev          # http://localhost:3000
```

| URL parameter | Routes | |
|---|---|---|
| `mode=mock\|live` | all | Data source (default `mock`, or `NEXT_PUBLIC_FEED_MODE`) |
| `speed=1\|10\|20` | all | Replay speed (default 20×) |
| `from=1650` or `from=27m` | all | Start the replay at a match time |
| `persona`, `lang`, `club`, `player` | `/` | Fan profile, e.g. `?persona=casual&lang=ar&club=home` |
| `segment=<key>` | `/overlay` | The segment to air (URL-encoded) |
| `bug=0`, `debug=1` | `/overlay` | Hide the score bug, show the clock |
| `segments=<key>;<key>` | `/studio` | Live mode: the segments to watch |

Demo moments: 9' goal (`from=550`), 27' pressing surge (`from=1650`), HT recap (`from=2850`), 61' equaliser, 72' speed tag (`from=4485`), 80' template fallback (`from=4990`), 86' winner, FT recap. The scrubber dots in the replay bar jump to each one.

## Data sources (`src/lib/feed.ts`)

- **Mock** (default): replays `data/mock/stream.jsonl` (served by `/api/mock-stream`, baked in at build time) and emits each message when `elapsed × speed ≥ t` (`show_at` for overlays). Every segment is replayed and the views filter, so switching profile is instant. When the replay has no variant for the exact profile, the nearest one is shown and labelled.
- **Live**: `ws://localhost:8765/ws?segment=<urlencoded key>` (override with `NEXT_PUBLIC_LIVE_WS_URL`). One wire message per frame; switching profile sends `{"type":"subscribe","segment_key":"..."}`. Overlays that arrive early wait until the match clock reaches `show_at`; the client reconnects with back-off. Azure Web PubSub can reuse the same frames.

Overlays stay on screen for `duration_s` seconds of wall time, so they remain readable at 20×. Per slot, the highest priority wins.

## Checks

```powershell
npm run lint
npm run typecheck
npm test             # Playwright: unit project (pure logic) + e2e smoke tests
```

The e2e tests start the dev server themselves. On Windows they use the installed Microsoft Edge (`PW_CHANNEL=msedge`), so no browser download is needed; in CI run `npx playwright install --with-deps chromium` first.

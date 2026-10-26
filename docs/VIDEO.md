# Demo video: 3-minute shot list

Base URL: `https://pitchmind-web.mangopebble-6404393d.polandcentral.azurecontainerapps.io`

**Before recording**
- Record at 1920×1080. Second screen: a browser window plus a phone-width window (390 px) for one cut.
- Overlay: `/overlay?segment=...` in its own window (transparent; put it over a pitch image or OBS scene).
- Each `./infra/demo.ps1` switch restarts the agents (about 1 minute): run it off camera, then cut to the result.
- Run `./infra/demo.ps1 restore` at the end.

| Time | Shot | On screen | Voice-over (gist) |
|---|---|---|---|
| 0:00–0:12 | Title | PitchMind logo over the second screen | Live AI commentary that explains *why* a moment matters, for every fan, in their language. |
| 0:12–0:40 | Second screen, EN | `/?persona=analyst&lang=en`: score, live insight, **Why?** open (claims + cited event IDs), pass map | Every claim cites the events behind it; analysts get xG, pressure, the pass map. |
| 0:40–1:00 | Second screen, AR and FR | Switch language to **العربية** (whole page goes right to left), then **Français** + **New to football**; one cut at phone width | Same moment, rewritten per persona and translated by agents. |
| 1:00–1:20 | Overlay | `/overlay` with a lower third sliding in (EN), then the Arabic lower third (RTL) with its xG | Broadcast graphics, timed and throttled: one lower third per 20 s, goals cut in. |
| 1:20–1:45 | Studio | `/studio`: four segments side by side; **Hold** an insight, it leaves the air; the **Audit trail** logs it | A producer stays in control; every decision is logged with time and match minute. |
| 1:45–2:15 | Verifier (`plant`) | After `./infra/demo.ps1 plant`: zoom on a studio card, trace `explain › verifier › explain › verifier` (✓ verified); optionally the agents log line `draft rejected` | We planted a wrong xG in every first draft. The Verifier caught it; fans never saw it. |
| 2:15–2:40 | Recovery (`kill`) | After `./infra/demo.ps1 kill`: zoom on the **AUTO · TEMPLATE** badge, trace ending in `template`; second screen still updating | An agent is down. A verified template takes over; the screen is never empty. |
| 2:40–2:55 | Architecture | README diagram: simulator → stats → moments → agents → render → gateway → web, on Event Hubs + Container Apps | Microsoft Agent Framework + Foundry Phi-4, Event Hubs, Container Apps, Managed Identity: no keys. |
| 2:55–3:00 | Close | Live URL on screen | Try it live: there is always a match on. |

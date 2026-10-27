# PitchMind

**Live AI commentary that explains *why* a moment matters, for every kind of fan, in their language.**
Built for the Microsoft × Premier League **Inside the Game** Developer Hackathon.

PitchMind watches a synthetic football match in real time: a simulator streams events, a stats engine
computes xG, pressure and momentum, and a moment detector picks what matters. A team of agents on
**Microsoft Agent Framework** with **Foundry (Phi-4)** then writes the story: an **Orchestrator** routes
each moment to a writer (Narrative, Explain, Recap), **Persona** adapts it to the fan (analyst, casual,
beginner), **Language** translates it (EN, FR, AR, ES), and a **Verifier** checks every number against the
cited events before anything airs. If an agent fails, a verified template takes over, so the screen is
never empty. It all runs on **Azure Event Hubs** and **Container Apps**, authenticated with **Managed
Identity**: no keys anywhere.

> All match data is **synthetic**. Clubs and players are fictional; no Premier League data is used.

## Live demo

| | |
|---|---|
| Second screen | https://pitchmind-web.mangopebble-6404393d.polandcentral.azurecontainerapps.io |
| Broadcast overlay (1920×1080 browser source) | [/overlay](https://pitchmind-web.mangopebble-6404393d.polandcentral.azurecontainerapps.io/overlay) |
| Producer studio (hold / approve, audit trail) | [/studio](https://pitchmind-web.mangopebble-6404393d.polandcentral.azurecontainerapps.io/studio) |

A match loops forever, so there is always a game on. Pick a style, language, club or player on the
second screen; **Why?** on any insight shows its claims and the event IDs that back them.

## Try the resilience demo

```powershell
./infra/demo.ps1 plant     # each writer's first draft gets a wrong xG: the Verifier rejects it before it airs
./infra/demo.ps1 kill      # an agent goes down: the template takes over, marked AUTO · TEMPLATE in the studio
./infra/demo.ps1 restore   # back to normal
./infra/demo.ps1 status
```

Each switch restarts the agents app and takes about a minute. Watch `/studio`: every insight shows the
agents that handled it (`explain › verifier › explain › verifier` after a rejection, `› template` after a
failure).

## Results

Measured live on Foundry Phi-4, with the match at 4× speed:

| | |
|---|---|
| Rate-limit errors | **0** (71% of model calls before per-model rate limiting) |
| Stale frames from the previous match | **0** |
| Insights written by the AI | **~31 of 37**; the rest used the verified template fallback |
| Moment → insight, p50 | **~41 s** |
| Per-agent p50 | explain 7.2 s · narrative 8.2 s · recap 9.8 s · persona 8.6 s · language 10.2 s |
| Planted wrong numbers (`demo.ps1 plant`) | **6 of 6** rejected by the Verifier; none reached fans |
| Foundry Evals on a full live match | groundedness **4.38/5**, numeric fidelity **1.00** (225 numbers), 3 languages: [details and caveats](docs/EVALS.md) |

## Architecture

```
simulator ─┐            Azure Event Hubs (Standard, Entra ID only)            ┌─ gateway (WebSocket, public)
stats ─────┤   match-events · match-stats · match-moments · match-insights ·   ├─ render
moments ───┤                    match-overlays                                ├─ agents (Agent Framework + Foundry Phi-4)
           └──── one Container App per stage, one image, Managed Identity ────┘
web (Next.js, public, scales to zero) ── wss ──> gateway
```

Each stage is a Container App running the same image; Application Insights collects logs and agent
traces. Render turns insights into timed overlays (at most one lower third per 20 s per segment; goals
cut in). Details and costs: [infra/README.md](infra/README.md). Message formats: [contracts/README.md](contracts/README.md).

## Run locally

Python 3.12 and Node 20+. No Azure needed: the agents run on an offline mock model.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pitchmind_runner --speed 10      # whole pipeline -> ws://127.0.0.1:8765/ws
cd apps/web; npm install; npm run dev                           # http://localhost:3000/?mode=live (+ /overlay, /studio)
```

Without `?mode=live` the web app replays a recorded demo match (`data/mock/stream.jsonl`).
With Foundry: `--llm foundry --env-file .env`. Kill an agent locally with `--disable narrative`.
Checks: `ruff check .`, `mypy`, `pytest`, and in `apps/web` `npm run lint`, `npm run typecheck`, `npx playwright test`.
Deploy your own: `az login`, then `./infra/deploy.ps1`.

## Known limitations

- The always-on demo runs the match at **4× speed** so the agents stay within the Phi-4 quota (20 requests/min).
- Some passes bunch on the goal lines in the pass map: the simulator clamps passes that would leave the pitch.
- The cloud generates **4 audience segments**; any other fan profile gets the closest one (labelled in the app).

## Docs

[Evaluations](docs/EVALS.md) · [Demo video shot list](docs/VIDEO.md) · [Plan](docs/PLAN.pdf) · [Resources](docs/RESOURCES.md) ·
[Team](docs/TEAM.md) · [Datasets & papers](docs/DATASETS_AND_PAPERS.md)

## License

[MIT](LICENSE)

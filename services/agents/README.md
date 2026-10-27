# Agents

Moments in, verified and personalised insights out. Built on **Microsoft Agent Framework** with models from **Microsoft Foundry**.

```
Moment ─▶ Orchestrator ─switch─▶ Explain | Narrative | Recap ─▶ Verifier ─fan-out─▶ one sub-workflow per segment:
                                                                   Persona ─▶ Language* ─▶ Verifier ─▶ Insight
                                                                      ▲                       │ reject (once)
                                                                      └───────────────────────┘
* non-English segments only. Any failure, timeout or second rejection ─▶ template fallback.
```

Each segment runs as its own sub-workflow, so its insight is published as soon as its Verifier passes it; a slow or retrying segment never holds the others back. A moment has a deadline (`PITCHMIND_MOMENT_DEADLINE_S`, 12 s): segments still running then get the template.

| Agent | Role | Model |
|---|---|---|
| Orchestrator | Routes by moment kind; skips stat alerts (speed/distance tags render without an LLM) | code |
| Explain | Why it matters: pressure, momentum, control, big chances | `FOUNDRY_MODEL_STRONG` |
| Narrative | Live commentary: goals, saves, cards, milestones | `FOUNDRY_MODEL_STRONG` |
| Recap | Half-time / full-time recap (context, key moments, standout player, verdict) | `FOUNDRY_MODEL_STRONG` |
| Persona | Analyst / casual / beginner, club perspective, player or metric focus | `FOUNDRY_MODEL_FAST` |
| Language | EN, FR, AR, ES: adapted, not word-for-word | `FOUNDRY_MODEL_FAST` |
| Verifier | Code checks on every draft + optional LLM judge on writer and segment drafts | code (+ fast) |

## Grounding

Agents see only `Facts` built by code from the shared match state: the moment's metrics and evidence, player and team names, score, phase, and earlier key moments for recaps. The Verifier rejects a draft when:

- a claim cites an event id that is not in `moment.evidence`, or names a metric that is not in `moment.metrics`;
- any number in the headline, body or claims is not in the facts. Locale formats are understood (`0,38`, `68 %`, Arabic-Indic digits), and so are number words in EN/FR/ES/AR ("quatre fois sur dix", "treinta y cinco", "خمسة وعشرون"); derived numbers ("4 times out of 10") are rejected. Half names ("second half") and "both" ("les deux équipes") are not counts, and words for one are skipped on their own;
- the text contains markup, a link or control characters;
- there are no claims, a text is empty or too long, or the agent returned `INSUFFICIENT_EVIDENCE`.

Claim metric values are copied from the moment by code, never by the LLM. A rejected draft is retried once with the Verifier's feedback; after that the segment gets `moment.fallback_text` with a localised headline (`fallback: true`), so the overlay never goes blank. With `--judge`, an LLM judge also reviews writer and segment drafts that pass the code checks; if the judge itself is unreachable the code verdict stands (logged and traced).

## Reliability

- **Timeouts and circuit breaker:** each call has `PITCHMIND_AGENT_TIMEOUT_S`. After 3 straight failures an agent's circuit opens for 30 s; then exactly one probe call decides whether it closes again. An unreadable reply (bad JSON) falls back but does not count as an outage.
- **Isolation:** an unexpected error in one step costs only that segment; a failure of the whole workflow still publishes templates for unfinished segments.
- **Redelivery:** the transport is at-least-once. A moment delivered twice replays the insights already published (same ids, so downstream upserts are idempotent) without calling the agents again; a run that was interrupted is processed again. `AgentsService.close_match(match_id)` drops a finished match's state.
- **`agent_trace`** lists only agents that were actually called (a killed agent does not appear); `model` names the deployment that wrote the published text.

## Run

```powershell
# Offline: deterministic mock model, demo match, insights to stdout
.\.venv\Scripts\python.exe -m pitchmind_agents

# Foundry (Entra ID auth: az login locally, Managed Identity in Azure)
.\.venv\Scripts\python.exe -m pitchmind_agents --llm foundry --env-file .env --output data/sim/insights.jsonl

# Failure-recovery demo: kill the Narrative agent
.\.venv\Scripts\python.exe -m pitchmind_agents --disable narrative
```

## Tracing

`--trace foundry` exports OpenTelemetry traces to the Application Insights resource connected to the Foundry project (or `APPLICATIONINSIGHTS_CONNECTION_STRING`), where they show up in Foundry's tracing view. `--trace otlp` follows the standard `OTEL_EXPORTER_OTLP_*` variables (e.g. the Aspire dashboard); `--trace console` prints spans. `--trace-content` adds prompts and replies to the spans (development only).

One moment is one trace:

```
pitchmind.moment            moment id, kind, writer, segments, fallbacks, latency
└─ workflow.run
   ├─ executor.process narrative ─ invoke_agent narrative ─ chat <model> (tokens)
   ├─ executor.process persona_casual_ar_home ─ invoke_agent persona ─ ...
   └─ executor.process verifier_casual_ar_home   events: pitchmind.verifier.rejected, pitchmind.fallback
```

## Evaluations

```powershell
# Offline: numeric fidelity on freshly generated mock insights
.\.venv\Scripts\python.exe -m pitchmind_agents.evals

# Foundry: generate with the real models (saved as they arrive), then score groundedness + fluency in Foundry Evals
.\.venv\Scripts\python.exe -m pitchmind_agents.evals --llm foundry --foundry --segments all --env-file .env --save-insights data/sim/insights.jsonl --markdown docs/EVALS.md

# Score an existing file, e.g. a feed recorded from the deployed gateway (moments and insights in one file)
.\.venv\Scripts\python.exe -m pitchmind_agents.evals --input data/sim/live.jsonl --insights data/sim/live.jsonl --foundry --judge-model Phi-4-mini-instruct --env-file .env
```

Every insight becomes an Agent Framework `EvalItem`: the query names the moment and audience, the response is the headline and body fans see, and the context is the exact `Facts` the agents were given.

| Metric | Provider | What it measures |
|---|---|---|
| `groundedness` | Microsoft Foundry (`builtin.groundedness`) | Is every statement supported by the facts? (1-5, pass/fail from Foundry) |
| `fluency` | Microsoft Foundry (`builtin.fluency`) | Is the text natural and well written? (1-5, pass/fail from Foundry) |
| `numeric_fidelity` | PitchMind (code) | Share of numbers in the text that appear in the facts (0-1). It reuses the Verifier's number parser, so it is a regression check, not independent evidence |

Only insights the agents wrote are scored: a template fallback is fixed text filled in by code. The pipeline table counts every insight: moments (insights of one moment share a writer run, so this is the real sample size), agent-written vs template share, first-pass acceptance, and latency p50/p95 (nearest rank).

The judge is `--judge-model`, else `FOUNDRY_EVAL_MODEL`, else `FOUNDRY_MODEL_STRONG`. Judging on a deployment the live agents do not use keeps it off their quota. The Foundry run gets 30 minutes (`--foundry-timeout`). A run that times out, fails or returns fewer items is listed under **Problem** and the CLI exits 1; errored items count as "No score". A timed-out run keeps going in Foundry: the Problem line gives the `--foundry-run EVAL_ID/RUN_ID` to collect it later with the same `--insights`, instead of paying for a second run. Foundry numbers its result items from 1 and leaves their text empty, so each score is traced back to its insight through the run's data rows; failures and the per-language means in the notes rely on that. Portal links to the run are printed to stderr only, since they contain subscription ids.

As a check, the hand-written insights in `data/mock/stream.jsonl` score 1.00 on numeric fidelity (31/31). Numbers a writer derives rather than reads, such as "4 fois sur 10" from an xG of 0.38 or "12%" from 0.12, are caught (see `test_numeric_fidelity_catches_derived_numbers`); the Verifier rejects such drafts.

## Options

`--segments demo|all|"<key>;<key>"` picks the audience segments (demo = `analyst|en`, `casual|ar|club:home`, `beginner|fr`, player focus `H10`).

| Variable | Default | |
|---|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | | Foundry project endpoint |
| `FOUNDRY_MODEL_STRONG` / `FOUNDRY_MODEL_FAST` | | Model deployments (fast defaults to strong) |
| `PITCHMIND_AGENT_TIMEOUT_S` | `8` | Per-call timeout |
| `PITCHMIND_MOMENT_DEADLINE_S` | `12` | Per-moment deadline; late segments get the template |
| `PITCHMIND_MAX_RETRIES` | `1` | Verifier-driven retries per draft |
| `PITCHMIND_JUDGE` | `0` | LLM judge on writer drafts |
| `PITCHMIND_DISABLED_AGENTS` | | e.g. `narrative,language` |
| `PITCHMIND_MIN_IMPORTANCE` | `0` | Skip moments below this importance |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | | Trace target for `--trace foundry` (else taken from the Foundry project) |
| `FOUNDRY_EVAL_MODEL` | strong model | Judge deployment for Foundry evaluations |

Invalid values stop the CLI with a message naming the variable.

In code: `AgentsService(AgentTeam(clients, config), segments)`. `await service.handle(message)` returns the insights for a wire message; `async for insight in service.stream(moment)` yields each one as soon as it is ready (use this when publishing to Event Hubs). `team.disable(...)` / `team.enable(...)` flip the kill switch at runtime. `pitchmind_agents.testing` has offline helpers (mock match, scripted agents) for tests.

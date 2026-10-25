# Resources – Inside the Game Hackathon

Curated for a 2-day build. **Skim, don't study.** Each item says what to take from it and who on the team needs it (WS1–WS6 from `PLAN.pdf`).

Legend: 🔴 read now · 🟡 skim when you start that part · ⚪ optional / after submission

---

## 0. Verified facts from the official rules

From `OFFICIAL RULES.md` (read on 2026-10-25):

| Fact | Value |
|---|---|
| Deadline | **27 Oct 2026, 11:59 pm Pacific Time = Tue 28 Oct, 07:59 Tunisia time** |
| Team size | Max **4** people |
| Prizes | A project can win at most **one Grand Prize + one Category Prize** |
| Data | Must be synthetic. If you use third-party data or SDKs, you must respect their licenses (Sec. 4.3, 4.7) |
| Code | Must be **newly created** during the hackathon. Open-source libraries are fine if you add new functionality (Sec. 4.3, 4.11) |
| Video | Under 2 min, public (YouTube/Vimeo), no third-party trademarks or copyrighted music |
| Repo | Must be **public** |
| Eligibility | Age of majority; Tunisia is not on the excluded list, but that list is "not limited to". To be 100% sure, ask the sponsor in writing (Sec. 11.6) |

**Prize strategy:** we can win only one category prize, so lead the video and README with **Multi-Agent Orchestration**, our strongest category. We still show Foundry, Cloud Native and Enterprise features, because they also count toward the Grand Prize rubric.

---

## 1. Official hackathon resources

| | Resource | Take from it | Who |
|---|---|---|---|
| 🔴 | [Official GitHub repo](https://github.com/microsoft/insidethegamehackathon) | Only contains rules and playlists. **There is no dataset or starter kit**, so we build our own simulator | All |
| 🔴 | `OFFICIAL RULES.md` | Summarized in section 0 | All |
| 🟡 | `RESOURCE PLAYLISTS.md` → [Foundry](https://aka.ms/asn/foundry), [Foundry Agents](https://aka.ms/asn/foundryagents), [Agentic Workflows](https://aka.ms/asn/agenticworkflows), [Data](https://aka.ms/asn/data), [GitHub Copilot](https://aka.ms/asn/ghcopilot) | Judges come from these product teams, so use their vocabulary in the README | WS3, WS6 |
| ⚪ | Reactor session "Build AI-powered soccer insights apps with AKS and ACA" | Watch at 2× only if you get stuck on Container Apps deployment | WS5 |

## 2. Event Sourcing & CQRS

We use these patterns lightly: an append-only event log plus read models. We don't need a full CQRS framework.

| | Resource | Take from it |
|---|---|---|
| 🟡 | [Microsoft – Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) | 10-min read. Gives the "Azure" wording for the README |
| 🟡 | [Microsoft – CQRS pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs) | Same |
| ⚪ | [Fowler – Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html), [Fowler – CQRS](https://martinfowler.com/bliki/CQRS.html) | Good background, not needed to build |
| ⚪ | [Dennis Doomen – guidelines](https://www.dennisdoomen.com/2020/06/guidelines-event-sourcing.html) | After the hackathon |
| ❌ | Microsoft CQRS Journey | A whole book. **Skip** in 48 h |

## 3. Azure Event Hubs & real-time streaming (WS1, WS5)

| | Resource | Take from it |
|---|---|---|
| 🟡 | [Event Hubs best practices](https://learn.microsoft.com/en-us/azure/well-architected/service-guides/event-hubs) | Partition key = `match_id` (keeps events in order per match); consumer groups per service |
| 🟡 | [Resilient design](https://learn.microsoft.com/en-us/azure/architecture/serverless/event-hubs-functions/resilient-design) | Checkpointing, retries, poison messages → our dead-letter rule |
| ⚪ | [Event Hubs + Functions](https://learn.microsoft.com/en-us/azure/architecture/serverless/event-hubs-functions/event-hubs-functions), [Performance & scale](https://learn.microsoft.com/en-us/azure/architecture/serverless/event-hubs-functions/performance-scale) | Only for the recap Function |
| ➕ | [KEDA Azure Event Hubs scaler](https://keda.sh/docs/latest/scalers/azure-event-hub/) | **Missing from the original list.** This is how Container Apps scale on Event Hubs backlog, a key point for the Cloud Native prize |

## 4. Multi-agent systems (WS3)

| | Resource | Take from it |
|---|---|---|
| 🔴 | [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/) | **Our framework.** Read the Python *workflows* section: sequential, concurrent and handoff orchestration, shared state, checkpointing |
| 🔴 | [Agent Framework GitHub (samples)](https://github.com/microsoft/agent-framework) | Copy the patterns from the Python workflow samples |
| 🟡 | Foundry Agent Service docs (via the Foundry Agents playlist) | Hosting agents in Foundry, tracing |
| ⚠️ | Semantic Kernel agent orchestration ([overview](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/), [sequential](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/sequential), [concurrent](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/concurrent)) | **Concepts only. Don't write SK code.** Agent Framework is the successor to Semantic Kernel + AutoGen and the one named in the prize text. Mixing both wastes time |

How our agents map to orchestration types:
- **Concurrent:** Explain + Narrative run in parallel on one moment
- **Sequential:** → Persona → Language → Verifier
- **Fan-out:** one Persona/Language branch per active segment
- **Handoff / fallback:** Verifier reject → retry once → template

## 5. Evidence-based / grounded generation (WS3)

| | Resource | Take from it |
|---|---|---|
| 🟡 | Microsoft structured outputs guidance (Azure OpenAI in Foundry docs) | Use **JSON-schema structured output**, not "please return JSON" |
| ⚪ | Survey: *Attribution, Citation, and Quotation* – [arXiv:2508.15396](https://arxiv.org/abs/2508.15396) | Cite it in the README to justify the design; don't read it all |
| ⚪ | Fine-grained grounded citations (ACL 2024 Findings) | Same |

**Prompt rule: good. Use it with these three additions:**

> Use only the supplied facts and evidence.
> Every factual claim must include one or more evidence event IDs.
> Do not invent players, statistics, or tactical conclusions.
> If evidence is insufficient, return `"INSUFFICIENT_EVIDENCE"`.
> Return valid JSON only.
> **+ Every number you write must appear verbatim in the supplied metrics.**
> **+ Evidence IDs must come only from the supplied `evidence` list.**
> **+ Write for persona `{persona}` in language `{lang}`; keep player names unchanged.**

Code still has to **enforce** the rule, because prompts alone aren't enough:
- The Verifier checks that every cited ID exists in the input and that every number matches the stats.
- `INSUFFICIENT_EVIDENCE` → publish nothing, or the template fallback. Never show it on screen.

## 6. Football analytics & synthetic data (WS2)

| | Resource | Take from it |
|---|---|---|
| 🔴 | [StatsBomb Open Data](https://github.com/statsbomb/open-data) | **Schema reference only**: event types, fields, 120×80 pitch coordinates. ⚠️ It contains real match data under a license that requires attribution, and the rules demand synthetic data, so **never ship or train on it in the repo**. Copy the *shape*, not the data |
| 🟡 | [socceraction](https://socceraction.readthedocs.io) | **xT (expected threat)** is a great momentum input, and the formula is simple to compute on our own grid. Skip VAEP, which needs training on real data |
| 🟡 | Soccermatics (David Sumpter) | Simple xG logistic model: distance + angle. Exactly what our stats engine needs |
| ⚪ | Sportmonks Pressure Index, Sky Sports advanced stats, Bundesliga Match Momentum (AWS blog) | Inspiration for metric definitions and on-screen naming. Note: the Bundesliga piece is an AWS case study, so **don't name AWS** in our video |

## 7. Azure services, deployment & frontend (WS4, WS5)

| | Resource | Take from it |
|---|---|---|
| 🔴 | Azure for Students | Check **credit balance** and whether your subscription has **model quota in Foundry** *before anything else* |
| 🟡 | [Azure Container Apps docs](https://learn.microsoft.com/en-us/azure/container-apps/) | Deploy, scale rules, managed identity |
| 🟡 | [Azure Web PubSub docs](https://learn.microsoft.com/en-us/azure/azure-web-pubsub/) | Client tokens from the API; groups = segments |
| ➕ | [Azure Developer CLI (azd)](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/) | **Missing from the original list.** `azd up` with Bicep deploys everything in one command, which saves hours on WS5 |
| ⚪ | Cosmos DB, Static Web Apps, Azure Cache for Redis | Standard quickstarts when needed |

## 8. Missing from the original list

| Area | Resource | Why |
|---|---|---|
| Computer vision (WS6) | [Ultralytics YOLO docs](https://docs.ultralytics.com), [Roboflow supervision](https://supervision.roboflow.com) | Detection, ByteTrack tracking and homography helpers for the CV module |
| Foundry evaluations (WS3) | Foundry docs → evaluations + tracing (in the Foundry playlist) | Groundedness/fluency evals and traces are concrete evidence for the "Best Foundry" and "Enterprise" judging |
| Arabic RTL (WS4) | Next.js / CSS `dir="rtl"` + logical properties (`margin-inline-start`) | Arabic layout breaks otherwise |

---

## Reading order (realistic for 48 h)

| When | Who | What | Time |
|---|---|---|---|
| Now | All | Section 0 of this file | 5 min |
| Now | WS5 | Azure for Students credits + Foundry quota | 15 min |
| Now | WS3 | Agent Framework overview + Python workflow samples | 45 min |
| Now | WS2 | StatsBomb event schema (shape only) + Soccermatics xG + xT idea | 30 min |
| When deploying | WS5 | Event Hubs best practices, KEDA scaler, azd | 30 min |
| When building the Verifier | WS3 | Structured outputs guidance + prompt rule above | 15 min |
| After submission | Anyone | Fowler, Doomen, the papers, CQRS Journey | — |

# Team Split – 2 People

Two halves that meet only at `contracts/`. Neither person waits for the other.
Full details of each part: [PLAN.pdf](PLAN.pdf). Reading list: [RESOURCES.md](RESOURCES.md).

**Deadline:** Tue 28 Oct, 07:59 Tunisia time (27 Oct, 11:59 pm PT). **Our target: submit Mon 27 Oct, 23:00.**

---

## 👤 Person A – "The Brain" (Python: data + AI)

Everything from match events to the finished insight.

| What | Workstream | Effort |
|---|---|---|
| Contracts (**together** with Person B) | WS1 | 4 h |
| Match simulator + fictional league + scripted demo match | WS2 | 8 h |
| Stats engine: pass difficulty, speeds, xG, pressure, momentum, control vs chaos | WS2 | 8 h |
| Moment detector: turning points, thresholds, milestones | WS2 | 5 h |
| Agents: Orchestrator, Explain, Narrative, Recap, Persona, Language, Verifier | WS3 | 14 h |
| Render service: insight → timed overlay JSON | WS3 | 3 h |
| **Total** | | **≈ 42 h** |

**Folders:** `contracts/`, `services/simulator/`, `services/stats-engine/`, `services/moment-detector/`, `services/agents/`, `services/render/`, `libs/`

## 👤 Person B – "The Face & the Cloud" (TypeScript + Azure)

Everything from overlay JSON to the screen, plus the infrastructure everything runs on.

| What | Workstream | Effort |
|---|---|---|
| Contracts (**together** with Person A) | WS1 | — |
| **Azure setup first:** Foundry + model quota, Event Hubs, Cosmos DB, Web PubSub, Container Apps, Key Vault | WS5 | 4 h |
| API / BFF (FastAPI: profiles, replay, Web PubSub tokens) | WS1 | 4 h |
| Second-screen app: personas, languages, Arabic RTL, "Why?" button, player-focus mode | WS4 | 10 h |
| Broadcast overlay page + studio dashboard | WS4 | 4 h |
| Bicep + `azd` deploy, CI/CD, App Insights | WS5 | 6 h |
| CV module: short own clip → ball speed event | WS6 | 6 h |
| Video + README polish | WS6 | 6 h |
| **Total** | | **≈ 40 h** |

**Folders:** `apps/web/`, `apps/overlay/`, `services/api/`, `services/cv-eventing/`, `infra/`, `.github/workflows/`

---

## 🤝 The meeting point: `contracts/`

1. **Together, now (≈ 1 h):** agree on `MatchEvent`, `StatUpdate`, `Moment`, `Insight`, `Overlay`, `FanProfile`, `MatchMeta`.
2. A **mock overlay stream** (`data/mock/overlays.jsonl`) is generated from the contracts, so Person B builds the UI before the backend exists.
3. After M1, **nobody changes `contracts/` without telling the other.**

---

## 🕒 Shared timeline (Tunisia time)

| When | Person A | Person B | Together |
|---|---|---|---|
| **Sat now → 14:00** | Draft contracts | **Create Azure resources, check Foundry quota** | ✅ **M1** – contracts frozen |
| **Sat 14:00 → Sun 02:00** | Simulator → stats → moments → agents | API + second-screen app on mock data + overlay page | Sync call ~20:00 |
| **Sun 02:00** | | | ✅ **M2** – full pipeline runs locally |
| **Sun 08:00 → 18:00** | Recaps, Verifier, Foundry evals, failure-recovery demo | Deploy all to Azure, studio dashboard, CV module | ✅ **M3** – live on Azure |
| **Sun 18:00 → 23:00** | Agent quality + latency fixes | Load test, UI bug fixes | ✅ **M4** – feature freeze |
| **Mon 27 Oct** | README: agents + architecture sections | Record + edit video | ✅ **M5** 18:00 repo public · **M6** 23:00 submitted |

---

## ✂️ If time runs short, cut in this order

1. CV module (one clip only, or skip)
2. Studio dashboard
3. Spanish (keep EN, FR, AR)
4. Redis (use in-process cache)

**Never cut:** the 5 pipeline stages, evidence citations, the 3 personas, the Azure deployment, the video.

---

## 📏 Working rules

- **Own folders only.** Person A: `services/*` (except `api`, `cv-eventing`), `contracts/`, `libs/`. Person B: `apps/*`, `infra/`, `services/api`, `services/cv-eventing`.
- **Branches:** Person A works on `brain/<topic>`, Person B on `face/<topic>`. Merge to `main` at every milestone (or sooner if the other person needs it).
- **Pull before you start, push small commits often.**
- **Never commit `.env`, keys or passwords.** Use `.env.example` as the template.
- **Commit messages:** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`).
- **Blocked for more than 30 min?** Tell the other person immediately.

### Daily git routine

```powershell
git checkout main
git pull
git checkout -b brain/simulator      # or face/web-shell
# ... work ...
git add .
git commit -m "feat(simulator): possession state machine"
git push -u origin brain/simulator
# when ready to merge:
git checkout main
git pull
git merge brain/simulator
git push
```

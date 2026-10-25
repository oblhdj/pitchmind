# Datasets & Papers – Inside the Game Hackathon

Found online on 2026-10-25, to add to [RESOURCES.md](RESOURCES.md). Items RESOURCES.md already covers (StatsBomb, socceraction, Soccermatics, Ultralytics, supervision, arXiv:2508.15396) are not repeated here.

Legend: 🔴 use now · 🟡 use when you reach that part · ⚪ cite in the README only

---

## 0. The data rule decides what we can use

Official rules, Sec. 4.7: *"Projects must use synthetic, football-realistic data."* Sec. 4.3: any third-party data must be used under its license.

| Tier | What | What we may do with it |
|---|---|---|
| **A. Synthetic** | Generated data (ours or someone else's) | Ship it, train on it, demo it |
| **B. Real, openly licensed** | Real match data and footage | Read the **schema** and the **docs**. At most, run a local sanity check that is never committed. **Never** ship it, demo it, or train a shipped model on it |
| **C. Papers** | Formulas and published summary numbers | Copy formulas, calibrate constants on published numbers, cite them |

Safest path: calibrate the simulator on **numbers from papers (tier C)**, so no real data ever touches the repo.

---

## 1. Datasets

### A. Synthetic, usable directly

| | Dataset | What it is | License | Take from it | Who |
|---|---|---|---|---|---|
| 🔴 | **Our own simulator output** | `pitchmind_simulator` JSONL export | MIT (ours) | Rules Sec. 4.1(v) explicitly asks to *"create or extend synthetic football-realistic datasets"*. Promote "publish the dataset" from STRETCH to MUST: a `data/datasets/` folder with a few seeds and a short datasheet (fields, seeds, calibration sources below) | A |
| 🟡 | [SoccerSynth-Detection](https://github.com/open-starlab/SoccerSynth-Detection) ([paper, arXiv:2501.09281](https://arxiv.org/abs/2501.09281)) | Synthetic images for soccer **player** detection, with random lighting, textures and motion blur. Tested with YOLOv8n | Code Apache-2.0; the **dataset license is not stated** (download is a Google Drive link) | Only if we need player detection in the CV module. Fine-tune YOLO on synthetic images instead of real broadcast frames. For **ball speed**, the pretrained COCO `sports ball` class on our own clip is enough | B (WS6) |
| ⚪ | [SoccerSynth Field](https://arxiv.org/abs/2503.13969) | Same group, synthetic pitch / field-line detection | Not checked | Cite only; we use a manual 4-point homography | B |
| ⚪ | [Google Research Football](https://github.com/google-research/football) ([AAAI 2020](https://arxiv.org/abs/1907.11180)) | 3D physics football simulator for RL | Apache-2.0, **archived (read-only) since Aug 2026** | Too heavy for 48 h. Cite as prior art for synthetic football | — |
| ⚪ | [SoccER](https://www.sciencedirect.com/science/article/pii/S2352711020303253) (2020) | Synthetic event + position generator built on the Gameplay Football engine | MIT | Same: prior art only | — |

### B. Real data: schema and sanity reference only (never commit)

| | Dataset | What it is | License / terms | Take from it | Who |
|---|---|---|---|---|---|
| 🟡 | [Wyscout public dataset](https://figshare.com/collections/Soccer_match_event_dataset/4415000) ([Pappalardo et al. 2019, *Scientific Data*](https://pmc.ncbi.nlm.nih.gov/articles/PMC6817871/)) | Full-season event logs, 7 competitions incl. Premier League 2017/18 | **CC BY 4.0** | The best source for event-rate sanity: passes, shots and fouls per match, pass accuracy. Compute locally, keep only the summary numbers | A |
| 🟡 | [SkillCorner Open Data](https://github.com/SkillCorner/opendata) | 10 A-League 2024/25 matches: broadcast tracking, *dynamic events*, *phases of play*, physical aggregates | Repo MIT; README asks to credit SkillCorner | The **phases-of-play** labels are a ready vocabulary for "control vs chaos". Physical aggregates give speed and distance ranges | A |
| 🟡 | [Metrica Sports sample data](https://github.com/metrica-sports/sample-data) | 3 anonymized games, tracking + events | **No formal license**: "be responsible… acknowledge the source" | What synced tracking + events look like. Read only | A, B (WS6) |
| ⚪ | [IDSSE / Sportec Open Bundesliga](https://pmc.ncbi.nlm.nih.gov/articles/PMC11787359/) (Bassek et al. 2025, *Scientific Data*) | 7 Bundesliga matches, official event + position data | **CC BY 4.0**; loader in [floodlight](https://floodlight.readthedocs.io/en/latest/modules/io/datasets.html) | Official DFL event definitions if a field name is unclear | A |
| ⚪ | [PFF FC World Cup 2022](https://www.blog.fc.pff.com/blog/enhanced-2022-world-cup-dataset) | 64 matches, events + tracking | **Terms not verified** (sign-up form) | Skip | — |
| ⚪ | [SoccerNet-Echoes](https://arxiv.org/abs/2405.07354) | Whisper transcripts of commentary for 550 games, 10 languages | **No license** on the repo | Read a few lines to hear real commentary tone per language. Don't ship | A (WS3) |

**Code that is fine to use** (code, not data): [kloppy](https://github.com/PySport/kloppy) (BSD-3, loads all the providers above into one model) and [roboflow/sports](https://github.com/roboflow/sports) (MIT, pitch keypoints + `ViewTransformer` homography + radar view, useful for WS6). The Roboflow Universe **datasets** linked from that repo are real broadcast frames, so don't train on them.

---

## 2. Papers

### WS2 – Simulator and stats engine

| | Paper | Take from it | Where it lands |
|---|---|---|---|
| 🔴 | Andrienko et al. 2017, *Visual Analysis of Pressure in Football*, Data Mining & Knowledge Discovery 31(6) ([open PDF](https://openaccess.city.ac.uk/id/eprint/17464/1/VAofPressing.pdf)) | A defined pressure model: pressure exerted by defenders on the ball carrier and on opponents, then aggregated into team pressing | `under_pressure` rule in the simulator; pressure index in the stats engine. Cite it in the docstring |
| 🔴 | Karun Singh, [*Introducing Expected Threat (xT)*](https://karun.in/blog/expected-threat.html) (blog, 2018) | 16×12 grid, value of moving the ball between zones. Implemented in socceraction (`socceraction.xthreat`) | Compute xT on **our synthetic** events. Then momentum = EWMA of xT gained |
| 🔴 | The Analyst (Stats Perform), [*What is match momentum?*](https://theanalyst.com/articles/what-is-match-momentum) | Each minute, compares each team's most threatening recent actions. Only the last ~3–4 minutes matter. Values are capped and smoothed | Validates our EWMA design. Use a 3–4 minute window and cap single actions so one shot doesn't swing the whole graph |
| 🟡 | Robberechts, Van Haaren, Davis, *A Bayesian Approach to In-Game Win Probability in Soccer*, KDD 2021 ([arXiv:1906.05029](https://arxiv.org/abs/1906.05029)) | Live win/draw/loss probability from score, time left and context | **Turning point = big swing in win probability.** Easy, explainable, great for the "Why?" button |
| 🟡 | Dixon & Coles 1997, *Modelling Association Football Scores…*, JRSS Series C 46(2) | The standard Poisson goal model | A cheap win-probability baseline: Poisson goals remaining from the current xG rate × minutes left |
| 🟡 | Martins et al. 2020, *Node and Network Entropy…*, Mathematics 8(9) ([open, CC BY 4.0](https://doi.org/10.3390/math8091543)) | Transition entropy of passing sequences (Markov chain). Higher entropy = less predictable play | Gives a paper behind the "event entropy" part of control vs chaos |
| 🟡 | Robberechts & Davis 2020, *How Data Availability Affects the Ability to Learn Good xG Models* ([blog](https://dtai.cs.kuleuven.be/sports/blog/how-data-availability-affects-the-ability-to-learn-good-xg-models), [repo](https://github.com/ML-KULeuven/soccer_xg)) | A simple feature set (location, header vs foot) with logistic regression is a solid baseline. Complex models need ~5 seasons of data | Justifies our hand-calibrated distance + angle model in `football.py` |
| 🟡 | Bradley et al. 2009, *High-intensity running in English FA Premier League soccer matches*, J. Sports Sci. 27(2) | High-intensity running per match by position (wide mid ~3.1 km … centre-back ~1.8 km). About **20 % less in the last 15 min** than the first 15 | Fatigue curve and per-position running in the simulator |
| 🟡 | Premier League [top-speed news](https://www.premierleague.com/news/4025726) | Season peaks around 35–37 km/h | Our `ORGANIC_SPRINT_CAP_KMH = 34.5` is realistic. Scripted sprints above it will read as "record" moments |
| ⚪ | Power, Ruiz, Wei, Lucey, *Not All Passes Are Created Equal*, KDD 2017 | Risk and reward of a pass, from tracking data | Our `pass_difficulty` is a hand-weighted version of the "risk" side. Cite it |
| ⚪ | Decroos et al., *Actions Speak Louder than Goals* (VAEP), KDD 2019 ([arXiv:1802.07127](https://arxiv.org/abs/1802.07127)) | Values every action by its effect on scoring and conceding | Cite only. VAEP needs training on real data |
| ⚪ | Spearman 2018, *Beyond Expected Goals*, MIT Sloan | Pitch control + off-ball scoring opportunity (OBSO) | Cite only, needs full tracking |
| ⚪ | Mendes-Neves et al. 2024, *Towards a Foundation Large Events Model for Soccer*, Machine Learning ([Springer](https://link.springer.com/article/10.1007/s10994-024-06606-y)) | Simulates matches by predicting the next event like an LLM predicts tokens | Our simulator is the hand-built version of this. Good README line |
| ⚪ | Wang et al. 2024, *TacticAI*, Nature Communications 15:1906 ([DeepMind blog](https://deepmind.google/discover/blog/tacticai-ai-assistant-for-football-tactics/)) | AI assistant for corner kicks, built with Liverpool FC | README framing only |

**Not found:** a reliable study of average **shot speed** in km/h. Keep the simulator's range plausible, and don't print a "league average shot speed" on screen as if it were a fact.

### WS3 – Agents, grounding and the Verifier

| | Paper | Take from it | Where it lands |
|---|---|---|---|
| 🔴 | Thomson & Reiter 2020, *A Gold Standard Methodology for Evaluating Accuracy in Data-to-Text Systems*, INLG ([arXiv:2011.03992](https://arxiv.org/abs/2011.03992)) + the [Accuracy Evaluation Shared Task results](https://arxiv.org/abs/2108.05644) (2021) | Built on **sports** game summaries. Annotators label specific errors by category instead of scoring "accuracy" on a scale. Key result: automatic checkers **miss errors that come from wrong computation or inference** | Exactly why the Verifier checks numbers **in code**, not only with an LLM judge. Report Verifier rejections **per error category** in the Foundry custom eval |
| 🔴 | Cemri et al., *Why Do Multi-Agent LLM Systems Fail?*, NeurIPS 2025 D&B ([arXiv:2503.13657](https://arxiv.org/abs/2503.13657)) | MAST: 14 failure modes in 3 groups (design/specification, inter-agent misalignment, task verification), from 1,600+ annotated traces | Name which MAST failures our design guards against (Verifier = task verification, retry + template = recovery). Strong material for **Best Multi-Agent** |
| 🟡 | Dhuliawala et al., *Chain-of-Verification Reduces Hallucination in LLMs*, Findings of ACL 2024 ([arXiv:2309.11495](https://arxiv.org/abs/2309.11495)) | Draft → write verification questions → answer them without seeing the draft → revise | The pattern for the Verifier's LLM-judge step |
| 🟡 | Qi et al. 2023, *GOAL: Knowledge-grounded Video Captioning for Real-time Soccer Commentary* ([arXiv:2303.14655](https://arxiv.org/abs/2303.14655), [repo BSD-3](https://github.com/THU-KEG/goal)) | Labels each commentary sentence as **scene description**, **background** or **comment** | A clean split of jobs: Explain = scene + comment with evidence; Narrative = background. Copy the taxonomy, not the data |
| ⚪ | Rao et al., *Multi-Agent System for Comprehensive Soccer Understanding* (SoccerAgent, SoccerWiki, SoccerBench) ([arXiv:2505.03735](https://arxiv.org/abs/2505.03735)) | The closest prior work: a multi-agent system for soccer Q&A over a knowledge base | README "related work": they answer questions, we explain live moments with cited evidence |
| ⚪ | Rao et al., *MatchTime: Towards Automatic Soccer Game Commentary Generation*, EMNLP 2024 ([arXiv:2406.18530](https://arxiv.org/abs/2406.18530)) | Found that commentary is often **misaligned in time** with the video, and fixed it | README: our `show_at` scheduling and latency budget address the same problem |

---

## 3. What to do with this in the next 48 h

1. **[A, WS2]** Set the simulator constants from tier C: Andrienko for `under_pressure`, Bradley for fatigue (−20 % in the last 15'), PL top speeds for sprints. One-line citations in the docstrings.
2. **[A, WS2]** Add xT (16×12) on synthetic events. Momentum = EWMA of xT gained over 3–4 minutes, with a cap per action.
3. **[A, WS2]** Turning point = win-probability swing (Poisson goals-remaining model). It gives a plain-language number for the "Why?" button.
4. **[A, WS3]** Verifier error categories in the style of Thomson & Reiter. Report counts per category in the Foundry numeric-fidelity eval.
5. **[A, WS2]** Publish 3–5 seeds as a synthetic dataset with a short datasheet (Rules Sec. 4.1(v)).
6. **[B, WS6]** CV: pretrained YOLO `sports ball` on our own clip + roboflow/sports homography code. SoccerSynth-Detection only if we need players.
7. **[Both, Mon]** README "Related work": SoccerAgent, MatchTime, GOAL, MAST, TacticAI, LEM. Five lines, no more.

## 4. Not verified

- The license of the SoccerSynth-Detection **dataset** files (only the code is Apache-2.0).
- PFF FC data terms; SoccerNet-Echoes and SoccerAgent have no license file.
- Exact speed thresholds in Bradley et al. 2009 (the abstract doesn't state them).
- MatchTime benchmark numbers, which come from secondary summaries. Don't quote them.

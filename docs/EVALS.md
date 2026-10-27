# Evaluations

One full match exactly as the live system played it, scored afterwards with Microsoft Foundry Evals
and our own numeric check.

**The match.** Match `M058`, recorded from the deployed gateway on 27 Oct 2026, 17:00–17:28 UTC: every
message from kick-off to the next kick-off, in arrival order, with no dropped connection
([data/evals/live-match-M058.jsonl](../data/evals/live-match-M058.jsonl)). The agents ran as always: Foundry
Phi-4 at 12 requests/min, moments of importance 0.5 and above, match at 4× speed, four audience segments
(analyst · English, casual · Arabic · home club, beginner · French, casual · English following player H10).

**The judges.** Foundry's built-in `groundedness` (is every statement supported by the facts the agents
were given?) and `fluency`, judged by **Phi-4-mini-instruct**, a separate deployment, so judging took no
quota from the live demo. `numeric_fidelity` is our check: every number fans read must appear in the facts.

**What is scored.** The 54 insights the agents wrote. The 10 template fallbacks are fixed text filled in by
code, so they count only in the pipeline table.

## Results

| Metric | Provider | Scale | Mean score | Passed | No score |
|---|---|---|---|---|---|
| numeric_fidelity | PitchMind | 0-1 | 1.00 | 54/54 | 0 |
| groundedness | Microsoft Foundry | 1-5 | 4.38 | 38/54 | 12 |
| fluency | Microsoft Foundry | 1-5 | 3.16 | 31/54 | 17 |

| By language | Arabic | English | French |
|---|---|---|---|
| numeric_fidelity | 1.00 (n=15) | 1.00 (n=23) | 1.00 (n=16) |
| groundedness | 4.36 (n=14) | 4.19 (n=16) | 4.67 (n=12) |
| fluency | 3.00 (n=10) | 3.18 (n=17) | 3.30 (n=10) |

| Pipeline | Value |
|---|---|
| Moments with an insight | 19 |
| Insights | 64 |
| Written by the agents | 54 (84%) |
| Template fallback | 10 (16%) |
| Accepted by the Verifier on the first pass | 62% |
| Moment → insight, p50 / p95 | 28 s / 47 s |

## Reading the numbers

**Groundedness 4.38 / 5.** 38 of the 42 scored insights pass. The 4 failures:

- **A real miss.** The English half-time recap (`ins-M058-ba591b-11-analyst_en`) says Harbour United
  "Clinches Win at HT" (a 1–0 lead at half-time is not a win) and "North City's 47 attempts" (47 is the minute;
  North City had 13 shots). Every number in it exists somewhere in the facts, so the Verifier's number check
  passed it. Only an LLM judge sees that a number is attached to the wrong thing, and the Verifier's own LLM
  judge (`PITCHMIND_JUDGE`) is off in the live deployment to stay within the 20 requests/min quota.
- The Arabic version of the same half-time recap (`…-11-casual_ar_home`).
- **A judge error.** `…-3-casual_ar_home` failed because, in the judge's words, the response "is in English,
  not Modern Standard Arabic". It is in Arabic.
- `…-18-casual_en_h10`: the judge faults it for leaving out details from the facts. Omitting a fact is not
  the same as stating an unsupported one.

**Fluency 3.16 / 5.** 31 of the 37 scored insights pass. The judge describes all 6 failures as "simple",
"clear" or "grammatically correct": Foundry's fluency rubric rewards varied vocabulary and complex sentences,
while a lower third is short on purpose. Read it as "no broken language", not as a quality ranking.

**No score.** For 12 (groundedness) and 17 (fluency) of the 54 insights the small judge model returned no
usable score; they are counted, not dropped. A GPT-class judge would give firmer numbers. Phi-4-mini is what
our subscription offers next to the Phi-4 the agents use.

**Numeric fidelity 1.00.** All 225 numbers fans read appear in the facts, in all three languages. It reuses
the Verifier's number parser, so it confirms that nothing slipped past the Verifier rather than giving
independent evidence, and, as the half-time recap shows, it cannot tell whether a number describes the right
thing.

**Sample size.** The 3–4 insights of one moment share one writer run, so the real sample is 19 moments, not 64
insights.

**Latency.** p50 28 s from moment to insight, bounded by the Phi-4 quota (20 requests/min shared by every
agent call). Speed and distance tags skip the agents and reach the screen within 2 s.

## What we did not use

We first regenerated insights offline with Phi-4 while the live demo was running. Sharing the deployment's
20,000 tokens/min made 22 of 32 insights fall back to templates: that measured the quota, not the system, so
we scored the live match instead.

## Reproduce

```powershell
# Numeric fidelity and pipeline numbers: offline, no Azure needed
.\.venv\Scripts\python.exe -m pitchmind_agents.evals --input data/evals/live-match-M058.jsonl --insights data/evals/live-match-M058.jsonl

# Plus the Foundry judges (az login and a Foundry project in .env)
.\.venv\Scripts\python.exe -m pitchmind_agents.evals --input data/evals/live-match-M058.jsonl --insights data/evals/live-match-M058.jsonl --foundry --judge-model Phi-4-mini-instruct --env-file .env
```

How the scoring works: [services/agents/README.md](../services/agents/README.md#evaluations).

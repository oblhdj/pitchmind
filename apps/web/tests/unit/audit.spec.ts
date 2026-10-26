/** The studio audit trail: what each hold / approve logs, newest first. Runs without a browser. */
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { appendAudit, AUDIT_LIMIT, decisionEntry, releaseEntry, type AuditEntry } from "../../src/lib/audit";
import type { Insight } from "../../src/lib/contracts";
import { parseStream } from "../../src/lib/feed";

const STREAM = readFileSync(path.resolve(__dirname, "../../../../data/mock/stream.jsonl"), "utf-8");
const INSIGHTS = parseStream(STREAM)
  .map((i) => i.msg)
  .filter((m): m is Insight => m.msg === "insight");

test("a decision logs wall clock, match minute, segment, insight and action", () => {
  const insight = INSIGHTS[0] as Insight;
  const at = Date.UTC(2026, 9, 26, 20, 15, 0);
  expect(decisionEntry(insight, "held", { minute: 61, phase: "second_half" }, at)).toEqual({
    at,
    minute: 61,
    phase: "second_half",
    action: "held",
    insightId: insight.id,
    headline: insight.headline,
    segment: insight.segment.key,
  });
  expect(releaseEntry(3, null, at)).toEqual({ at, minute: null, phase: null, action: "released_all", count: 3 });
});

test("the log is newest first, never mutated, and capped", () => {
  const [a, b] = INSIGHTS as [Insight, Insight];
  const first = appendAudit([], decisionEntry(a, "held", null, 1));
  const log = appendAudit(appendAudit(first, decisionEntry(b, "held", null, 2)), decisionEntry(a, "approved", null, 3));
  expect(log.map((e) => [e.at, e.action])).toEqual([
    [3, "approved"],
    [2, "held"],
    [1, "held"],
  ]);
  expect(first).toHaveLength(1);

  const full = Array.from({ length: AUDIT_LIMIT + 5 }, (_, i) => releaseEntry(1, null, i)).reduce<AuditEntry[]>(
    (acc, entry) => appendAudit(acc, entry),
    [],
  );
  expect(full).toHaveLength(AUDIT_LIMIT);
  expect(full[0]?.at).toBe(AUDIT_LIMIT + 4); // the newest stays
  expect(full.at(-1)?.at).toBe(5); // the oldest five dropped off
});

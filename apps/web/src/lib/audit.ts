"use client";

/**
 * The studio's audit trail: every hold / approve decision with the wall-clock time, the match
 * minute, the segment and the insight, newest first. Session memory only (no backend), shared
 * live with the other studio tabs of this browser, like the holds themselves.
 */
import { useSyncExternalStore } from "react";

import type { Decision } from "./approvals";
import type { Insight, Phase } from "./contracts";

interface AuditBase {
  /** Wall clock, ms since the epoch. */
  at: number;
  /** Match minute when the producer acted; null before kick-off. */
  minute: number | null;
  phase: Phase | null;
}

export type AuditEntry =
  | (AuditBase & { action: Decision; insightId: string; headline: string; segment: string })
  | (AuditBase & { action: "released_all"; count: number });

/** An entry once logged: its id is unique across tabs (React key, de-duplication). */
export type LoggedEntry = AuditEntry & { id: string };

export type MatchClock = { minute: number; phase: Phase } | null;

/** Older entries drop off past this many. */
export const AUDIT_LIMIT = 200;

/** A hold or approve of one insight. */
export function decisionEntry(insight: Insight, action: Decision, clock: MatchClock, at: number): AuditEntry {
  return {
    at,
    minute: clock?.minute ?? null,
    phase: clock?.phase ?? null,
    action,
    insightId: insight.id,
    headline: insight.headline,
    segment: insight.segment.key,
  };
}

/** "Release all holds": `count` held insights went back on air. */
export function releaseEntry(count: number, clock: MatchClock, at: number): AuditEntry {
  return { at, minute: clock?.minute ?? null, phase: clock?.phase ?? null, action: "released_all", count };
}

/** `log` with `entry` on top (newest first), capped at `limit` entries. */
export function appendAudit<T extends AuditEntry>(log: readonly T[], entry: T, limit = AUDIT_LIMIT): T[] {
  return [entry, ...log].slice(0, limit);
}

const CHANNEL = "pitchmind-audit";
const ACTIONS: ReadonlySet<string> = new Set(["held", "approved", "released_all"] satisfies AuditEntry["action"][]);
const TAB = Math.random().toString(36).slice(2, 10);
const EMPTY: readonly LoggedEntry[] = [];

let log: readonly LoggedEntry[] = EMPTY;
let logged = 0;
const listeners = new Set<() => void>();
let channel: BroadcastChannel | null = null;

function add(entry: LoggedEntry): void {
  if (log.some((e) => e.id === entry.id)) return;
  log = appendAudit(log, entry);
  for (const listener of listeners) listener();
}

/** Log a decision here and in the other studio tabs. */
export function recordAudit(entry: AuditEntry): void {
  logged += 1;
  const entryWithId: LoggedEntry = { ...entry, id: `${TAB}-${logged}` };
  add(entryWithId);
  channel?.postMessage(entryWithId);
}

function onMessage(event: MessageEvent<unknown>): void {
  const data = event.data;
  if (typeof data !== "object" || data === null) return;
  if (!("id" in data && typeof data.id === "string" && "action" in data && typeof data.action === "string")) return;
  if (ACTIONS.has(data.action)) add(data as LoggedEntry);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    try {
      channel = new BroadcastChannel(CHANNEL);
      channel.onmessage = onMessage;
    } catch {
      channel = null;
    }
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      channel?.close();
      channel = null;
    }
  };
}

/** The studio's decisions, newest first. */
export function useAuditLog(): readonly LoggedEntry[] {
  return useSyncExternalStore(subscribe, () => log, () => EMPTY);
}

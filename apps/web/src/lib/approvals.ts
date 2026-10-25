"use client";

/**
 * Human in the loop: the studio can hold an insight so it never reaches air. Decisions are
 * kept in localStorage and broadcast to every tab of the app (overlay, second screen), so a
 * producer holding an insight in /studio takes it off /overlay at once. Default: approved.
 */
import { useSyncExternalStore } from "react";

export type Decision = "approved" | "held";

const STORAGE_KEY = "pitchmind:held";
const CHANNEL = "pitchmind-approvals";
const EMPTY: ReadonlySet<string> = new Set();

let held: ReadonlySet<string> | null = null;
const listeners = new Set<() => void>();
let channel: BroadcastChannel | null = null;

function read(): ReadonlySet<string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const ids: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

function refresh(): void {
  held = read();
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    window.addEventListener("storage", onStorage);
    try {
      channel = new BroadcastChannel(CHANNEL);
      channel.onmessage = refresh;
    } catch {
      channel = null;
    }
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener("storage", onStorage);
      channel?.close();
      channel = null;
    }
  };
}

function onStorage(event: StorageEvent): void {
  if (event.key === STORAGE_KEY) refresh();
}

function snapshot(): ReadonlySet<string> {
  held ??= read();
  return held;
}

export function setDecision(insightId: string, decision: Decision): void {
  const next = new Set(snapshot());
  if (decision === "held") next.add(insightId);
  else next.delete(insightId);
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
  } catch {
    // Private mode: the decision still applies to this tab.
  }
  held = next;
  channel?.postMessage("changed");
  for (const listener of listeners) listener();
}

export function clearDecisions(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  held = new Set();
  channel?.postMessage("changed");
  for (const listener of listeners) listener();
}

/** Ids of the insights currently held by the studio. */
export function useHeld(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, snapshot, () => EMPTY);
}

/**
 * Wire types generated from the Python contracts (`contracts/ts/index.ts`).
 * Import them from here; never copy them by hand.
 */
export type {
  AgentName,
  Claim,
  EventType,
  Insight,
  InsightKind,
  Language,
  MatchEvent,
  MatchMeta,
  MetricName,
  Moment,
  MomentKind,
  Overlay,
  OverlayMetric,
  OverlaySlot,
  Persona,
  Phase,
  Player,
  Segment,
  StatSnapshot,
  Team,
  TeamSide,
  TeamStats,
  WireMessage,
} from "@contracts";

import type { WireMessage } from "@contracts";

const WIRE_KINDS: ReadonlySet<string> = new Set([
  "match_meta",
  "match_event",
  "stat_snapshot",
  "moment",
  "insight",
  "overlay",
] satisfies WireMessage["msg"][]);

/** A JSON value from a socket or file that carries a known `msg` discriminator. */
export function isWireMessage(value: unknown): value is WireMessage {
  return (
    typeof value === "object" &&
    value !== null &&
    "msg" in value &&
    typeof value.msg === "string" &&
    WIRE_KINDS.has(value.msg)
  );
}

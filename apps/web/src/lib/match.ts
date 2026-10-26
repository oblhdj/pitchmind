/**
 * Match state as a pure reducer over feed events, plus the selectors the views use.
 * Wall-clock timestamps arrive with each action, so the reducer stays pure.
 */
import type {
  Insight,
  MatchEvent,
  MatchMeta,
  Moment,
  Overlay,
  OverlaySlot,
  Phase,
  Player,
  StatSnapshot,
  Team,
  TeamSide,
  WireMessage,
} from "./contracts";

export type FeedStatus =
  | "idle"
  | "loading"
  | "playing"
  | "paused"
  | "ended"
  | "connecting"
  | "live"
  | "reconnecting"
  | "error";

/** A moment the replay can jump to. */
export interface Chapter {
  t: number;
  minute: number;
  kind: Moment["kind"];
}

export interface Catalog {
  segments: string[];
  chapters: Chapter[];
  duration: number;
}

export type FeedEvent =
  | { type: "message"; msg: WireMessage }
  | { type: "batch"; msgs: WireMessage[] } // history after a seek: no overlay goes on air
  | { type: "clock"; t: number }
  | { type: "reset" }
  | { type: "status"; status: FeedStatus; detail?: string }
  | { type: "catalog"; catalog: Catalog };

/** An overlay and the wall-clock time (ms) it went on air; null for history replayed by a seek. */
export interface AiredOverlay {
  overlay: Overlay;
  airedAt: number | null;
}

export interface MatchState {
  meta: MatchMeta | null;
  events: Record<number, MatchEvent>;
  snapshots: StatSnapshot[];
  moments: Record<string, Moment>;
  insights: Insight[];
  overlays: Record<string, AiredOverlay>;
  clock: number;
  status: FeedStatus;
  detail: string | null;
  catalog: Catalog | null;
}

export const initialState: MatchState = {
  meta: null,
  events: {},
  snapshots: [],
  moments: {},
  insights: [],
  overlays: {},
  clock: 0,
  status: "idle",
  detail: null,
  catalog: null,
};

export interface Action {
  event: FeedEvent;
  now: number; // performance.now() when the event arrived
}

export function reduce(state: MatchState, { event, now }: Action): MatchState {
  switch (event.type) {
    case "reset":
      return { ...initialState, status: state.status, catalog: state.catalog, meta: state.meta };
    case "status":
      return { ...state, status: event.status, detail: event.detail ?? null };
    case "catalog":
      return { ...state, catalog: event.catalog };
    case "clock":
      return event.t === state.clock ? state : { ...state, clock: event.t };
    case "message":
      return apply(state, event.msg, now);
    case "batch":
      return event.msgs.reduce<MatchState>((acc, msg) => apply(acc, msg, null), state);
  }
}

function insertSorted<T>(items: readonly T[], item: T, time: (x: T) => number): T[] {
  const out = [...items];
  let i = out.length;
  while (i > 0 && time(out[i - 1] as T) > time(item)) i -= 1;
  out.splice(i, 0, item);
  return out;
}

function apply(state: MatchState, msg: WireMessage, now: number | null): MatchState {
  switch (msg.msg) {
    case "match_meta":
      // A different match id is the next match of a looping live feed: its event ids start
      // again at 0, so nothing of the previous match may be kept.
      if (state.meta !== null && state.meta.match_id !== msg.match_id) {
        return { ...initialState, status: state.status, detail: state.detail, catalog: state.catalog, meta: msg };
      }
      return { ...state, meta: msg };
    case "match_event":
      return msg.id in state.events ? state : { ...state, events: { ...state.events, [msg.id]: msg } };
    case "stat_snapshot":
      if (state.snapshots.some((s) => s.t === msg.t && s.last_event_id === msg.last_event_id)) return state;
      return { ...state, snapshots: insertSorted(state.snapshots, msg, (s) => s.t) };
    case "moment":
      return msg.id in state.moments ? state : { ...state, moments: { ...state.moments, [msg.id]: msg } };
    case "insight":
      if (state.insights.some((i) => i.id === msg.id)) return state;
      return { ...state, insights: insertSorted(state.insights, msg, (i) => i.t) };
    case "overlay":
      if (msg.overlay_id in state.overlays) return state;
      return { ...state, overlays: { ...state.overlays, [msg.overlay_id]: { overlay: msg, airedAt: now } } };
  }
}

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

export function latestSnapshot(state: MatchState): StatSnapshot | null {
  return state.snapshots.at(-1) ?? null;
}

/** The broadcast minute and phase at the current clock, extrapolated from the last snapshot or event. */
export function currentMinute(state: MatchState): { minute: number; phase: Phase } | null {
  const snapshot = latestSnapshot(state);
  let anchor: { t: number; minute: number; phase: Phase } | null = snapshot;
  for (const event of Object.values(state.events)) {
    if (event.t <= state.clock && (!anchor || event.t > anchor.t)) anchor = event;
  }
  if (!anchor) return null;
  const running = anchor.phase === "first_half" || anchor.phase === "second_half";
  const extra = running ? Math.max(0, Math.floor((state.clock - anchor.t) / 60)) : 0;
  return { minute: anchor.minute + extra, phase: anchor.phase };
}

/** Score and broadcast minute for score bugs and headers. */
export function scoreLine(state: MatchState): { home: number; away: number; minute: number | null; phase: Phase | null } {
  const snapshot = latestSnapshot(state);
  const now = currentMinute(state);
  return {
    home: snapshot?.score.home ?? 0,
    away: snapshot?.score.away ?? 0,
    minute: now?.minute ?? null,
    phase: now?.phase ?? null,
  };
}

/** The last on-ball event with a location, for the pitch marker. */
export function lastLocatedEvent(state: MatchState): MatchEvent | null {
  let best: MatchEvent | null = null;
  for (const event of Object.values(state.events)) {
    if ((event.start || event.end) && event.t <= state.clock && (!best || event.t > best.t)) best = event;
  }
  return best;
}

/** Insights for one segment, newest first. */
export function insightsFor(state: MatchState, key: string): Insight[] {
  return state.insights.filter((i) => i.segment.key === key).reverse();
}

/** On air right now for a segment: per slot, the highest-priority overlay; highest priority first. */
export function onAir(
  state: MatchState,
  key: string,
  now: number,
  held: ReadonlySet<string> = new Set(),
): Overlay[] {
  const bySlot = new Map<OverlaySlot, Overlay>();
  for (const { overlay, airedAt } of Object.values(state.overlays)) {
    if (overlay.segment_key !== key || airedAt === null) continue;
    if (now - airedAt >= overlay.duration_s * 1000) continue;
    if (overlay.insight_id !== null && held.has(overlay.insight_id)) continue;
    const current = bySlot.get(overlay.slot);
    if (!current || overlay.priority > current.priority) bySlot.set(overlay.slot, overlay);
  }
  return [...bySlot.values()].sort((a, b) => b.priority - a.priority);
}

/** Segment keys seen so far, or every key in the replay file. */
export function knownSegments(state: MatchState): string[] {
  if (state.catalog) return state.catalog.segments;
  return [...new Set(state.insights.map((i) => i.segment.key))];
}

export function team(meta: MatchMeta | null, side: TeamSide): Team | null {
  if (!meta) return null;
  return side === "home" ? meta.home : meta.away;
}

export function findPlayer(meta: MatchMeta | null, id: string | null): (Player & { side: TeamSide }) | null {
  if (!meta || !id) return null;
  for (const side of ["home", "away"] as const) {
    const player = meta[side].players.find((p) => p.id === id);
    if (player) return { ...player, side };
  }
  return null;
}

export function playerName(meta: MatchMeta | null, id: string | null): string | null {
  return findPlayer(meta, id)?.short_name ?? id;
}

export function citedEvents(state: MatchState, insight: Insight): MatchEvent[] {
  const ids = [...new Set(insight.claims.flatMap((c) => c.evidence))].sort((a, b) => a - b);
  return ids.map((id) => state.events[id]).filter((e): e is MatchEvent => e !== undefined);
}

export function eventsOf(state: MatchState, playerId: string): MatchEvent[] {
  return Object.values(state.events)
    .filter((e) => e.player === playerId || e.receiver === playerId)
    .sort((a, b) => b.t - a.t);
}

/** The phase at match time ``t``, from the last snapshot or event before it. */
export function phaseAt(state: MatchState, t: number): Phase | null {
  let best: { t: number; phase: Phase } | null = null;
  for (const item of [...state.snapshots, ...Object.values(state.events)]) {
    if (item.t <= t && (!best || item.t >= best.t)) best = item;
  }
  return best?.phase ?? null;
}

/** The broadcast minute of the moment an insight is about, e.g. "61'" or "90+4'". */
export function minuteOf(state: MatchState, insight: Insight): { minute: number; phase: Phase | null } | null {
  const moment = insight.moment_id ? state.moments[insight.moment_id] : undefined;
  return moment ? { minute: moment.minute, phase: phaseAt(state, moment.t) } : null;
}

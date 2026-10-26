/**
 * Where wire messages come from, behind one interface so the views never care.
 *
 * - Mock: replays `data/mock/stream.jsonl` on a timer. A message is emitted when
 *   `elapsed x speed >= t` (`show_at` for overlays). Every segment is emitted; the views
 *   filter, so switching profile is instant.
 * - Live: WebSocket to the backend (`ws://localhost:8765/ws?segment=...`, later Azure Web
 *   PubSub with the same frames). Insights and overlays arrive already filtered to the
 *   segment; overlays that arrive early are held until the match clock reaches `show_at`.
 */
import { isWireMessage, type WireMessage } from "./contracts";
import type { Catalog, Chapter, FeedEvent, FeedStatus } from "./match";

export type FeedMode = "mock" | "live";
export type Listener = (event: FeedEvent) => void;

export const SPEEDS = [1, 10, 20] as const;
export const DEFAULT_LIVE_URL = process.env.NEXT_PUBLIC_LIVE_WS_URL ?? "ws://localhost:8765/ws";
export const MOCK_STREAM_URL = "/api/mock-stream";

export interface Feed {
  readonly mode: FeedMode;
  subscribe(listener: Listener): () => void;
  start(): void;
  stop(): void;
  /** Live: subscribe to another segment. Mock: no-op (every segment is replayed). */
  setSegment(key: string | null): void;
  /** Replay controls; live feeds ignore them. */
  pause(): void;
  resume(): void;
  setSpeed(speed: number): void;
  seek(t: number): void;
}

export interface FeedOptions {
  mode: FeedMode;
  /** The fan's segment; null means every segment (studio). */
  segment: string | null;
  /** Live studio: one connection per segment. */
  segments?: readonly string[];
  speed?: number;
  from?: number;
  liveUrl?: string;
  mockUrl?: string;
}

export function createFeed(options: FeedOptions): Feed {
  if (options.mode === "mock") return new MockFeed(options);
  const url = options.liveUrl ?? DEFAULT_LIVE_URL;
  if (options.segments && options.segments.length > 0) {
    return new MultiFeed(options.segments.map((key) => new LiveFeed(url, key)));
  }
  return new LiveFeed(url, options.segment);
}

// ---------------------------------------------------------------------------
// Replay scheduling (pure, unit-tested)
// ---------------------------------------------------------------------------

export interface Timed {
  time: number;
  msg: WireMessage;
}

export function timeOf(msg: WireMessage): number {
  switch (msg.msg) {
    case "match_meta":
      return Number.NEGATIVE_INFINITY;
    case "overlay":
      return msg.show_at;
    default:
      return msg.t;
  }
}

/** Parse a JSONL stream into messages ordered by emit time (stable for ties). */
export function parseStream(text: string): Timed[] {
  const items: Timed[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const value: unknown = JSON.parse(line);
    if (isWireMessage(value)) items.push({ time: timeOf(value), msg: value });
  }
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.time - b.item.time || a.index - b.index)
    .map(({ item }) => item);
}

/** Index of the first message still in the future once the clock reads ``clock``. */
export function dueUntil(items: readonly Timed[], cursor: number, clock: number): number {
  let i = cursor;
  while (i < items.length && (items[i] as Timed).time <= clock) i += 1;
  return i;
}

export function catalogOf(items: readonly Timed[]): Catalog {
  const segments = new Set<string>();
  const chapters: Chapter[] = [];
  let duration = 0;
  for (const { time, msg } of items) {
    if (Number.isFinite(time)) duration = Math.max(duration, time);
    if (msg.msg === "insight") segments.add(msg.segment.key);
    if (msg.msg === "overlay") segments.add(msg.segment_key);
    if (msg.msg === "moment") chapters.push({ t: msg.t, minute: msg.minute, kind: msg.kind });
  }
  return { segments: [...segments], chapters, duration };
}

// ---------------------------------------------------------------------------
// Feeds
// ---------------------------------------------------------------------------

abstract class BaseFeed {
  private listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  protected emit(event: FeedEvent): void {
    for (const listener of this.listeners) listener(event);
  }

  protected status(status: FeedStatus, detail?: string): void {
    this.emit({ type: "status", status, detail });
  }
}

const TICK_MS = 100;

export class MockFeed extends BaseFeed implements Feed {
  readonly mode = "mock" as const;
  private items: Timed[] = [];
  private cursor = 0;
  private clock = 0;
  private speed: number;
  private playing = false;
  private stopped = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private last = 0;
  private duration = 0;

  constructor(private readonly options: FeedOptions) {
    super();
    this.speed = options.speed ?? 20;
  }

  start(): void {
    this.status("loading");
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const response = await fetch(this.options.mockUrl ?? MOCK_STREAM_URL);
      if (!response.ok) throw new Error(`mock stream: HTTP ${response.status}`);
      const items = parseStream(await response.text());
      if (this.stopped) return;
      this.items = items;
      const catalog = catalogOf(items);
      this.duration = catalog.duration;
      this.emit({ type: "catalog", catalog });
      this.seek(this.options.from ?? 0);
      this.resume();
      this.timer = setInterval(this.tick, TICK_MS);
    } catch (error) {
      if (!this.stopped) this.status("error", error instanceof Error ? error.message : String(error));
    }
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  setSegment(): void {}

  pause(): void {
    this.playing = false;
    this.status("paused");
  }

  resume(): void {
    if (this.cursor >= this.items.length && this.clock >= this.duration) this.seek(0);
    this.playing = true;
    this.last = performance.now();
    this.status("playing");
  }

  setSpeed(speed: number): void {
    if (speed > 0) this.speed = speed;
  }

  seek(t: number): void {
    this.clock = Math.max(0, t);
    this.cursor = dueUntil(this.items, 0, this.clock);
    this.emit({ type: "reset" });
    this.emit({ type: "batch", msgs: this.items.slice(0, this.cursor).map((i) => i.msg) });
    this.emit({ type: "clock", t: this.clock });
    this.last = performance.now();
  }

  private tick = (): void => {
    const now = performance.now();
    const elapsed = (now - this.last) / 1000;
    this.last = now;
    if (!this.playing) return;
    this.clock += elapsed * this.speed;
    const next = dueUntil(this.items, this.cursor, this.clock);
    for (let i = this.cursor; i < next; i += 1) this.emit({ type: "message", msg: (this.items[i] as Timed).msg });
    this.cursor = next;
    this.emit({ type: "clock", t: this.clock });
    if (this.cursor >= this.items.length && this.clock >= this.duration) {
      this.playing = false;
      this.status("ended");
    }
  };
}

const BACKOFF_MS = [1000, 2000, 5000, 10000];

export class LiveFeed extends BaseFeed implements Feed {
  readonly mode = "live" as const;
  private socket: WebSocket | null = null;
  private stopped = false;
  private attempts = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private pending: WireMessage[] = []; // overlays waiting for their show_at
  // Match clock: last match time seen, advanced at the observed replay rate between messages.
  private lastT = 0;
  private lastWall = 0;
  private rate = 1;
  private matchId: string | null = null;

  constructor(
    private readonly url: string,
    private segment: string | null,
  ) {
    super();
  }

  start(): void {
    this.connect();
    this.timer = setInterval(this.tick, 250);
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearInterval(this.timer);
    if (this.retry) clearTimeout(this.retry);
    this.socket?.close();
  }

  setSegment(key: string | null): void {
    if (key === this.segment) return;
    this.segment = key;
    if (key !== null && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "subscribe", segment_key: key }));
    }
  }

  pause(): void {}
  resume(): void {}
  setSpeed(): void {}
  seek(): void {}

  private endpoint(): string {
    if (this.segment === null) return this.url;
    const sep = this.url.includes("?") ? "&" : "?";
    return `${this.url}${sep}segment=${encodeURIComponent(this.segment)}`;
  }

  private connect(): void {
    if (this.stopped) return;
    this.status(this.attempts === 0 ? "connecting" : "reconnecting");
    const socket = new WebSocket(this.endpoint());
    this.socket = socket;
    socket.onopen = () => {
      this.attempts = 0;
      this.status("live");
    };
    socket.onmessage = (frame) => this.receive(frame.data);
    socket.onclose = () => {
      if (this.stopped) return;
      const delay = BACKOFF_MS[Math.min(this.attempts, BACKOFF_MS.length - 1)] ?? 10000;
      this.attempts += 1;
      this.status("reconnecting", `retrying in ${delay / 1000}s`);
      this.retry = setTimeout(() => this.connect(), delay);
    };
    socket.onerror = () => socket.close();
  }

  private clockNow(now = performance.now()): number {
    return this.lastWall === 0 ? this.lastT : this.lastT + ((now - this.lastWall) / 1000) * this.rate;
  }

  private receive(data: unknown): void {
    if (typeof data !== "string") return;
    let value: unknown;
    try {
      value = JSON.parse(data);
    } catch {
      return;
    }
    if (!isWireMessage(value)) return;
    if (value.msg === "match_meta" && value.match_id !== this.matchId) {
      // The next match of the loop: its clock starts again at 0, and nothing pending belongs to it.
      this.matchId = value.match_id;
      this.lastT = 0;
      this.lastWall = 0;
      this.rate = 1;
      this.pending = [];
    }
    if (value.msg === "overlay" && value.show_at > this.clockNow()) {
      this.pending.push(value);
      return;
    }
    if (value.msg !== "match_meta" && value.msg !== "overlay") this.observeTime(value.t);
    this.emit({ type: "message", msg: value });
  }

  /** Estimate how fast match time runs (the simulator may play at 1x to 20x). */
  private observeTime(t: number): void {
    const now = performance.now();
    if (t <= this.lastT) return;
    if (this.lastWall > 0) {
      const wall = (now - this.lastWall) / 1000;
      if (wall > 0.05) this.rate = 0.7 * this.rate + 0.3 * Math.min(60, Math.max(0.5, (t - this.lastT) / wall));
    }
    this.lastT = t;
    this.lastWall = now;
  }

  private tick = (): void => {
    const clock = this.clockNow();
    const due = this.pending.filter((m) => timeOf(m) <= clock);
    if (due.length > 0) {
      this.pending = this.pending.filter((m) => timeOf(m) > clock);
      for (const msg of due) this.emit({ type: "message", msg });
    }
    if (this.lastWall > 0) this.emit({ type: "clock", t: clock });
  };
}

/** Several live connections (one per segment) seen as one feed, for the studio. */
class MultiFeed extends BaseFeed implements Feed {
  readonly mode = "live" as const;
  private unsubscribes: Array<() => void> = [];

  constructor(private readonly feeds: LiveFeed[]) {
    super();
  }

  start(): void {
    this.unsubscribes = this.feeds.map((feed, i) =>
      feed.subscribe((event) => {
        if (event.type === "clock" && i > 0) return; // one clock is enough
        this.emit(event);
      }),
    );
    for (const feed of this.feeds) feed.start();
  }

  stop(): void {
    for (const off of this.unsubscribes) off();
    for (const feed of this.feeds) feed.stop();
  }

  setSegment(): void {}
  pause(): void {}
  resume(): void {}
  setSpeed(): void {}
  seek(): void {}
}

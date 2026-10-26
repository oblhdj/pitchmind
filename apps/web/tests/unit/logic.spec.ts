/** Pure logic: segments, replay scheduling, overlay selection. Runs without a browser. */
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import type { MatchEvent, MatchMeta, Overlay, WireMessage } from "../../src/lib/contracts";
import { catalogOf, dueUntil, LiveFeed, parseStream } from "../../src/lib/feed";
import { broadcastMinute } from "../../src/lib/format";
import { initialState, insightsFor, onAir, reduce, type MatchState } from "../../src/lib/match";
import { feedParams, profileParams } from "../../src/lib/options";
import { closestSegment, parseSegmentKey, segmentKey } from "../../src/lib/segments";

const STREAM = readFileSync(path.resolve(__dirname, "../../../../data/mock/stream.jsonl"), "utf-8");
const ANALYST = "analyst|en|club:*|player:*|metric:*";
const ARABIC = "casual|ar|club:home|player:*|metric:*";
const PLAYER = "casual|en|club:*|player:H10|metric:*";

test("segment keys match the contract format", () => {
  const profile = { persona: "casual", language: "ar", club: "home", player: null } as const;
  expect(segmentKey(profile)).toBe(ARABIC);
  expect(parseSegmentKey(ARABIC)).toEqual(profile);
  expect(parseSegmentKey("casual|xx|club:*|player:*|metric:*")).toBeNull();
});

test("the closest available segment prefers language, then persona, never another player's focus", () => {
  const available = [ANALYST, ARABIC, "beginner|fr|club:*|player:*|metric:*", PLAYER];
  expect(closestSegment(ANALYST, available)).toBe(ANALYST);
  expect(closestSegment("casual|ar|club:*|player:*|metric:*", available)).toBe(ARABIC);
  expect(closestSegment("casual|en|club:*|player:*|metric:*", available)).toBe(ANALYST);
  expect(closestSegment("casual|en|club:*|player:H10|metric:*", available)).toBe(PLAYER);
  expect(closestSegment("beginner|es|club:*|player:*|metric:*", available)).toBe("beginner|fr|club:*|player:*|metric:*");
});

test("broadcast minutes show stoppage time", () => {
  expect(broadcastMinute(46, "first_half")).toBe("45+1'");
  expect(broadcastMinute(46, "second_half")).toBe("46'");
  expect(broadcastMinute(94, "full_time")).toBe("90+4'");
});

test("the replay emits each message when elapsed x speed reaches its time", () => {
  const items = parseStream(STREAM);
  expect(items[0]?.msg.msg).toBe("match_meta");
  expect(items.every((item, i) => i === 0 || (items[i - 1]?.time ?? 0) <= item.time)).toBe(true);
  const firstOverlay = items.findIndex((item) => item.msg.msg === "overlay");
  const overlay = items[firstOverlay]?.msg as Overlay;
  expect(dueUntil(items, 0, overlay.show_at - 0.1)).toBeLessThanOrEqual(firstOverlay);
  expect(dueUntil(items, 0, overlay.show_at)).toBeGreaterThan(firstOverlay);
  const catalog = catalogOf(items);
  expect(catalog.segments.sort()).toEqual([ANALYST, "beginner|fr|club:*|player:*|metric:*", ARABIC, PLAYER].sort());
  expect(catalog.chapters).toHaveLength(10);
});

function play(msgs: readonly WireMessage[], now: number): MatchState {
  return msgs.reduce<MatchState>((state, msg) => reduce(state, { event: { type: "message", msg }, now }), initialState);
}

test("on air: per slot the highest priority, for the segment's duration, unless held", () => {
  const items = parseStream(STREAM).map((i) => i.msg);
  const lowerThirds = items.filter((m): m is Overlay => m.msg === "overlay" && m.segment_key === ANALYST);
  const first = lowerThirds[0] as Overlay;
  const rival: Overlay = { ...first, overlay_id: "ov-rival", insight_id: "ins-rival", priority: first.priority + 5 };
  const state = play([first, rival], 1000);
  expect(onAir(state, ANALYST, 1000).map((o) => o.overlay_id)).toEqual(["ov-rival"]);
  expect(onAir(state, ARABIC, 1000)).toEqual([]);
  expect(onAir(state, ANALYST, 1000 + rival.duration_s * 1000)).toEqual([]);
  expect(onAir(state, ANALYST, 1000, new Set(["ins-rival"])).map((o) => o.overlay_id)).toEqual([first.overlay_id]);
});

test("history replayed by a seek never goes on air", () => {
  const items = parseStream(STREAM).map((i) => i.msg);
  const state = reduce(initialState, { event: { type: "batch", msgs: items }, now: 1000 });
  expect(onAir(state, ANALYST, 1000)).toEqual([]);
  const insights = insightsFor(state, ANALYST);
  expect(insights.length).toBeGreaterThan(5);
  expect(insights[0]?.t).toBeGreaterThan(insights.at(-1)?.t ?? 0); // newest first
});

test("the next match of a live loop starts from a clean state and clock", () => {
  const items = parseStream(STREAM).map((i) => i.msg);
  const meta = items[0] as MatchMeta;
  const late = items.filter((m): m is MatchEvent => m.msg === "match_event").at(-1) as MatchEvent;
  const overlay = items.find((m): m is Overlay => m.msg === "overlay") as Overlay;
  const next: MatchMeta = { ...meta, match_id: "M002" };

  const played = play([meta, late, meta], 1000);
  expect(Object.keys(played.events)).toHaveLength(1); // a re-announcement keeps the match
  const fresh = play([meta, late, next], 1000);
  expect(fresh.meta?.match_id).toBe("M002");
  expect(fresh.events).toEqual({}); // the old event ids would shadow the new match's

  // Without a clock reset, an overlay of the new match would look long overdue and air at once.
  const feed = new LiveFeed("ws://unused", null);
  const emitted: WireMessage[] = [];
  feed.subscribe((e) => {
    if (e.type === "message") emitted.push(e.msg);
  });
  const receive = (msg: WireMessage) => (feed as unknown as { receive(data: string): void }).receive(JSON.stringify(msg));
  [meta, late, next, { ...overlay, match_id: "M002", show_at: 10 }].forEach(receive);
  expect(emitted.map((m) => m.msg)).toEqual(["match_meta", "match_event", "match_meta"]);
});

test("URL options", () => {
  expect(feedParams({ mode: "live", speed: "10", from: "27m" })).toEqual({ mode: "live", speed: 10, from: 1620 });
  expect(feedParams({ speed: "-3" })).toEqual({ mode: "mock", speed: 20, from: 0 });
  expect(profileParams({ persona: "beginner", lang: "fr", club: "away", player: "H10" })).toEqual({
    persona: "beginner",
    language: "fr",
    club: "away",
    player: "H10",
  });
  expect(profileParams({ persona: "boss", player: "<script>" })).toEqual({
    persona: "analyst",
    language: "en",
    club: null,
    player: null,
  });
});

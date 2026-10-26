/** Pass map data shaping: which passes, where, completed or not. Runs without a browser. */
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import type { MatchEvent, TeamSide } from "../../src/lib/contracts";
import { parseStream } from "../../src/lib/feed";
import { passLines, passMap, upToClock } from "../../src/lib/metrics";

const STREAM = readFileSync(path.resolve(__dirname, "../../../../data/mock/stream.jsonl"), "utf-8");

function pass(
  id: number,
  t: number,
  team: TeamSide,
  player: string,
  start: [number, number],
  end: [number, number],
  outcome: "success" | "failure" = "success",
): MatchEvent {
  return {
    msg: "match_event",
    schema_version: "1.0",
    id,
    match_id: "M1",
    t,
    minute: Math.floor(t / 60),
    phase: "first_half",
    type: "pass",
    team,
    player,
    receiver: null,
    start,
    end,
    outcome,
    under_pressure: false,
    ball_speed_kmh: null,
    player_speed_kmh: null,
    distance_m: null,
    related_event_id: null,
    source: "sim",
  };
}

const EVENTS: MatchEvent[] = [
  pass(3, 300, "away", "A8", [20, 10], [40, 30], "failure"),
  pass(1, 100, "home", "H10", [50, 34], [70, 20]),
  pass(2, 200, "home", "H7", [30, 60], [45, 50], "failure"),
  { ...pass(4, 250, "home", "H10", [10, 10], [20, 20]), type: "carry" },
  { ...pass(5, 260, "home", "H10", [10, 10], [20, 20]), end: null },
];

test("passes up to the clock, oldest first, away turned round to attack left", () => {
  const lines = passMap(EVENTS, { clock: 1000 });
  expect(lines.map((l) => l.event.id)).toEqual([1, 2, 3]); // no carry, no pass without an end
  expect(lines.map((l) => l.completed)).toEqual([true, false, false]);
  expect(lines[0]).toMatchObject({ from: [50, 34], to: [70, 20] });
  expect(lines[2]).toMatchObject({ from: [85, 58], to: [65, 38] });
  expect(passMap(EVENTS, { clock: 200 }).map((l) => l.event.id)).toEqual([1, 2]);
});

test("the sorted passes are cut to the clock without sorting again", () => {
  const lines = passLines(EVENTS);
  expect(upToClock(lines, 99)).toEqual([]);
  expect(upToClock(lines, 250).map((l) => l.event.id)).toEqual([1, 2]);
  expect(upToClock(lines, 1000, 1).map((l) => l.event.id)).toEqual([3]);
  expect(upToClock(lines, 1000, 0)).toEqual([]);
});

test("a chosen player wins over a chosen club, and only the latest passes are kept", () => {
  expect(passMap(EVENTS, { clock: 1000, club: "home" }).map((l) => l.event.id)).toEqual([1, 2]);
  expect(passMap(EVENTS, { clock: 1000, club: "away" }).map((l) => l.event.id)).toEqual([3]);
  expect(passMap(EVENTS, { clock: 1000, club: "away", player: "H10" }).map((l) => l.event.id)).toEqual([1]);
  expect(passMap(EVENTS, { clock: 1000, limit: 2 }).map((l) => l.event.id)).toEqual([2, 3]);
});

test("the replay's passes land on the pitch", () => {
  const events = parseStream(STREAM)
    .map((i) => i.msg)
    .filter((m): m is MatchEvent => m.msg === "match_event");
  const lines = passMap(events, { clock: Infinity });
  expect(lines.length).toBeGreaterThan(0);
  for (const { from, to } of lines) {
    for (const [x, y] of [from, to]) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(105);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(68);
    }
  }
});

import type { Language, MatchEvent, MetricName, OverlayMetric, TeamSide } from "./contracts";
import { formatNumber } from "./format";

const LABELS: Partial<Record<MetricName, Record<Language, string>>> = {
  xg: { en: "xG", fr: "xG", ar: "xG", es: "xG" },
  xt: { en: "xT", fr: "xT", ar: "xT", es: "xT" },
  pressure_index: { en: "Pressure", fr: "Pression", ar: "الضغط", es: "Presión" },
  player_speed_kmh: { en: "Top speed", fr: "Vitesse", ar: "السرعة", es: "Velocidad" },
  shot_speed_kmh: { en: "Shot speed", fr: "Frappe", ar: "قوة التسديدة", es: "Disparo" },
  ball_speed_kmh: { en: "Ball speed", fr: "Ballon", ar: "سرعة الكرة", es: "Balón" },
  pass_difficulty: { en: "Pass difficulty", fr: "Difficulté", ar: "صعوبة التمريرة", es: "Dificultad" },
  pass_distance_m: { en: "Pass length", fr: "Longueur", ar: "طول التمريرة", es: "Distancia" },
  possession_pct: { en: "Possession", fr: "Possession", ar: "الاستحواذ", es: "Posesión" },
  momentum: { en: "Momentum", fr: "Dynamique", ar: "الزخم", es: "Inercia" },
  control_chaos: { en: "Chaos", fr: "Chaos", ar: "الفوضى", es: "Caos" },
  distance_covered_m: { en: "Distance", fr: "Distance", ar: "المسافة", es: "Distancia" },
  sprints: { en: "Sprints", fr: "Sprints", ar: "الانطلاقات", es: "Sprints" },
  shots: { en: "Shots", fr: "Tirs", ar: "التسديدات", es: "Tiros" },
};

export function metricLabel(language: Language, metric: OverlayMetric): string {
  return metric.label ?? LABELS[metric.name]?.[language] ?? metric.name.replaceAll("_", " ");
}

export function metricValue(language: Language, metric: OverlayMetric): string {
  return formatNumber(metric.value, language, Math.abs(metric.value) < 10 ? 2 : 1);
}

/** One pass for the pass map, in pitch coordinates (105 x 68) with home attacking right. */
export interface PassLine {
  event: MatchEvent;
  completed: boolean;
  from: [number, number];
  to: [number, number];
}

/** The latest passes are kept, so a full live match stays legible. */
export const PASS_MAP_LIMIT = 250;

/**
 * Every pass, oldest first. Coordinates arrive relative to the acting team, so away passes are
 * turned round, as on the broadcast pitch. A chosen player narrows to their passes, else a chosen
 * club to its team's.
 */
export function passLines(
  events: Iterable<MatchEvent>,
  { club = null, player = null }: { club?: TeamSide | null; player?: string | null } = {},
): PassLine[] {
  const lines: PassLine[] = [];
  for (const event of events) {
    const { start, end, team } = event;
    if (event.type !== "pass" || !start || !end || !team) continue;
    if (player ? event.player !== player : club !== null && team !== club) continue;
    const turn = ([x, y]: [number, number]): [number, number] => (team === "away" ? [105 - x, 68 - y] : [x, y]);
    lines.push({ event, completed: event.outcome === "success", from: turn(start), to: turn(end) });
  }
  return lines.sort((a, b) => a.event.t - b.event.t || a.event.id - b.event.id);
}

/** The passes played by `clock` (from `passLines`, oldest first), only the latest `limit`. */
export function upToClock(lines: readonly PassLine[], clock: number, limit = PASS_MAP_LIMIT): PassLine[] {
  let end = lines.length;
  while (end > 0 && (lines[end - 1] as PassLine).event.t > clock) end -= 1;
  return limit > 0 ? lines.slice(Math.max(0, end - limit), end) : [];
}

/** The pass map at the match clock: `passLines` cut by `upToClock`. */
export function passMap(
  events: Iterable<MatchEvent>,
  { clock, club = null, player = null, limit = PASS_MAP_LIMIT }: { clock: number; club?: TeamSide | null; player?: string | null; limit?: number },
): PassLine[] {
  return upToClock(passLines(events, { club, player }), clock, limit);
}

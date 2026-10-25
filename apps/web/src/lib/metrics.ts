import type { Language, MetricName, OverlayMetric } from "./contracts";
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

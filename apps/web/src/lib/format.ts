import type { Language, Phase } from "./contracts";

const LOCALES: Record<Language, string> = {
  en: "en-GB",
  fr: "fr-FR",
  es: "es-ES",
  ar: "ar-u-nu-latn", // Western digits, as the agents write them
};

export function locale(language: Language): string {
  return LOCALES[language];
}

/** Broadcast minute: 46 in the first half is shown as 45+1, 92 in the second as 90+2. */
export function broadcastMinute(minute: number, phase: Phase | null | undefined): string {
  if ((phase === "first_half" || phase === "half_time") && minute > 45) return `45+${minute - 45}'`;
  if ((phase === "second_half" || phase === "full_time") && minute > 90) return `90+${minute - 90}'`;
  return `${minute}'`;
}

export function formatNumber(value: number, language: Language, fractionDigits = 2): string {
  return new Intl.NumberFormat(LOCALES[language], { maximumFractionDigits: fractionDigits }).format(value);
}

export function formatPercent(value: number, language: Language): string {
  return new Intl.NumberFormat(LOCALES[language], { style: "percent", maximumFractionDigits: 0 }).format(value / 100);
}

/** "mm:ss" of match time, for replay controls. */
export function matchClock(t: number): string {
  const total = Math.max(0, Math.floor(t));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

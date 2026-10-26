import type { Language, Persona, TeamSide } from "./contracts";

/** What a fan picked in the selectors. One-metric mode is not exposed in the app yet. */
export interface Profile {
  persona: Persona;
  language: Language;
  club: TeamSide | null;
  player: string | null;
}

export const PERSONAS: readonly Persona[] = ["analyst", "casual", "beginner"];
export const LANGUAGES: readonly Language[] = ["en", "fr", "ar", "es"];

export const DEFAULT_PROFILE: Profile = { persona: "analyst", language: "en", club: null, player: null };

/** The segments the cloud generates (`SEGMENTS=demo`, the agents' `DEMO_SEGMENTS`). */
export const DEMO_SEGMENTS: readonly string[] = [
  "analyst|en|club:*|player:*|metric:*",
  "casual|ar|club:home|player:*|metric:*",
  "beginner|fr|club:*|player:*|metric:*",
  "casual|en|club:*|player:H10|metric:*",
];

/** `persona|lang|club:X|player:Y|metric:*`, exactly as the agents and render service key their output. */
export function segmentKey(profile: Profile): string {
  return `${profile.persona}|${profile.language}|club:${profile.club ?? "*"}|player:${profile.player ?? "*"}|metric:*`;
}

export function parseSegmentKey(key: string): Profile | null {
  const [persona, language, club, player] = key.split("|");
  const value = (part: string | undefined, label: string): string | null | undefined => {
    if (!part?.startsWith(`${label}:`)) return undefined;
    const raw = part.slice(label.length + 1);
    return raw === "*" ? null : raw;
  };
  const clubValue = value(club, "club");
  const playerValue = value(player, "player");
  if (!PERSONAS.includes(persona as Persona) || !LANGUAGES.includes(language as Language)) return null;
  if (clubValue === undefined || playerValue === undefined) return null;
  if (clubValue !== null && clubValue !== "home" && clubValue !== "away") return null;
  return { persona: persona as Persona, language: language as Language, club: clubValue, player: playerValue };
}

/**
 * The available segment that best fits a wanted one. The cloud generates only the demo
 * segments and the mock replay only has a few, so a fan gets the nearest variant instead of an
 * empty feed. Language matters most, then persona; a player-focus variant is never given to a
 * fan who does not follow that player.
 */
export function closestSegment(wanted: string, available: readonly string[]): string | null {
  if (available.includes(wanted)) return wanted;
  const want = parseSegmentKey(wanted);
  if (!want) return null;
  let best: { key: string; score: number } | null = null;
  for (const key of available) {
    const have = parseSegmentKey(key);
    if (!have) continue;
    if (have.player !== null && have.player !== want.player) continue;
    let score = 0;
    if (have.language === want.language) score += 8;
    if (have.persona === want.persona) score += 4;
    if (have.player !== null && have.player === want.player) score += 3;
    if (have.club === want.club) score += 2;
    else if (have.club !== null) score -= 1;
    if (!best || score > best.score) best = { key, score };
  }
  return best?.key ?? null;
}

/** Page options from the URL, so a demo view can be bookmarked or opened side by side. */
import type { Language, Persona, TeamSide } from "./contracts";
import type { FeedMode } from "./feed";
import { DEFAULT_PROFILE, LANGUAGES, PERSONAS, type Profile } from "./segments";

export type SearchParams = Record<string, string | string[] | undefined>;

export interface FeedParams {
  mode: FeedMode;
  speed: number;
  from: number;
}

function first(params: SearchParams, name: string): string | undefined {
  const value = params[name];
  return Array.isArray(value) ? value[0] : value;
}

/** ``?mode=live``, ``?speed=10``, ``?from=1650`` (seconds) or ``?from=27m`` (match minute). */
export function feedParams(params: SearchParams): FeedParams {
  const envMode = process.env.NEXT_PUBLIC_FEED_MODE === "live" ? "live" : "mock";
  const mode = first(params, "mode") === "live" ? "live" : first(params, "mode") === "mock" ? "mock" : envMode;
  const speed = Number(first(params, "speed"));
  const rawFrom = first(params, "from") ?? "0";
  const from = rawFrom.endsWith("m") ? Number(rawFrom.slice(0, -1)) * 60 : Number(rawFrom);
  return {
    mode,
    speed: Number.isFinite(speed) && speed > 0 ? speed : 20,
    from: Number.isFinite(from) && from > 0 ? from : 0,
  };
}

/** ``?persona=casual&lang=ar&club=home&player=H10``. */
export function profileParams(params: SearchParams): Profile {
  const persona = first(params, "persona");
  const language = first(params, "lang");
  const club = first(params, "club");
  const player = first(params, "player");
  return {
    persona: PERSONAS.includes(persona as Persona) ? (persona as Persona) : DEFAULT_PROFILE.persona,
    language: LANGUAGES.includes(language as Language) ? (language as Language) : DEFAULT_PROFILE.language,
    club: club === "home" || club === "away" ? (club as TeamSide) : null,
    player: player && /^[HA]\d{1,2}$/.test(player) ? player : null,
  };
}

export function stringParam(params: SearchParams, name: string): string | null {
  return first(params, name) ?? null;
}

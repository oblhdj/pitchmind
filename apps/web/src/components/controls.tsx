"use client";

import Link from "next/link";
import { useMemo, type CSSProperties, type ReactNode } from "react";

import type { Language, MomentKind } from "@/lib/contracts";
import { SPEEDS, type FeedMode } from "@/lib/feed";
import { matchClock } from "@/lib/format";
import { t } from "@/lib/i18n";
import { kindsOf, OverlayLayer, Pitch, ScoreBug, LiveTag } from "@/components/broadcast";
import { lastLocatedEvent, onAir, scoreLine, type MatchState } from "@/lib/match";
import type { ReplayControls as Controls } from "@/lib/useMatch";

import { PauseIcon, PlayIcon, RestartIcon } from "./ui";

const CHAPTER_STYLE: Partial<Record<MomentKind, string>> = {
  goal: "bg-gold",
  big_chance: "bg-mint",
  save: "bg-mint",
  phase: "bg-white",
  speed_threshold: "bg-violet",
};

const CHAPTER_LABEL: Record<MomentKind, string> = {
  goal: "Goal",
  big_chance: "Big chance",
  save: "Save",
  momentum_swing: "Momentum swing",
  pressure_surge: "Pressure surge",
  control_shift: "Control shift",
  rhythm_change: "Rhythm change",
  speed_threshold: "Speed",
  distance_milestone: "Distance",
  milestone: "Milestone",
  card: "Card",
  substitution_impact: "Substitution",
  phase: "Whistle",
};

export function Brand({ sub }: { sub?: ReactNode }) {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="PitchMind home">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <defs>
          <linearGradient id="pm-brand" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#34f5c5" />
            <stop offset="1" stopColor="#9b8cff" />
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="28" height="28" rx="8" fill="url(#pm-brand)" />
        <rect x="7.5" y="9" width="17" height="14" rx="2" fill="none" stroke="#04070d" strokeWidth="1.8" />
        <path d="M16 9v14M7.5 13.5h3v5h-3M24.5 13.5h-3v5h3" fill="none" stroke="#04070d" strokeWidth="1.6" />
        <circle cx="16" cy="16" r="2.2" fill="#04070d" />
      </svg>
      <div className="leading-none">
        <div className="font-display text-xl font-extrabold tracking-wide text-white">
          Pitch<span className="text-mint">Mind</span>
        </div>
        {sub && <div className="mt-0.5 text-[0.7rem] text-slate-400">{sub}</div>}
      </div>
    </Link>
  );
}

export function StatusPill({ mode, state, language = "en" }: { mode: FeedMode; state: MatchState; language?: Language }) {
  const live = mode === "live";
  const ok = state.status === "live" || state.status === "playing";
  const label = live ? t(language, "live") : t(language, "demoReplay");
  return (
    <span
      data-testid="feed-status"
      data-status={state.status}
      title={state.detail ?? state.status}
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 ${
        live ? "bg-live/12 text-live ring-live/30" : "bg-white/6 text-slate-200 ring-white/10"
      }`}
    >
      <span className={`size-2 rounded-full ${ok ? (live ? "animate-blink bg-live" : "bg-mint") : "bg-slate-500"}`} />
      {label}
      {state.status !== "playing" && state.status !== "live" && <span className="font-normal text-slate-400">· {state.status}</span>}
    </span>
  );
}

/** Play, speed and a scrubber with the match's key moments (mock replay only). */
export function ReplayControls({
  mode,
  state,
  speed,
  controls,
}: {
  mode: FeedMode;
  state: MatchState;
  speed: number;
  controls: Controls;
}) {
  const duration = Math.max(state.catalog?.duration ?? 0, state.clock, 1);
  const progress = `${Math.min(100, (state.clock / duration) * 100).toFixed(2)}%`;
  const playing = state.status === "playing";
  const chapters = state.catalog?.chapters ?? [];
  if (mode === "live") return null;
  return (
    // The minimum width makes the header wrap the controls onto their own line on phones.
    <div dir="ltr" data-testid="replay-controls" className="flex min-w-[17rem] flex-1 items-center gap-3">
      <button
        type="button"
        onClick={() => (playing ? controls.pause() : controls.resume())}
        aria-label={playing ? "Pause replay" : "Play replay"}
        className="grid size-9 shrink-0 place-content-center rounded-full bg-white text-ink-950 shadow transition hover:scale-105"
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>
      <button
        type="button"
        onClick={() => controls.seek(0)}
        aria-label="Restart from kick-off"
        className="grid size-8 shrink-0 place-content-center rounded-full text-slate-300 ring-1 ring-white/10 transition hover:bg-white/5 hover:text-white"
      >
        <RestartIcon />
      </button>
      <div role="radiogroup" aria-label="Replay speed" className="flex shrink-0 rounded-lg bg-ink-950/60 p-0.5 ring-1 ring-white/5">
        {SPEEDS.map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={speed === value}
            onClick={() => controls.setSpeed(value)}
            className={`rounded-md px-2 py-1 font-display text-sm font-bold tabular-nums transition ${
              speed === value ? "bg-mint text-ink-950" : "text-slate-300 hover:text-white"
            }`}
          >
            {value}×
          </button>
        ))}
      </div>
      <div className="relative hidden min-w-[180px] flex-1 items-center sm:flex">
        <input
          type="range"
          aria-label="Match time"
          className="scrubber w-full"
          min={0}
          max={Math.ceil(duration)}
          step={1}
          value={Math.min(state.clock, duration)}
          onChange={(event) => controls.seek(Number(event.target.value))}
          style={{ "--progress": progress } as CSSProperties}
        />
        {chapters.map((chapter) => (
          <button
            key={`${chapter.kind}-${chapter.t}`}
            type="button"
            title={`${chapter.minute}' ${CHAPTER_LABEL[chapter.kind]}`}
            aria-label={`Jump to ${chapter.minute}' ${CHAPTER_LABEL[chapter.kind]}`}
            onClick={() => controls.seek(Math.max(0, chapter.t - 8))}
            className={`absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-[calc(50%+11px)] rounded-full ring-2 ring-ink-900 transition hover:scale-150 ${
              CHAPTER_STYLE[chapter.kind] ?? "bg-sky"
            }`}
            style={{ left: `${(chapter.t / duration) * 100}%` }}
          />
        ))}
      </div>
      <span className="shrink-0 font-display text-sm font-semibold tabular-nums text-slate-300">{matchClock(state.clock)}</span>
    </div>
  );
}

/** A 16:9 broadcast frame: pitch, score bug and the overlays on air for one segment. */
export function BroadcastFrame({
  state,
  segment,
  now,
  held,
  liveLabel = "Live",
  testId = "broadcast-frame",
}: {
  state: MatchState;
  segment: string;
  now: number;
  held: ReadonlySet<string>;
  liveLabel?: string;
  testId?: string;
}) {
  const overlays = onAir(state, segment, now, held);
  const kinds = useMemo(() => kindsOf(state.insights), [state.insights]);
  const score = scoreLine(state);
  return (
    <div
      data-testid={testId}
      className="@container relative aspect-video w-full overflow-hidden rounded-2xl bg-ink-950 ring-1 ring-white/10 shadow-[0_30px_60px_-30px_rgb(0_0_0/0.8)]"
    >
      <Pitch lastEvent={lastLocatedEvent(state)} />
      <ScoreBug meta={state.meta} score={score} />
      <LiveTag label={liveLabel} />
      <OverlayLayer overlays={overlays} meta={state.meta} kinds={kinds} score={score} />
    </div>
  );
}

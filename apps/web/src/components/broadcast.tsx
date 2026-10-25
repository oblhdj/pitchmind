"use client";

/**
 * Broadcast graphics shared by the overlay page, the second-screen preview and the studio.
 * Sizes use container query units (cqw), so the same graphics scale from a small preview
 * to a 1920x1080 browser source.
 */
import { useId, type CSSProperties } from "react";

import type { InsightKind, Language, MatchEvent, MatchMeta, Overlay, Phase, Team, TeamSide } from "@/lib/contracts";
import { broadcastMinute } from "@/lib/format";
import { kindName } from "@/lib/i18n";
import { findPlayer, team as teamOf } from "@/lib/match";
import { metricLabel, metricValue } from "@/lib/metrics";

export interface ScoreLine {
  home: number;
  away: number;
  minute: number | null;
  phase: Phase | null;
}

/** A generated shield in the club colours: fictional clubs, no logos. */
export function TeamCrest({ team, size, className }: { team: Team | null; size?: number; className?: string }) {
  const id = useId();
  const primary = team?.colors.primary ?? "#334155";
  const secondary = team?.colors.secondary ?? "#cbd5e1";
  const initials = (team?.short_name ?? "?").slice(0, 3);
  return (
    <svg
      viewBox="0 0 64 72"
      width={size}
      height={size === undefined ? undefined : (size * 72) / 64}
      role="img"
      aria-label={team ? `${team.name} crest` : "Team crest"}
      className={className}
    >
      <defs>
        <linearGradient id={`${id}-shine`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0.28" />
          <stop offset="0.55" stopColor="white" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M32 3 59 11v23c0 18-12 29-27 35C17 63 5 52 5 34V11Z" fill={primary} stroke={secondary} strokeWidth="3" />
      <path d="M32 3v66C17 63 5 52 5 34V11Z" fill="black" opacity="0.16" />
      <path d="M6 24h52" stroke={secondary} strokeWidth="4" opacity="0.85" />
      <path d="M32 3 59 11v23c0 18-12 29-27 35C17 63 5 52 5 34V11Z" fill={`url(#${id}-shine)`} />
      <text x="32" y="51" textAnchor="middle" fontWeight="800" fontSize="17" fill={secondary} style={{ fontFamily: "var(--font-display)" }}>
        {initials}
      </text>
    </svg>
  );
}

/** The corner score bug: NCF 1-1 HBU 61'. */
export function ScoreBug({ meta, score }: { meta: MatchMeta | null; score: ScoreLine | null }) {
  if (!meta) return null;
  const minute = score?.minute != null ? broadcastMinute(score.minute, score.phase) : "";
  return (
    <div
      dir="ltr"
      data-testid="score-bug"
      className="absolute left-[3%] top-[5%] flex items-stretch overflow-hidden rounded-[0.5cqw] font-display text-[1.55cqw] font-bold uppercase leading-none shadow-[0_0.6cqw_1.6cqw_rgb(0_0_0/0.45)]"
    >
      <span className="flex items-center gap-[0.55cqw] bg-ink-950/90 px-[0.9cqw] py-[0.55cqw] text-white">
        <span className="h-[1.5cqw] w-[0.32cqw] rounded-full" style={{ background: meta.home.colors.primary }} />
        {meta.home.short_name}
      </span>
      <span className="flex items-center bg-white px-[0.9cqw] tabular-nums text-ink-950">
        {score?.home ?? 0}
        <span className="mx-[0.4cqw] text-ink-600">-</span>
        {score?.away ?? 0}
      </span>
      <span className="flex items-center gap-[0.55cqw] bg-ink-950/90 px-[0.9cqw] text-white">
        {meta.away.short_name}
        <span className="h-[1.5cqw] w-[0.32cqw] rounded-full" style={{ background: meta.away.colors.primary }} />
      </span>
      {minute && <span className="flex items-center bg-mint px-[0.8cqw] tabular-nums text-ink-950">{minute}</span>}
    </div>
  );
}

function teamStyle(meta: MatchMeta | null, side: TeamSide | null): CSSProperties {
  const color = side ? (teamOf(meta, side)?.colors.primary ?? "#34f5c5") : "#34f5c5";
  return { "--team": color } as CSSProperties;
}

const STRIPE = "bg-[linear-gradient(180deg,color-mix(in_oklab,var(--team)_55%,white),var(--team))]";

interface SlotProps {
  overlay: Overlay;
  meta: MatchMeta | null;
  kind: InsightKind | null;
  score: ScoreLine | null;
}

function LowerThird({ overlay, meta, kind }: SlotProps) {
  const team = overlay.team ? teamOf(meta, overlay.team) : null;
  const eyebrow = [kind ? kindName(overlay.language, kind) : null, team?.name].filter(Boolean).join(" · ");
  return (
    <div className="absolute bottom-[9%] start-[3.5%] w-[62%] animate-wipe-in rtl:animate-wipe-in-rtl">
      <div className="flex items-stretch overflow-hidden rounded-[0.7cqw] shadow-[0_1cqw_2.6cqw_rgb(0_0_0/0.5)]">
        <div className={`w-[0.65cqw] shrink-0 ${STRIPE}`} />
        <div className="glass min-w-0 flex-1 px-[1.6cqw] py-[1.15cqw]">
          <div className="eyebrow mb-[0.45cqw] flex items-center gap-[0.6cqw] text-[0.95cqw] text-mint">
            <span className="size-[0.6cqw] rounded-full bg-mint" />
            {eyebrow || "PitchMind"}
          </div>
          <div className="font-display text-[2.45cqw] font-bold uppercase leading-[1.02] text-white">{overlay.title}</div>
          <p className="mt-[0.55cqw] line-clamp-2 text-[1.2cqw] leading-snug text-slate-200">{overlay.body}</p>
        </div>
        {overlay.metric && (
          <div className="flex shrink-0 flex-col items-center justify-center bg-white px-[1.5cqw] text-ink-950">
            <div className="font-display text-[2.9cqw] font-extrabold leading-none tabular-nums">
              {metricValue(overlay.language, overlay.metric)}
            </div>
            <div className="eyebrow mt-[0.3cqw] text-[0.8cqw] text-ink-600">{metricLabel(overlay.language, overlay.metric)}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function PlayerTag({ overlay, meta }: SlotProps) {
  const player = findPlayer(meta, overlay.player_id);
  return (
    <div className="absolute bottom-[27%] end-[4%] animate-pop">
      <div className="glass flex items-center gap-[1cqw] rounded-full py-[0.5cqw] ps-[0.5cqw] pe-[1.7cqw] ring-1 ring-white/12 shadow-[0_1cqw_2.4cqw_rgb(0_0_0/0.5)]">
        <div
          className={`grid size-[3.9cqw] place-content-center rounded-full font-display text-[1.75cqw] font-extrabold text-white ${STRIPE}`}
        >
          {player?.number ?? ""}
        </div>
        <div className="min-w-0">
          <div className="font-display text-[1.75cqw] font-bold uppercase leading-none text-white">
            {player?.short_name ?? overlay.player_id ?? overlay.title}
          </div>
          <div className="eyebrow mt-[0.3cqw] text-[0.85cqw] text-mint">{overlay.title}</div>
        </div>
        {overlay.metric && (
          <div className="ms-[0.4cqw] font-display text-[3cqw] font-extrabold leading-none tabular-nums text-white">
            {metricValue(overlay.language, overlay.metric)}
            {overlay.metric.unit && (
              <span className="ms-[0.35cqw] text-[1.15cqw] font-semibold text-slate-300">{overlay.metric.unit}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatBubble({ overlay }: SlotProps) {
  return (
    <div className="absolute end-[3.5%] top-[6%] w-[19%] animate-pop">
      <div className="glass overflow-hidden rounded-[1cqw] ring-1 ring-white/12 shadow-[0_1cqw_2.4cqw_rgb(0_0_0/0.5)]">
        <div className={`h-[0.4cqw] ${STRIPE}`} />
        <div className="px-[1.3cqw] py-[1cqw]">
          <div className="eyebrow text-[0.85cqw] text-mint">{overlay.title}</div>
          {overlay.metric && (
            <div className="mt-[0.3cqw] font-display text-[3.4cqw] font-extrabold leading-none tabular-nums text-white">
              {metricValue(overlay.language, overlay.metric)}
              <span className="ms-[0.4cqw] text-[1.1cqw] font-semibold text-slate-300">
                {overlay.metric.unit ?? metricLabel(overlay.language, overlay.metric)}
              </span>
            </div>
          )}
          <p className="mt-[0.4cqw] line-clamp-2 text-[1cqw] leading-snug text-slate-300">{overlay.body}</p>
        </div>
      </div>
    </div>
  );
}

function Ticker({ overlay }: SlotProps) {
  const text = `${overlay.title} — ${overlay.body}`;
  return (
    <div className="absolute inset-x-0 bottom-0 flex h-[5.4%] items-stretch bg-ink-950/92 text-[1.25cqw] text-white">
      <div className="z-10 flex shrink-0 items-center bg-mint px-[1.2cqw] font-display font-extrabold uppercase text-ink-950">
        PitchMind
      </div>
      <div className="relative flex-1 overflow-hidden">
        <div className="absolute inset-y-0 flex w-max animate-ticker items-center whitespace-nowrap rtl:[animation-direction:reverse]">
          <span className="px-[2cqw]">{text}</span>
          <span className="px-[2cqw]" aria-hidden>
            {text}
          </span>
        </div>
      </div>
    </div>
  );
}

function RecapCard({ overlay, meta, score }: SlotProps) {
  return (
    <div className="absolute inset-0 grid place-items-center bg-ink-950/25">
      <div className="glass w-[58%] animate-pop overflow-hidden rounded-[1.3cqw] ring-1 ring-white/12 shadow-[0_2cqw_5cqw_rgb(0_0_0/0.6)]">
        <div className="h-[0.45cqw] bg-[linear-gradient(90deg,var(--color-mint),var(--color-sky),var(--color-violet))]" />
        <div className="px-[2.6cqw] py-[2.1cqw]">
          {meta && score && (
            <div dir="ltr" className="mb-[1.4cqw] flex items-center justify-center gap-[1.6cqw]">
              <TeamCrest team={meta.home} className="h-[4.2cqw] w-auto" />
              <div className="font-display text-[4.2cqw] font-extrabold leading-none tabular-nums text-white">
                {score.home}
                <span className="mx-[0.8cqw] text-slate-500">-</span>
                {score.away}
              </div>
              <TeamCrest team={meta.away} className="h-[4.2cqw] w-auto" />
            </div>
          )}
          <div className="font-display text-[2.7cqw] font-bold uppercase leading-[1.05] text-white">{overlay.title}</div>
          <p className="mt-[0.9cqw] text-[1.35cqw] leading-relaxed text-slate-200">{overlay.body}</p>
        </div>
      </div>
    </div>
  );
}

const SLOTS = {
  lower_third: LowerThird,
  player_tag: PlayerTag,
  stat_bubble: StatBubble,
  ticker: Ticker,
  recap_card: RecapCard,
} as const;

/** Every overlay on air, each in its slot. The parent decides what is on air. */
export function OverlayLayer({
  overlays,
  meta,
  kinds,
  score,
}: {
  overlays: readonly Overlay[];
  meta: MatchMeta | null;
  kinds: Readonly<Record<string, InsightKind>>;
  score: ScoreLine | null;
}) {
  return (
    <div className="pointer-events-none absolute inset-0" aria-live="polite">
      {overlays.map((overlay) => {
        const Slot = SLOTS[overlay.slot];
        return (
          <div
            key={overlay.overlay_id}
            data-testid={`overlay-${overlay.slot}`}
            data-overlay-id={overlay.overlay_id}
            dir={overlay.rtl ? "rtl" : "ltr"}
            lang={overlay.language}
            className="absolute inset-0"
            style={teamStyle(meta, overlay.team)}
          >
            <Slot overlay={overlay} meta={meta} kind={overlay.insight_id ? (kinds[overlay.insight_id] ?? null) : null} score={score} />
          </div>
        );
      })}
    </div>
  );
}

/** A stylised pitch under a broadcast camera angle, with the last on-ball action pulsing. */
export function Pitch({ lastEvent }: { lastEvent: MatchEvent | null }) {
  const id = useId();
  // Coordinates are relative to the acting team; draw home attacking right, away flipped.
  const spot = lastEvent?.end ?? lastEvent?.start ?? null;
  const [x, y] = spot ? (lastEvent?.team === "away" ? [105 - spot[0], 68 - spot[1]] : spot) : [0, 0];
  return (
    <div className="absolute inset-0 overflow-hidden bg-[radial-gradient(120%_90%_at_50%_0%,#1d6b45_0%,#0f4a2f_45%,#06231a_100%)]">
      <div className="absolute inset-x-[-12%] bottom-[-8%] top-[18%] [transform:perspective(900px)_rotateX(38deg)]">
        <svg viewBox="-4 -4 113 76" className="h-full w-full" preserveAspectRatio="none" aria-hidden>
          <defs>
            <pattern id={`${id}-stripes`} width="10.5" height="68" patternUnits="userSpaceOnUse">
              <rect width="5.25" height="68" fill="white" opacity="0.035" />
            </pattern>
          </defs>
          <rect x="0" y="0" width="105" height="68" fill={`url(#${id}-stripes)`} />
          <g fill="none" stroke="white" strokeOpacity="0.38" strokeWidth="0.35">
            <rect x="0" y="0" width="105" height="68" />
            <line x1="52.5" y1="0" x2="52.5" y2="68" />
            <circle cx="52.5" cy="34" r="9.15" />
            <rect x="0" y="13.84" width="16.5" height="40.32" />
            <rect x="88.5" y="13.84" width="16.5" height="40.32" />
            <rect x="0" y="24.84" width="5.5" height="18.32" />
            <rect x="99.5" y="24.84" width="5.5" height="18.32" />
          </g>
          {spot && (
            <g>
              <circle cx={x} cy={y} r="1.6" fill="#34f5c5" opacity="0.9" />
              <circle cx={x} cy={y} r="1.6" fill="none" stroke="#34f5c5" strokeWidth="0.4" className="origin-center animate-ping-slow [transform-box:fill-box]" />
            </g>
          )}
        </svg>
      </div>
      <div className="absolute inset-0 bg-[radial-gradient(80%_70%_at_50%_45%,transparent_40%,rgb(0_0_0/0.55)_100%)]" />
    </div>
  );
}

export function LiveTag({ label }: { label: string }) {
  return (
    <div className="absolute right-[3%] top-[5%] flex items-center gap-[0.5cqw] rounded-[0.4cqw] bg-live px-[0.8cqw] py-[0.35cqw] font-display text-[1.1cqw] font-bold uppercase tracking-wide text-white">
      <span className="size-[0.55cqw] animate-blink rounded-full bg-white" />
      {label}
    </div>
  );
}

export function kindsOf(insights: ReadonlyArray<{ id: string; kind: InsightKind }>): Record<string, InsightKind> {
  return Object.fromEntries(insights.map((i) => [i.id, i.kind]));
}

export type { Language };

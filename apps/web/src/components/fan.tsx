"use client";

import { useState, type CSSProperties } from "react";

import type {
  AgentName,
  Insight,
  InsightKind,
  Language,
  MatchEvent,
  MatchMeta,
  Moment,
  Persona,
  StatSnapshot,
  Team,
  TeamSide,
} from "@/lib/contracts";
import { broadcastMinute, formatNumber, formatPercent } from "@/lib/format";
import { eventTypeName, kindName, LANGUAGE_NAMES, personaName, phaseName, t } from "@/lib/i18n";
import {
  citedEvents,
  currentMinute,
  eventsOf,
  findPlayer,
  latestSnapshot,
  minuteOf,
  playerName,
  team as teamOf,
  type MatchState,
} from "@/lib/match";
import { LANGUAGES, PERSONAS, type Profile } from "@/lib/segments";

import { TeamCrest } from "./broadcast";
import { Badge, CheckIcon, SectionTitle, Segmented, SparkIcon } from "./ui";

/** A team colour lifted enough to read on the dark theme. */
function bright(color: string | undefined, amount = 35): string {
  return `color-mix(in oklab, ${color ?? "#64748b"} ${100 - amount}%, white)`;
}

// ---------------------------------------------------------------------------
// Match header
// ---------------------------------------------------------------------------

function TeamBlock({ team, align }: { team: Team | null; align: "start" | "end" }) {
  return (
    <div className={`flex min-w-0 items-center gap-3 ${align === "end" ? "flex-row-reverse text-end" : ""}`}>
      <TeamCrest team={team} size={52} className="shrink-0 drop-shadow-[0_6px_14px_rgb(0_0_0/0.5)]" />
      <div className="min-w-0">
        <div className="truncate font-display text-xl font-bold uppercase leading-tight text-white sm:text-2xl">
          {team?.name ?? "—"}
        </div>
        <div className="text-xs font-medium tracking-wide text-slate-400">{team?.formation}</div>
      </div>
    </div>
  );
}

export function MatchHeader({ state, language }: { state: MatchState; language: Language }) {
  const meta = state.meta;
  const snapshot = latestSnapshot(state);
  const now = currentMinute(state);
  const running = now?.phase === "first_half" || now?.phase === "second_half";
  return (
    <section data-testid="match-header" className="panel relative overflow-hidden px-4 py-4 sm:px-6">
      <div
        className="pointer-events-none absolute -start-24 -top-24 size-64 rounded-full opacity-40 blur-3xl"
        style={{ background: meta?.home.colors.primary }}
      />
      <div
        className="pointer-events-none absolute -end-24 -top-24 size-64 rounded-full opacity-35 blur-3xl"
        style={{ background: meta?.away.colors.primary }}
      />
      <div className="relative grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 sm:gap-6">
        <TeamBlock team={meta?.home ?? null} align="start" />
        <div className="text-center">
          <div data-testid="score" className="flex items-center justify-center gap-3 font-display text-5xl font-extrabold leading-none tabular-nums text-white sm:text-6xl">
            <span>{snapshot?.score.home ?? 0}</span>
            <span className="text-3xl text-slate-500">–</span>
            <span>{snapshot?.score.away ?? 0}</span>
          </div>
          <div className="mt-2 flex items-center justify-center gap-2 text-sm">
            {running && <span className="size-2 animate-blink rounded-full bg-live" />}
            <span data-testid="minute" className="font-display text-lg font-bold tabular-nums text-mint">
              {now ? broadcastMinute(now.minute, now.phase) : "0'"}
            </span>
            <span className="text-slate-400">{phaseName(language, now?.phase ?? "pre_match")}</span>
          </div>
        </div>
        <TeamBlock team={meta?.away ?? null} align="end" />
      </div>
      {meta && (
        <div className="relative mt-3 text-center text-xs text-slate-500">
          {meta.competition} · {meta.venue}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export function ProfilePanel({
  profile,
  onChange,
  meta,
  segment,
  effective,
}: {
  profile: Profile;
  onChange: (profile: Profile) => void;
  meta: MatchMeta | null;
  segment: string;
  effective: string;
}) {
  const language = profile.language;
  const clubOptions: Array<{ value: "neutral" | TeamSide; label: React.ReactNode }> = [
    { value: "neutral", label: t(language, "neutral") },
    ...(["home", "away"] as const).map((side) => ({
      value: side,
      label: (
        <span className="flex min-w-0 items-center gap-1.5">
          <TeamCrest team={teamOf(meta, side)} size={14} />
          <span className="truncate">{teamOf(meta, side)?.short_name ?? side}</span>
        </span>
      ),
    })),
  ];
  return (
    <section data-testid="profile-panel" className="panel space-y-4 p-4">
      <SectionTitle>{t(language, "yourView")}</SectionTitle>
      <Field label={t(language, "style")}>
        <Segmented<Persona>
          label={t(language, "style")}
          testId="persona-picker"
          value={profile.persona}
          onChange={(persona) => onChange({ ...profile, persona })}
          options={PERSONAS.map((p) => ({ value: p, label: personaName(language, p) }))}
        />
      </Field>
      <Field label={t(language, "language")}>
        <Segmented<Language>
          label={t(language, "language")}
          testId="language-picker"
          value={profile.language}
          onChange={(next) => onChange({ ...profile, language: next })}
          options={LANGUAGES.map((l) => ({
            value: l,
            label: <span lang={l}>{LANGUAGE_NAMES[l]}</span>,
          }))}
        />
      </Field>
      <Field label={t(language, "club")}>
        <Segmented<"neutral" | TeamSide>
          label={t(language, "club")}
          testId="club-picker"
          value={profile.club ?? "neutral"}
          onChange={(club) => onChange({ ...profile, club: club === "neutral" ? null : club })}
          options={clubOptions}
        />
      </Field>
      <Field label={t(language, "followPlayer")}>
        <select
          data-testid="player-picker"
          value={profile.player ?? ""}
          onChange={(event) => onChange({ ...profile, player: event.target.value || null })}
          className="w-full rounded-xl bg-ink-950/60 px-3 py-2 text-sm text-slate-100 ring-1 ring-white/10 outline-none focus:ring-mint/50"
        >
          <option value="">{t(language, "nobody")}</option>
          {meta &&
            (["home", "away"] as const).map((side) => (
              <optgroup key={side} label={meta[side].name}>
                {meta[side].players.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.number}. {p.name} ({p.position})
                  </option>
                ))}
              </optgroup>
            ))}
        </select>
      </Field>
      <div className="rounded-xl bg-ink-950/50 px-3 py-2 ring-1 ring-white/5">
        <div className="eyebrow text-[0.62rem] text-slate-500">Segment</div>
        <code dir="ltr" data-testid="segment-key" className="block font-mono text-[0.72rem] text-slate-300">
          {segment.split("|").map((part, i) => (
            <span key={i}>
              {i > 0 && "|"}
              {i > 0 && <wbr />}
              {part}
            </span>
          ))}
        </code>
        {effective !== segment && (
          <div className="mt-1.5 text-[0.72rem] text-gold">
            {t(language, "closest")}:{" "}
            <code dir="ltr" className="font-mono">
              {effective}
            </code>
          </div>
        )}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-slate-400">{label}</div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

const KIND_STYLE: Record<InsightKind, { bar: string; text: string }> = {
  explanation: { bar: "bg-mint", text: "text-mint" },
  commentary: { bar: "bg-live", text: "text-live" },
  stat_alert: { bar: "bg-violet", text: "text-violet" },
  milestone: { bar: "bg-sky", text: "text-sky" },
  recap: { bar: "bg-gold", text: "text-gold" },
};

export function InsightFeed({
  state,
  insights,
  language,
}: {
  state: MatchState;
  insights: readonly Insight[];
  language: Language;
}) {
  return (
    <section data-testid="insight-feed" className="panel p-4">
      <SectionTitle aside={<Badge tone="slate">{insights.length}</Badge>}>
        <span className="inline-flex items-center gap-2">
          <SparkIcon className="text-mint" /> {t(language, "insights")}
        </span>
      </SectionTitle>
      {insights.length === 0 ? (
        <p className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">
          {t(language, "noInsights")}
        </p>
      ) : (
        <ol className="space-y-3">
          {insights.map((insight) => (
            <InsightCard key={insight.id} insight={insight} state={state} language={language} />
          ))}
        </ol>
      )}
    </section>
  );
}

function InsightCard({ insight, state, language }: { insight: Insight; state: MatchState; language: Language }) {
  const [open, setOpen] = useState(false);
  const minute = minuteOf(state, insight);
  const style = KIND_STYLE[insight.kind];
  return (
    <li
      data-testid="insight-card"
      data-insight-id={insight.id}
      data-fallback={insight.fallback}
      className="relative animate-rise overflow-hidden rounded-2xl bg-ink-850/80 ring-1 ring-white/7"
    >
      <div className={`absolute inset-y-0 start-0 w-1 ${style.bar}`} />
      <div className="p-4 ps-5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={`eyebrow ${style.text}`}>{kindName(language, insight.kind)}</span>
          {minute && (
            <span className="font-display text-sm font-semibold tabular-nums text-slate-400">
              {broadcastMinute(minute.minute, minute.phase)}
            </span>
          )}
          <span className="ms-auto flex items-center gap-1.5">
            {insight.verified && (
              <Badge tone="mint" title={t(language, "verified")}>
                <CheckIcon width={12} height={12} /> {t(language, "verified")}
              </Badge>
            )}
            {insight.fallback && (
              <Badge tone="gold" title={t(language, "autoHint")} testId="auto-badge">
                {t(language, "auto")}
              </Badge>
            )}
          </span>
        </div>
        <h3 className="mt-1.5 font-display text-[1.35rem] font-bold leading-tight text-white">{insight.headline}</h3>
        <p className="mt-1 text-[0.95rem] leading-relaxed text-slate-300">{insight.body}</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            data-testid="why-button"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className={`rounded-full px-3.5 py-1 text-sm font-semibold ring-1 transition ${
              open ? "bg-mint text-ink-950 ring-mint" : "text-mint ring-mint/40 hover:bg-mint/10"
            }`}
          >
            {open ? t(language, "hide") : t(language, "why")}
          </button>
          <AgentTrace trace={insight.agent_trace} />
          {insight.latency_ms != null && (
            <span className="ms-auto text-xs tabular-nums text-slate-500" title="End-to-end agent latency">
              {(insight.latency_ms / 1000).toFixed(1)} s
            </span>
          )}
        </div>
        {open && <WhyPanel insight={insight} state={state} language={language} />}
      </div>
    </li>
  );
}

export function AgentTrace({ trace }: { trace: readonly AgentName[] }) {
  return (
    <span dir="ltr" className="flex flex-wrap items-center gap-1 text-[0.65rem] text-slate-500" title="Agents that handled this insight">
      {trace.map((agent, i) => (
        <span key={`${agent}-${i}`} className="flex items-center gap-1">
          {i > 0 && <span className="text-slate-600">›</span>}
          <span className={agent === "template" ? "text-gold" : agent === "verifier" ? "text-mint/80" : ""}>{agent}</span>
        </span>
      ))}
    </span>
  );
}

function eventDetail(event: MatchEvent, meta: MatchMeta | null, language: Language): string {
  const parts: string[] = [];
  const who = playerName(meta, event.player);
  const to = playerName(meta, event.receiver);
  if (who) parts.push(to ? `${who} → ${to}` : who);
  if (event.outcome) parts.push(event.outcome.replaceAll("_", " "));
  if (event.ball_speed_kmh != null) parts.push(`${formatNumber(event.ball_speed_kmh, language, 1)} km/h`);
  if (event.player_speed_kmh != null) parts.push(`${formatNumber(event.player_speed_kmh, language, 1)} km/h`);
  if (event.distance_m != null) parts.push(`${formatNumber(event.distance_m, language, 1)} m`);
  if (event.under_pressure) parts.push("under pressure");
  return parts.join(" · ");
}

function WhyPanel({ insight, state, language }: { insight: Insight; state: MatchState; language: Language }) {
  const events = citedEvents(state, insight);
  return (
    <div data-testid="why-panel" className="mt-3 animate-rise space-y-3 rounded-xl bg-ink-950/70 p-3 ring-1 ring-white/6">
      <div>
        <div className="eyebrow mb-2 text-slate-400">{t(language, "claims")}</div>
        <ul className="space-y-2.5">
          {insight.claims.map((claim, i) => (
            <li key={i} className="text-sm leading-snug text-slate-200">
              <p>{claim.text}</p>
              <div dir="ltr" className="mt-1.5 flex flex-wrap gap-1.5">
                {claim.evidence.map((id) => (
                  <span
                    key={id}
                    data-testid="evidence-id"
                    className="rounded-md bg-sky/12 px-1.5 py-0.5 font-mono text-[0.7rem] text-sky ring-1 ring-sky/20"
                  >
                    #{id}
                  </span>
                ))}
                {Object.entries(claim.metrics).map(([name, value]) => (
                  <span key={name} className="rounded-md bg-white/5 px-1.5 py-0.5 font-mono text-[0.7rem] text-slate-300">
                    <span className="text-slate-500">{name}</span> {formatNumber(value, "en", 3)}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </div>
      {events.length > 0 && (
        <div>
          <div className="eyebrow mb-2 text-slate-400">{t(language, "citedEvents")}</div>
          <ul data-testid="cited-events" className="divide-y divide-white/5 overflow-hidden rounded-lg ring-1 ring-white/5">
            {events.map((event) => (
              <li key={event.id} className="grid grid-cols-[auto_auto_1fr] items-baseline gap-x-3 bg-ink-900/60 px-3 py-2 text-xs">
                <span dir="ltr" className="font-mono text-sky">
                  #{event.id}
                </span>
                <span className="font-display text-sm font-semibold tabular-nums text-slate-300">
                  {broadcastMinute(event.minute, event.phase)}
                </span>
                <span className="min-w-0">
                  <span className="font-semibold text-white">{eventTypeName(language, event.type)}</span>
                  <span className="text-slate-400"> · {eventDetail(event, state.meta, language)}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

function DualBar({
  label,
  home,
  away,
  format,
  meta,
}: {
  label: string;
  home: number;
  away: number;
  format: (value: number) => string;
  meta: MatchMeta | null;
}) {
  const total = home + away;
  const share = total > 0 ? home / total : 0.5;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-display text-base font-bold tabular-nums text-white">{format(home)}</span>
        <span className="text-xs text-slate-400">{label}</span>
        <span className="font-display text-base font-bold tabular-nums text-white">{format(away)}</span>
      </div>
      <div className="mt-1 flex h-1.5 gap-1">
        <div className="rounded-full transition-[flex-grow] duration-700" style={{ flexGrow: share, background: bright(meta?.home.colors.primary) }} />
        <div className="rounded-full transition-[flex-grow] duration-700" style={{ flexGrow: 1 - share, background: bright(meta?.away.colors.primary, 10) }} />
      </div>
    </div>
  );
}

export function MomentumChart({
  snapshots,
  moments,
  meta,
  duration,
  clock,
  language,
}: {
  snapshots: readonly StatSnapshot[];
  moments: readonly Moment[];
  meta: MatchMeta | null;
  duration: number;
  clock: number;
  language: Language;
}) {
  const W = 320;
  const H = 120;
  const mid = H / 2;
  const span = Math.max(duration, clock, 1);
  const x = (t: number) => (t / span) * W;
  const y = (m: number) => mid - m * (mid - 10);
  const points = snapshots.filter((s) => s.t <= clock).map((s) => [x(s.t), y(s.momentum)] as const);
  const line = points.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const area = points.length > 1 ? `M${points[0]?.[0] ?? 0},${mid} ${line.replace(/^M/, "L")} L${points.at(-1)?.[0] ?? 0},${mid} Z` : "";
  const halfTime = moments.find((m) => m.kind === "phase" && m.t < span * 0.75);
  const goals = moments.filter((m) => m.kind === "goal" && m.t <= clock);
  const home = bright(meta?.home.colors.primary, 30);
  const away = bright(meta?.away.colors.primary, 5);
  return (
    <div dir="ltr" data-testid="momentum-chart">
      <div className="mb-1 flex items-center justify-between text-[0.7rem] font-semibold uppercase tracking-wider">
        <span style={{ color: home }}>{meta?.home.short_name ?? "HOME"} ▲</span>
        <span className="text-slate-500">{t(language, "momentum")}</span>
        <span style={{ color: away }}>▼ {meta?.away.short_name ?? "AWAY"}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-32 w-full overflow-visible" role="img" aria-label="Momentum over the match">
        <defs>
          <clipPath id="mm-top">
            <rect x="0" y="0" width={W} height={mid} />
          </clipPath>
          <clipPath id="mm-bottom">
            <rect x="0" y={mid} width={W} height={mid} />
          </clipPath>
        </defs>
        <rect x="0" y="0" width={W} height={H} rx="10" fill="rgb(255 255 255 / 0.025)" />
        <line x1="0" x2={W} y1={mid} y2={mid} stroke="rgb(255 255 255 / 0.15)" strokeDasharray="3 4" />
        {halfTime && (
          <line x1={x(halfTime.t)} x2={x(halfTime.t)} y1="6" y2={H - 6} stroke="rgb(255 255 255 / 0.18)" strokeDasharray="2 3" />
        )}
        {area && (
          <>
            <path d={area} fill={home} opacity="0.35" clipPath="url(#mm-top)" />
            <path d={area} fill={away} opacity="0.35" clipPath="url(#mm-bottom)" />
            <path d={line} fill="none" stroke="white" strokeOpacity="0.85" strokeWidth="1.6" strokeLinejoin="round" />
          </>
        )}
        {goals.map((g) => (
          <g key={g.id} transform={`translate(${x(g.t)},${g.team === "away" ? H - 9 : 9})`}>
            <circle r="5.5" fill="#ffc94d" />
            <circle r="2" fill="#04070d" />
          </g>
        ))}
        <line x1={x(clock)} x2={x(clock)} y1="4" y2={H - 4} stroke="#34f5c5" strokeOpacity="0.7" />
      </svg>
    </div>
  );
}

function Meter({ value, left, right }: { value: number; left: string; right: string }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-[0.7rem] text-slate-400">
        <span>{left}</span>
        <span>{right}</span>
      </div>
      <div dir="ltr" className="relative h-2 rounded-full bg-[linear-gradient(90deg,#5cc8ff,#9b8cff,#ff3d5a)]">
        <div
          className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow ring-2 ring-ink-900 transition-[left] duration-700"
          style={{ left: `${Math.round(value * 100)}%` }}
        />
      </div>
    </div>
  );
}

export function StatsPanel({ state, language }: { state: MatchState; language: Language }) {
  const snapshot = latestSnapshot(state);
  const meta = state.meta;
  const n = (v: number, d = 2) => formatNumber(v, language, d);
  return (
    <section data-testid="stats-panel" className="panel space-y-4 p-4">
      <SectionTitle>{t(language, "stats")}</SectionTitle>
      <MomentumChart
        snapshots={state.snapshots}
        moments={Object.values(state.moments)}
        meta={meta}
        duration={state.catalog?.duration ?? 5800}
        clock={state.clock}
        language={language}
      />
      {snapshot ? (
        <div className="space-y-3">
          <DualBar label={t(language, "possession")} home={snapshot.home.possession_pct} away={snapshot.away.possession_pct} format={(v) => formatPercent(v, language)} meta={meta} />
          <DualBar label={t(language, "shots")} home={snapshot.home.shots} away={snapshot.away.shots} format={(v) => n(v, 0)} meta={meta} />
          <DualBar label={t(language, "onTarget")} home={snapshot.home.shots_on_target} away={snapshot.away.shots_on_target} format={(v) => n(v, 0)} meta={meta} />
          <DualBar label={t(language, "xg")} home={snapshot.home.xg} away={snapshot.away.xg} format={(v) => n(v)} meta={meta} />
          <DualBar label={t(language, "passAccuracy")} home={snapshot.home.pass_accuracy_pct} away={snapshot.away.pass_accuracy_pct} format={(v) => formatPercent(v, language)} meta={meta} />
          <DualBar label={t(language, "pressure")} home={snapshot.home.pressure_index} away={snapshot.away.pressure_index} format={(v) => n(v)} meta={meta} />
          <DualBar label={t(language, "tackles")} home={snapshot.home.tackles_won} away={snapshot.away.tackles_won} format={(v) => n(v, 0)} meta={meta} />
          <DualBar label={t(language, "distance")} home={snapshot.home.distance_covered_m / 1000} away={snapshot.away.distance_covered_m / 1000} format={(v) => n(v, 1)} meta={meta} />
          <div className="grid gap-3 pt-1">
            <Meter value={snapshot.control_chaos} left={t(language, "control")} right={t(language, "chaos")} />
            <div className="flex items-baseline justify-between rounded-xl bg-ink-950/50 px-3 py-2 ring-1 ring-white/5">
              <span className="text-xs text-slate-400">{t(language, "rhythm")}</span>
              <span className="font-display text-lg font-bold tabular-nums text-white">
                {n(snapshot.rhythm_epm, 1)} <span className="text-xs font-medium text-slate-400">{t(language, "perMinute")}</span>
              </span>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-500">…</p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Player focus
// ---------------------------------------------------------------------------

const ATTRIBUTES = ["pace", "passing", "finishing", "dribbling", "defending", "stamina"] as const;

export function PlayerFocus({
  state,
  playerId,
  insights,
  language,
  onPick,
}: {
  state: MatchState;
  playerId: string | null;
  insights: readonly Insight[];
  language: Language;
  onPick: (playerId: string) => void;
}) {
  const meta = state.meta;
  const player = findPlayer(meta, playerId);
  if (!player) {
    const counts = new Map<string, number>();
    for (const moment of Object.values(state.moments)) {
      for (const id of moment.players) counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    const stars = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([id]) => findPlayer(meta, id)).filter((p) => p !== null);
    return (
      <section data-testid="player-focus" className="panel p-4">
        <SectionTitle>{t(language, "playerFocus")}</SectionTitle>
        <p className="text-sm text-slate-400">{t(language, "pickPlayer")}</p>
        {stars.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {stars.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onPick(p.id)}
                className="flex items-center gap-2 rounded-full bg-white/5 py-1 ps-1 pe-3 text-sm text-slate-200 ring-1 ring-white/10 transition hover:bg-white/10"
              >
                <span className="grid size-6 place-content-center rounded-full font-display text-xs font-bold text-white" style={{ background: teamOf(meta, p.side)?.colors.primary }}>
                  {p.number}
                </span>
                {p.short_name}
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }
  const team = teamOf(meta, player.side);
  const events = eventsOf(state, player.id).slice(0, 8);
  const theirs = insights.filter(
    (i) => i.segment.player === player.id || (i.moment_id && state.moments[i.moment_id]?.players.includes(player.id)),
  );
  return (
    <section data-testid="player-focus" className="panel overflow-hidden p-0">
      <div className="relative p-4" style={{ "--team": team?.colors.primary } as CSSProperties}>
        <div className="absolute inset-0 bg-[linear-gradient(135deg,color-mix(in_oklab,var(--team)_45%,transparent),transparent_70%)]" />
        <div className="relative flex items-center gap-3">
          <div className="grid size-14 shrink-0 place-content-center rounded-2xl bg-ink-950/60 font-display text-3xl font-extrabold text-white ring-1 ring-white/15">
            {player.number}
          </div>
          <div className="min-w-0">
            <div className="eyebrow text-slate-300">{t(language, "playerFocus")}</div>
            <div className="truncate font-display text-2xl font-bold uppercase leading-tight text-white">{player.name}</div>
            <div className="text-xs text-slate-300">
              {player.position} · {player.nationality} · {team?.short_name}
            </div>
          </div>
        </div>
      </div>
      <div className="space-y-4 p-4 pt-2">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {ATTRIBUTES.map((name) => (
            <div key={name}>
              <div className="flex justify-between text-[0.7rem] text-slate-400">
                <span>{t(language, name)}</span>
                <span className="tabular-nums text-slate-200">{player.attributes[name]}</span>
              </div>
              <div className="mt-1 h-1 rounded-full bg-white/8">
                <div className="h-full rounded-full bg-mint" style={{ width: `${player.attributes[name]}%` }} />
              </div>
            </div>
          ))}
        </div>
        <div>
          <div className="eyebrow mb-2 text-slate-400">{t(language, "involvement")}</div>
          {events.length === 0 ? (
            <p className="text-sm text-slate-500">{t(language, "noInvolvement")}</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {events.map((event) => (
                <li key={event.id} className="flex items-baseline gap-2">
                  <span className="w-11 shrink-0 font-display font-semibold tabular-nums text-slate-400">
                    {broadcastMinute(event.minute, event.phase)}
                  </span>
                  <span className="text-slate-200">{eventTypeName(language, event.type)}</span>
                  <span className="truncate text-xs text-slate-500">{eventDetail(event, meta, language)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {theirs.length > 0 && (
          <div>
            <div className="eyebrow mb-2 text-slate-400">{t(language, "playerInsights")}</div>
            <ul className="space-y-2">
              {theirs.slice(0, 4).map((insight) => {
                const minute = minuteOf(state, insight);
                return (
                  <li key={insight.id} className="rounded-xl bg-ink-950/50 px-3 py-2 ring-1 ring-white/5">
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                      {minute && <span className="font-display font-semibold tabular-nums">{broadcastMinute(minute.minute, minute.phase)}</span>}
                      <span>{kindName(language, insight.kind)}</span>
                    </div>
                    <div className="font-display text-base font-bold leading-snug text-white">{insight.headline}</div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

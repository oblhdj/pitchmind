"use client";

import { setDecision, clearDecisions, useHeld, type Decision } from "@/lib/approvals";
import { decisionEntry, recordAudit, releaseEntry, useAuditLog, type AuditEntry } from "@/lib/audit";
import type { Insight } from "@/lib/contracts";
import { broadcastMinute } from "@/lib/format";
import { kindName, LANGUAGE_NAMES, personaName, isRtl } from "@/lib/i18n";
import { currentMinute, insightsFor, knownSegments, minuteOf, playerName, scoreLine, type MatchState } from "@/lib/match";
import type { FeedParams } from "@/lib/options";
import { parseSegmentKey } from "@/lib/segments";
import { useMatch, useNow } from "@/lib/useMatch";

import { TeamCrest } from "./broadcast";
import { Brand, BroadcastFrame, ReplayControls, StatusPill } from "./controls";
import { AgentTrace, Waiting } from "./fan";
import { Badge, CheckIcon, ChevronIcon } from "./ui";

/** The producer's view: every active segment side by side, with a hold / approve switch per insight. */
export function Studio({ feed, segments }: { feed: FeedParams; segments: readonly string[] }) {
  const { state, controls, speed } = useMatch({
    mode: feed.mode,
    segment: null,
    liveSegments: feed.mode === "live" ? segments : undefined,
    speed: feed.speed,
    from: feed.from,
  });
  const now = useNow();
  const held = useHeld();
  const keys = feed.mode === "mock" ? knownSegments(state) : segments;
  const all = state.insights;
  const heldNow = all.filter((i) => held.has(i.id)).length;
  const latencies = all.map((i) => i.latency_ms).filter((v): v is number => v != null && v > 0);
  const avgLatency = latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length / 1000 : null;
  const score = scoreLine(state);
  const releaseAll = () => {
    clearDecisions();
    if (heldNow > 0) recordAudit(releaseEntry(heldNow, currentMinute(state), Date.now()));
  };

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-white/5 bg-ink-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3">
          <Brand sub="Studio · human in the loop" />
          <StatusPill mode={feed.mode} state={state} />
          {state.meta && (
            <div dir="ltr" className="flex items-center gap-2 font-display text-lg font-bold">
              <TeamCrest team={state.meta.home} size={20} />
              {state.meta.home.short_name}
              <span className="tabular-nums text-white">
                {score.home}-{score.away}
              </span>
              {state.meta.away.short_name}
              <TeamCrest team={state.meta.away} size={20} />
              {score.minute != null && <span className="ms-1 text-mint tabular-nums">{broadcastMinute(score.minute, score.phase)}</span>}
            </div>
          )}
          <ReplayControls mode={feed.mode} state={state} speed={speed} controls={controls} />
        </div>
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-2 px-4 pb-3 text-xs">
          <Stat label="Segments" value={keys.length} />
          <Stat label="Insights" value={all.length} />
          <Stat label="On air" value={all.length - heldNow} tone="mint" />
          <Stat label="Held" value={heldNow} tone="gold" />
          <Stat label="Template fallback" value={all.filter((i) => i.fallback).length} tone="gold" />
          <Stat label="Verified" value={`${all.length ? Math.round((all.filter((i) => i.verified).length / all.length) * 100) : 100}%`} tone="mint" />
          {avgLatency != null && <Stat label="Avg agent latency" value={`${avgLatency.toFixed(1)} s`} />}
          <button
            type="button"
            onClick={releaseAll}
            className="ms-auto rounded-lg px-3 py-1.5 text-slate-300 ring-1 ring-white/10 transition hover:bg-white/5 hover:text-white"
          >
            Release all holds
          </button>
        </div>
      </header>

      <AuditTrail state={state} />

      <main data-testid="studio-grid" className="mx-auto grid max-w-[1800px] gap-4 px-4 py-5 md:grid-cols-2 2xl:grid-cols-4">
        {keys.length === 0 && <Waiting title="Waiting for the match feed" hint="Every segment appears here side by side once the feed starts." />}
        {keys.map((key) => (
          <SegmentColumn key={key} segment={key} state={state} now={now} held={held} />
        ))}
      </main>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "mint" | "gold" }) {
  const color = tone === "mint" ? "text-mint" : tone === "gold" ? "text-gold" : "text-white";
  return (
    <span className="flex items-baseline gap-1.5 rounded-lg bg-white/4 px-2.5 py-1 ring-1 ring-white/6">
      <span className="text-slate-400">{label}</span>
      <span className={`font-display text-sm font-bold tabular-nums ${color}`}>{value}</span>
    </span>
  );
}

const ACTIONS: Record<AuditEntry["action"], { label: string; tone: "mint" | "gold" | "slate" }> = {
  approved: { label: "On air", tone: "mint" },
  held: { label: "Hold", tone: "gold" },
  released_all: { label: "Release all", tone: "slate" },
};

function segmentLabel(key: string, state: MatchState): string {
  const profile = parseSegmentKey(key);
  if (!profile) return key;
  const parts = [personaName("en", profile.persona), LANGUAGE_NAMES[profile.language]];
  if (profile.club) parts.push(`fan of ${state.meta?.[profile.club].short_name ?? profile.club}`);
  if (profile.player) parts.push(`follows ${playerName(state.meta, profile.player)}`);
  return parts.join(" · ");
}

/** Every hold / approve decision of this browser's studio tabs, newest first. */
function AuditTrail({ state }: { state: MatchState }) {
  const log = useAuditLog();
  return (
    <section className="mx-auto max-w-[1800px] px-4 pt-5">
      <details open data-testid="audit-trail" className="panel group px-3 py-2">
        <summary className="flex cursor-pointer list-none items-center gap-2 py-1 [&::-webkit-details-marker]:hidden">
          <span className="eyebrow text-slate-400">Audit trail</span>
          <Badge>{log.length}</Badge>
          <span className="text-xs text-slate-500">hold / approve decisions, newest first</span>
          <ChevronIcon className="ms-auto text-slate-500 transition group-open:rotate-180" />
        </summary>
        {log.length === 0 ? (
          <p className="py-2 text-xs text-slate-500">No decisions yet: every hold and approve is logged here.</p>
        ) : (
          <ol className="mt-1 max-h-44 divide-y divide-white/5 overflow-y-auto text-xs">
            {log.map((entry) => (
              <li
                key={entry.id}
                data-testid="audit-entry"
                data-action={entry.action}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5"
              >
                <time dateTime={new Date(entry.at).toISOString()} className="font-mono tabular-nums text-slate-400">
                  {new Date(entry.at).toLocaleTimeString("en-GB", { hour12: false })}
                </time>
                <span className="w-12 font-display text-sm font-semibold tabular-nums text-slate-300">
                  {entry.minute != null ? broadcastMinute(entry.minute, entry.phase) : "—"}
                </span>
                <Badge tone={ACTIONS[entry.action].tone}>{ACTIONS[entry.action].label}</Badge>
                {entry.action === "released_all" ? (
                  <span className="text-slate-300">
                    {entry.count} held insight{entry.count === 1 ? "" : "s"} back on air
                  </span>
                ) : (
                  <>
                    <span className="text-slate-400">{segmentLabel(entry.segment, state)}</span>
                    {/* At least 12rem: on a phone it wraps to its own line rather than shrink to "…". */}
                    <span dir="auto" data-testid="audit-headline" className="min-w-48 flex-1 truncate text-left font-semibold text-white">
                      {entry.headline}
                    </span>
                    <code dir="ltr" className="font-mono text-[0.65rem] text-slate-500">
                      {entry.insightId}
                    </code>
                  </>
                )}
              </li>
            ))}
          </ol>
        )}
      </details>
    </section>
  );
}

function SegmentColumn({
  segment,
  state,
  now,
  held,
}: {
  segment: string;
  state: MatchState;
  now: number;
  held: ReadonlySet<string>;
}) {
  const profile = parseSegmentKey(segment);
  const language = profile?.language ?? "en";
  const insights = insightsFor(state, segment);
  return (
    <section data-testid="studio-column" data-segment={segment} className="panel flex min-w-0 flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {profile ? (
          <>
            <Badge tone="violet">{personaName("en", profile.persona)}</Badge>
            <Badge tone="sky">{LANGUAGE_NAMES[profile.language]}</Badge>
            {profile.club && <Badge tone="slate">fan of {state.meta?.[profile.club].short_name ?? profile.club}</Badge>}
            {profile.player && <Badge tone="gold">follows {playerName(state.meta, profile.player)}</Badge>}
          </>
        ) : (
          <Badge>{segment}</Badge>
        )}
        <span className="ms-auto text-xs tabular-nums text-slate-500">{insights.length}</span>
      </div>
      <BroadcastFrame state={state} segment={segment} now={now} held={held} testId="studio-frame" />
      {insights.length === 0 && (
        <Waiting compact title="Watching the match" hint="This segment's first insight lands with the first key moment." />
      )}
      <ol dir={isRtl(language) ? "rtl" : "ltr"} lang={language} className="flex flex-col gap-2">
        {insights.map((insight) => (
          <StudioCard key={insight.id} insight={insight} state={state} held={held.has(insight.id)} />
        ))}
      </ol>
    </section>
  );
}

function StudioCard({ insight, state, held }: { insight: Insight; state: MatchState; held: boolean }) {
  const minute = minuteOf(state, insight);
  const decide = (decision: Decision) => {
    if ((decision === "held") === held) return; // already so: nothing changes, nothing to log
    setDecision(insight.id, decision);
    recordAudit(decisionEntry(insight, decision, currentMinute(state), Date.now()));
  };
  return (
    <li
      data-testid="studio-card"
      data-held={held}
      data-fallback={insight.fallback}
      className={`animate-rise rounded-xl p-3 ring-1 transition ${held ? "bg-gold/5 opacity-60 ring-gold/30" : "bg-ink-850/80 ring-white/7"}`}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {minute && <span className="font-display font-semibold tabular-nums text-slate-400">{broadcastMinute(minute.minute, minute.phase)}</span>}
        <span className="eyebrow text-[0.62rem] text-slate-400">{kindName("en", insight.kind)}</span>
        {/* Spelled out and larger than elsewhere: the demo video zooms in on recovery and the Verifier. */}
        {insight.verified && (
          <span className="inline-flex items-center gap-1 rounded-full bg-mint/12 px-2 py-0.5 text-xs font-semibold text-mint ring-1 ring-mint/30">
            <CheckIcon width={12} height={12} /> verified
          </span>
        )}
        {insight.fallback && (
          <span
            data-testid="auto-badge"
            title="Template text: published while the agents were unavailable"
            className="inline-flex items-center rounded-full bg-gold/15 px-2 py-0.5 text-xs font-bold uppercase tracking-wide text-gold ring-1 ring-gold/40"
          >
            auto · template
          </span>
        )}
      </div>
      <div dir="auto" className="mt-1 font-display text-base font-bold leading-snug text-white">
        {insight.headline}
      </div>
      <p dir="auto" className="mt-0.5 line-clamp-3 text-xs leading-relaxed text-slate-300">
        {insight.body}
      </p>
      <div dir="ltr" className="mt-2 flex items-center gap-2">
        <div role="radiogroup" aria-label="Broadcast decision" className="flex rounded-lg bg-ink-950/70 p-0.5 text-xs ring-1 ring-white/5">
          <button
            type="button"
            role="radio"
            aria-checked={!held}
            data-testid="approve-toggle"
            onClick={() => decide("approved")}
            className={`rounded-md px-2.5 py-1 font-semibold transition ${!held ? "bg-mint text-ink-950" : "text-slate-400 hover:text-white"}`}
          >
            On air
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={held}
            data-testid="hold-toggle"
            onClick={() => decide("held")}
            className={`rounded-md px-2.5 py-1 font-semibold transition ${held ? "bg-gold text-ink-950" : "text-slate-400 hover:text-white"}`}
          >
            Hold
          </button>
        </div>
        {insight.latency_ms != null && (
          <span className="ms-auto text-xs tabular-nums text-slate-400" title="End-to-end agent latency">
            {(insight.latency_ms / 1000).toFixed(1)} s
          </span>
        )}
      </div>
      <div className="mt-2 border-t border-white/6 pt-2">
        <AgentTrace trace={insight.agent_trace} size="md" />
      </div>
    </li>
  );
}

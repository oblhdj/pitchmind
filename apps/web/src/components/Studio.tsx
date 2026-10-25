"use client";

import { setDecision, clearDecisions, useHeld } from "@/lib/approvals";
import type { Insight } from "@/lib/contracts";
import { broadcastMinute } from "@/lib/format";
import { kindName, LANGUAGE_NAMES, personaName, isRtl } from "@/lib/i18n";
import { insightsFor, knownSegments, minuteOf, playerName, scoreLine, type MatchState } from "@/lib/match";
import type { FeedParams } from "@/lib/options";
import { parseSegmentKey } from "@/lib/segments";
import { useMatch, useNow } from "@/lib/useMatch";

import { TeamCrest } from "./broadcast";
import { Brand, BroadcastFrame, ReplayControls, StatusPill } from "./controls";
import { AgentTrace } from "./fan";
import { Badge, CheckIcon } from "./ui";

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
            onClick={clearDecisions}
            className="ms-auto rounded-lg px-3 py-1.5 text-slate-300 ring-1 ring-white/10 transition hover:bg-white/5 hover:text-white"
          >
            Release all holds
          </button>
        </div>
      </header>

      <main data-testid="studio-grid" className="mx-auto grid max-w-[1800px] gap-4 px-4 py-5 md:grid-cols-2 2xl:grid-cols-4">
        {keys.length === 0 && <p className="text-sm text-slate-400">Waiting for the first insights…</p>}
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
  return (
    <li
      data-testid="studio-card"
      data-held={held}
      className={`animate-rise rounded-xl p-3 ring-1 transition ${held ? "bg-gold/5 opacity-60 ring-gold/30" : "bg-ink-850/80 ring-white/7"}`}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {minute && <span className="font-display font-semibold tabular-nums text-slate-400">{broadcastMinute(minute.minute, minute.phase)}</span>}
        <span className="eyebrow text-[0.62rem] text-slate-400">{kindName("en", insight.kind)}</span>
        {insight.verified && (
          <Badge tone="mint">
            <CheckIcon width={11} height={11} />
          </Badge>
        )}
        {insight.fallback && <Badge tone="gold">auto</Badge>}
      </div>
      <div className="mt-1 font-display text-base font-bold leading-snug text-white">{insight.headline}</div>
      <p className="mt-0.5 line-clamp-3 text-xs leading-relaxed text-slate-300">{insight.body}</p>
      <div dir="ltr" className="mt-2 flex items-center gap-2">
        <div role="radiogroup" aria-label="Broadcast decision" className="flex rounded-lg bg-ink-950/70 p-0.5 text-xs ring-1 ring-white/5">
          <button
            type="button"
            role="radio"
            aria-checked={!held}
            data-testid="approve-toggle"
            onClick={() => setDecision(insight.id, "approved")}
            className={`rounded-md px-2.5 py-1 font-semibold transition ${!held ? "bg-mint text-ink-950" : "text-slate-400 hover:text-white"}`}
          >
            On air
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={held}
            data-testid="hold-toggle"
            onClick={() => setDecision(insight.id, "held")}
            className={`rounded-md px-2.5 py-1 font-semibold transition ${held ? "bg-gold text-ink-950" : "text-slate-400 hover:text-white"}`}
          >
            Hold
          </button>
        </div>
        <span className="min-w-0 flex-1 truncate">
          <AgentTrace trace={insight.agent_trace} />
        </span>
        {insight.latency_ms != null && <span className="text-[0.65rem] tabular-nums text-slate-500">{(insight.latency_ms / 1000).toFixed(1)}s</span>}
      </div>
    </li>
  );
}

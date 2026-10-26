"use client";

import { useEffect, useState } from "react";

import { useHeld } from "@/lib/approvals";
import { t, isRtl } from "@/lib/i18n";
import { insightsFor, knownSegments } from "@/lib/match";
import type { FeedParams } from "@/lib/options";
import { closestSegment, DEMO_SEGMENTS, segmentKey, type Profile } from "@/lib/segments";
import { useMatch, useNow } from "@/lib/useMatch";

import { Brand, BroadcastFrame, ReplayControls, StatusPill } from "./controls";
import { InsightFeed, MatchHeader, PassMap, PlayerFocus, ProfilePanel, StatsPanel } from "./fan";
import { ExternalIcon } from "./ui";

/** The fan's second screen: header, broadcast preview, personalised insights, stats, player focus. */
export function SecondScreen({ feed, initialProfile }: { feed: FeedParams; initialProfile: Profile }) {
  const [profile, setProfile] = useState(initialProfile);
  const segment = segmentKey(profile);
  // Neither feed has every profile: the cloud generates the demo segments, the replay a few.
  // A fan gets the nearest one (labelled in the profile panel) rather than an empty feed.
  const liveSegment = feed.mode === "live" ? (closestSegment(segment, DEMO_SEGMENTS) ?? segment) : null;
  const { state, controls, speed } = useMatch({ mode: feed.mode, segment: liveSegment ?? segment, speed: feed.speed, from: feed.from });
  const now = useNow();
  const held = useHeld();
  const effective = liveSegment ?? closestSegment(segment, knownSegments(state)) ?? segment;
  const insights = insightsFor(state, effective).filter((i) => !held.has(i.id));
  const language = profile.language;

  // Keep the profile in the URL so a view can be shared or opened side by side.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("persona", profile.persona);
    url.searchParams.set("lang", profile.language);
    for (const [name, value] of [
      ["club", profile.club],
      ["player", profile.player],
    ] as const) {
      if (value) url.searchParams.set(name, value);
      else url.searchParams.delete(name);
    }
    window.history.replaceState(null, "", url);
  }, [profile]);

  const overlayHref = `/overlay?segment=${encodeURIComponent(effective)}${feed.mode === "live" ? "&mode=live" : ""}`;

  return (
    <div dir={isRtl(language) ? "rtl" : "ltr"} lang={language} className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-white/5 bg-ink-950/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3">
          <Brand sub={t(language, "tagline")} />
          <StatusPill mode={feed.mode} state={state} language={language} />
          <ReplayControls mode={feed.mode} state={state} speed={speed} controls={controls} />
          <nav dir="ltr" className="ms-auto flex items-center gap-2 text-sm">
            <a href={overlayHref} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-slate-300 ring-1 ring-white/10 transition hover:bg-white/5 hover:text-white">
              Overlay <ExternalIcon width={14} height={14} />
            </a>
            <a href="/studio" target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-slate-300 ring-1 ring-white/10 transition hover:bg-white/5 hover:text-white">
              Studio <ExternalIcon width={14} height={14} />
            </a>
          </nav>
        </div>
      </header>

      {state.status === "error" && (
        <div role="alert" className="mx-auto mt-4 max-w-[1500px] px-4">
          <div className="rounded-xl bg-live/10 px-4 py-3 text-sm text-live ring-1 ring-live/30">{state.detail}</div>
        </div>
      )}

      <main className="mx-auto grid max-w-[1500px] gap-4 px-4 py-5 lg:grid-cols-[300px_minmax(0,1fr)_340px]">
        <div className="order-2 space-y-4 lg:order-1">
          <ProfilePanel profile={profile} onChange={setProfile} meta={state.meta} segment={segment} effective={effective} />
          <PlayerFocus
            state={state}
            playerId={profile.player}
            insights={insights}
            language={language}
            onPick={(player) => setProfile({ ...profile, player })}
          />
        </div>
        <div className="order-1 min-w-0 space-y-4 lg:order-2">
          <MatchHeader state={state} language={language} />
          <BroadcastFrame state={state} segment={effective} now={now} held={held} liveLabel={t(language, "live")} />
          <InsightFeed state={state} insights={insights} language={language} />
        </div>
        <div className="order-3 space-y-4">
          <StatsPanel state={state} language={language} />
          {profile.persona === "analyst" && <PassMap state={state} language={language} club={profile.club} player={profile.player} />}
        </div>
      </main>
    </div>
  );
}

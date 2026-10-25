"use client";

import { useMemo } from "react";

import { useHeld } from "@/lib/approvals";
import { matchClock } from "@/lib/format";
import { onAir, scoreLine } from "@/lib/match";
import type { FeedParams } from "@/lib/options";
import { useMatch, useNow } from "@/lib/useMatch";

import { kindsOf, OverlayLayer, ScoreBug } from "./broadcast";

/** Transparent full-frame graphics for one segment, for a browser source in OBS or vMix. */
export function BroadcastOverlay({
  feed,
  segment,
  showBug,
  debug,
}: {
  feed: FeedParams;
  segment: string;
  showBug: boolean;
  debug: boolean;
}) {
  const { state } = useMatch({ mode: feed.mode, segment, speed: feed.speed, from: feed.from });
  const now = useNow(150);
  const held = useHeld();
  const overlays = onAir(state, segment, now, held);
  const kinds = useMemo(() => kindsOf(state.insights), [state.insights]);
  const score = scoreLine(state);
  return (
    <div data-testid="overlay-stage" className="@container fixed inset-0">
      {showBug && <ScoreBug meta={state.meta} score={score} />}
      <OverlayLayer overlays={overlays} meta={state.meta} kinds={kinds} score={score} />
      {debug && (
        <div className="absolute bottom-2 end-2 rounded-md bg-black/70 px-2 py-1 font-mono text-xs text-white">
          {feed.mode} · {state.status} · {matchClock(state.clock)} · {segment}
        </div>
      )}
    </div>
  );
}

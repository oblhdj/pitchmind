"use client";

import { useEffect, useMemo, useReducer, useRef, useState } from "react";

import { createFeed, type Feed, type FeedMode } from "./feed";
import { initialState, reduce } from "./match";

export interface MatchOptions {
  mode: FeedMode;
  segment: string | null;
  /** Live studio: one connection per segment key. */
  liveSegments?: readonly string[];
  speed: number;
  from: number;
}

export interface ReplayControls {
  pause(): void;
  resume(): void;
  setSpeed(speed: number): void;
  seek(t: number): void;
}

/** Runs a feed for the lifetime of the component and folds its events into match state. */
export function useMatch(options: MatchOptions) {
  const [state, dispatch] = useReducer(reduce, initialState);
  const feedRef = useRef<Feed | null>(null);
  const segmentRef = useRef(options.segment);
  const [speed, setSpeedState] = useState(options.speed);
  const liveKey = options.liveSegments?.join(";") ?? "";

  useEffect(() => {
    const feed = createFeed({
      mode: options.mode,
      segment: segmentRef.current,
      segments: liveKey ? liveKey.split(";") : undefined,
      speed: options.speed,
      from: options.from,
    });
    feedRef.current = feed;
    const off = feed.subscribe((event) => dispatch({ event, now: performance.now() }));
    feed.start();
    return () => {
      off();
      feed.stop();
      feedRef.current = null;
    };
    // The feed is rebuilt only when its source changes; speed and position move through the controls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.mode, liveKey]);

  useEffect(() => {
    segmentRef.current = options.segment;
    feedRef.current?.setSegment(options.segment);
  }, [options.segment]);

  const controls = useMemo<ReplayControls>(
    () => ({
      pause: () => feedRef.current?.pause(),
      resume: () => feedRef.current?.resume(),
      setSpeed: (value: number) => {
        feedRef.current?.setSpeed(value);
        setSpeedState(value);
      },
      seek: (t: number) => feedRef.current?.seek(t),
    }),
    [],
  );

  return { state, controls, speed };
}

/** Wall-clock milliseconds (performance.now), refreshed on an interval, for overlay timing. */
export function useNow(intervalMs = 200): number {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const update = () => setNow(performance.now());
    update();
    const id = setInterval(update, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

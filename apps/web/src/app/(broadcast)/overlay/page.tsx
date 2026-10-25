import { BroadcastOverlay } from "@/components/BroadcastOverlay";
import { feedParams, stringParam, type SearchParams } from "@/lib/options";
import { DEFAULT_PROFILE, segmentKey } from "@/lib/segments";

/**
 * ``/overlay?segment=<key>`` for a browser source. Also ``mode``, ``speed``, ``from``,
 * ``bug=0`` (hide the score bug) and ``debug=1`` (show the clock).
 */
export default async function OverlayPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  return (
    <BroadcastOverlay
      feed={feedParams(params)}
      segment={stringParam(params, "segment") ?? segmentKey(DEFAULT_PROFILE)}
      showBug={stringParam(params, "bug") !== "0"}
      debug={stringParam(params, "debug") === "1"}
    />
  );
}

import type { Metadata } from "next";

import { Studio } from "@/components/Studio";
import { feedParams, stringParam, type SearchParams } from "@/lib/options";

export const metadata: Metadata = { title: "Studio" };

/** The four segments of the demo match; ``?segments=key;key`` overrides them in live mode. */
const DEMO_SEGMENTS = [
  "analyst|en|club:*|player:*|metric:*",
  "casual|ar|club:home|player:*|metric:*",
  "beginner|fr|club:*|player:*|metric:*",
  "casual|en|club:*|player:H10|metric:*",
];

export default async function StudioPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const custom = stringParam(params, "segments")?.split(";").filter(Boolean);
  return <Studio feed={feedParams(params)} segments={custom?.length ? custom : DEMO_SEGMENTS} />;
}

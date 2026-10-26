import type { Metadata } from "next";

import { Studio } from "@/components/Studio";
import { feedParams, stringParam, type SearchParams } from "@/lib/options";
import { DEMO_SEGMENTS } from "@/lib/segments";

export const metadata: Metadata = { title: "Studio" };

/** The four segments of the demo match; ``?segments=key;key`` overrides them in live mode. */
export default async function StudioPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const custom = stringParam(params, "segments")?.split(";").filter(Boolean);
  return <Studio feed={feedParams(params)} segments={custom?.length ? custom : DEMO_SEGMENTS} />;
}

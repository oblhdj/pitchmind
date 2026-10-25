import { SecondScreen } from "@/components/SecondScreen";
import { feedParams, profileParams, type SearchParams } from "@/lib/options";

export default async function SecondScreenPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  return <SecondScreen feed={feedParams(params)} initialProfile={profileParams(params)} />;
}

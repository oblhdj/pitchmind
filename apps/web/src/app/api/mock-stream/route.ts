/**
 * The scripted demo match (`data/mock/stream.jsonl`), served as JSON lines for the mock feed.
 * Read at build time, so a deployed app does not need the data folder.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-static";

export async function GET(): Promise<Response> {
  const file = process.env.MOCK_STREAM_PATH ?? path.join(process.cwd(), "..", "..", "data", "mock", "stream.jsonl");
  // Read once at build time (force-static), so the file need not be traced into the server bundle.
  const body = await readFile(/* turbopackIgnore: true */ file, "utf-8");
  return new Response(body, {
    headers: { "content-type": "application/x-ndjson; charset=utf-8", "cache-control": "public, max-age=300" },
  });
}

/** Smoke tests on the mock replay: the three routes render and react as the demo needs. */
import { expect, test } from "@playwright/test";

const ARABIC = "casual|ar|club:home|player:*|metric:*";

test("second screen: an overlay goes on air in mock mode", async ({ page }) => {
  await page.goto("/?from=550"); // the first goal's graphics air at 557 s of match time
  await expect(page.getByTestId("match-header")).toContainText("North City FC");
  const frame = page.getByTestId("broadcast-frame");
  await expect(frame.getByTestId("overlay-lower_third")).toBeVisible();
  await expect(frame.getByTestId("overlay-lower_third")).toContainText("Halvorsen");
});

test("second screen: Why? shows the claims, cited event ids and the events", async ({ page }) => {
  await page.goto("/?from=600");
  const card = page.getByTestId("insight-card").first();
  await expect(card).toContainText("Harbour strike first");
  await card.getByTestId("why-button").click();
  const why = card.getByTestId("why-panel");
  await expect(why).toBeVisible();
  await expect(why.getByTestId("evidence-id").first()).toHaveText("#130");
  await expect(why.getByTestId("cited-events")).toContainText("Goal");
});

test("second screen: an Arabic profile renders right to left", async ({ page }) => {
  await page.goto("/?persona=casual&lang=ar&club=home&from=600");
  const root = page.locator("body > div[dir]").first();
  await expect(root).toHaveAttribute("dir", "rtl");
  await expect(root).toHaveAttribute("lang", "ar");
  await expect(page.getByTestId("segment-key")).toHaveText(ARABIC);
  const card = page.getByTestId("insight-card").first();
  await expect(card).toContainText("هاربور");
  // Each text takes its own direction (an English template body would stay left to right), the latency too.
  await expect(card.locator("h3")).toHaveAttribute("dir", "auto");
  await expect(card.locator("p").first()).toHaveAttribute("dir", "auto");
  expect(await card.locator("p").first().evaluate((el) => getComputedStyle(el).direction)).toBe("rtl");
  expect(await card.getByTestId("latency").evaluate((el) => getComputedStyle(el).direction)).toBe("ltr");
});

test("second screen on a phone: the match header shows each team's short name in full", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?from=600");
  const names = page.getByTestId("match-header").getByTestId("team-name");
  await expect(names).toHaveText(["NCF", "HBU"], { useInnerText: true });
  expect(await names.evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth).length)).toBe(0);
});

test("second screen: a template fallback carries the auto badge", async ({ page }) => {
  await page.goto("/?from=5000"); // the analyst insight at 80' is a template
  const fallback = page.locator('[data-testid="insight-card"][data-fallback="true"]').first();
  await expect(fallback.getByTestId("auto-badge")).toBeVisible();
});

test("second screen: the analyst view has a pass map, filtered to the chosen club", async ({ page }) => {
  await page.goto("/?persona=analyst&club=away&from=600"); // Harbour's pass at 546 s has been played
  const passes = page.getByTestId("pass-map").getByTestId("pass");
  await expect(passes).toHaveCount(1);
  await expect(passes.first()).toHaveAttribute("data-completed", "true");
  await page.goto("/?persona=analyst&club=home&from=600");
  await expect(page.getByTestId("insight-card").first()).toContainText("Harbour"); // the history is in
  await expect(page.getByTestId("pass-map")).toBeVisible();
  await expect(page.getByTestId("pass-map").getByTestId("pass")).toHaveCount(0);
  await page.goto("/?persona=casual&from=600");
  await expect(page.getByTestId("insight-card").first()).toContainText("Harbour");
  await expect(page.getByTestId("pass-map")).toHaveCount(0);
});

test("second screen, live: a profile the cloud does not generate subscribes to the nearest one", async ({ page }) => {
  const asked: string[] = [];
  await page.routeWebSocket(/\/ws/, (ws) => {
    asked.push(new URL(ws.url()).searchParams.get("segment") ?? "");
    ws.onMessage((frame) => asked.push(String(JSON.parse(String(frame)).segment_key)));
  });
  await page.goto("/?mode=live&persona=analyst&club=away");
  await expect(page.getByTestId("profile-panel")).toContainText("analyst|en|club:*|player:*|metric:*"); // labelled
  await expect.poll(() => asked.length).toBeGreaterThan(0);
  expect(new Set(asked)).toEqual(new Set(["analyst|en|club:*|player:*|metric:*"])); // dev mode may open two sockets
  await page.getByTestId("language-picker").getByRole("radio", { name: "Français" }).click();
  await expect.poll(() => asked.at(-1)).toBe("beginner|fr|club:*|player:*|metric:*");
});

test("overlay page: transparent, segment from the URL, right to left for Arabic", async ({ page }) => {
  await page.goto(`/overlay?segment=${encodeURIComponent(ARABIC)}&from=550`);
  const lowerThird = page.getByTestId("overlay-lower_third");
  await expect(lowerThird).toBeVisible();
  await expect(lowerThird).toHaveAttribute("dir", "rtl");
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgba(0, 0, 0, 0)");
});

test("studio: every segment side by side, and a held insight leaves the air", async ({ page }) => {
  await page.goto("/studio?from=600");
  await expect(page.getByTestId("studio-column")).toHaveCount(4);
  const card = page.getByTestId("studio-card").first();
  await card.getByTestId("hold-toggle").click();
  await expect(card).toHaveAttribute("data-held", "true");
  await card.getByTestId("approve-toggle").click();
  await expect(card).toHaveAttribute("data-held", "false");
  const audit = page.getByTestId("audit-trail").getByTestId("audit-entry");
  await expect(audit).toHaveCount(2);
  await expect(audit.first()).toHaveAttribute("data-action", "approved"); // newest first
  await expect(audit.last()).toHaveAttribute("data-action", "held");
});

test("before the first insight, the feeds say the agents are watching", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("insight-feed").getByTestId("feed-waiting")).toContainText("The agents are watching the match.");
  await page.goto("/studio");
  await expect(page.getByTestId("studio-column").first().getByTestId("feed-waiting")).toBeVisible();
});

test("studio: a template fallback shows its badge and the agents that tried, large enough to read", async ({ page }) => {
  await page.goto("/studio?from=5000"); // the analyst insight at 4999 s is a template
  const card = page.locator('[data-testid="studio-card"][data-fallback="true"]').first();
  await expect(card.getByTestId("auto-badge")).toHaveText("auto · template");
  const trace = card.getByTestId("agent-trace");
  await expect(trace).toHaveText(/orchestrator\s*›\s*explain\s*›\s*template/);
  expect(await trace.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
});

test("studio on a phone: each audit entry keeps its headline readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/studio?from=600");
  await expect(page.getByTestId("studio-card")).toHaveCount(3); // the insights up to 10'
  for (const card of await page.getByTestId("studio-card").all()) await card.getByTestId("hold-toggle").click();
  const headlines = page.getByTestId("audit-entry").getByTestId("audit-headline");
  await expect(headlines).not.toHaveCount(0);
  for (const headline of await headlines.all()) {
    expect((await headline.boundingBox())?.width ?? 0).toBeGreaterThan(150); // not squeezed to an ellipsis
  }
});

test("studio: a decision in one studio tab shows in the other's audit trail", async ({ page, context }) => {
  await page.goto("/studio?from=600");
  await expect(page.getByTestId("studio-card").first()).toBeVisible(); // compiled before the second tab asks
  const other = await context.newPage();
  await other.goto("/studio?from=600");
  await expect(other.getByTestId("studio-card").first()).toBeVisible();
  await page.getByTestId("studio-card").first().getByTestId("hold-toggle").click();
  const audit = other.getByTestId("audit-trail").getByTestId("audit-entry");
  await expect(audit).toHaveCount(1);
  await expect(audit.first()).toHaveAttribute("data-action", "held");
});

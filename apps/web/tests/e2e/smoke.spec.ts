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
  await expect(page.getByTestId("insight-card").first()).toContainText("هاربور");
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

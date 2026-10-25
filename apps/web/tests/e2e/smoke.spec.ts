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
});

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PORT ?? 3100);
// Locally on Windows use the installed Edge (no browser download); CI uses Playwright's Chromium.
const channel = process.env.PW_CHANNEL ?? (process.platform === "win32" && !process.env.CI ? "msedge" : undefined);

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "unit", testMatch: /unit[\\/].*\.spec\.ts$/ },
    {
      name: "e2e",
      testMatch: /e2e[\\/].*\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"], channel, viewport: { width: 1440, height: 1000 } },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${PORT}`,
    url: `http://localhost:${PORT}/api/mock-stream`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});

import { defineConfig, devices } from "@playwright/test";

// Runs against the built Compose stack, never the Vite dev server: scripts/e2e.sh starts it.
export default defineConfig({
  testDir: "e2e",
  // A flaky journey must fail, not pass on a second try (AC-24).
  retries: 0,
  workers: 1,
  forbidOnly: true,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8180",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

import { defineConfig } from "@playwright/test";

// E2E runs against the dev stack (backend :8000 + Vite :5173), reusing servers
// that are already up. The spec creates uniquely-named records and cleans up
// after itself via the API, so the dev database is left as it was found.
const CI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  // One worker on CI. `fullyParallel: false` only serialises *within* a file, so
  // the two spec files otherwise run at once against a single database and a
  // single API process — which is the likeliest source of the contention that
  // made a save miss its 5s expectation once (#17).
  workers: CI ? 1 : undefined,
  // A retry on CI so a slow save reports as flaky rather than red, and the record
  // of which tests are actually unstable accumulates somewhere. Locally a failure
  // should stay a failure — retrying in front of the person who caused it just
  // hides what they did.
  retries: CI ? 1 : 0,
  // Default reporters print to the console and leave nothing behind. The HTML
  // report is what makes an upload worth doing: it embeds the trace below.
  reporter: CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:5173",
    // Only on the retry, so the ordinary green run pays nothing. A trace carries
    // the DOM, the network and a screenshot at every step, which is the
    // difference between reading that a button stayed visible and seeing why.
    trace: "on-first-retry",
  },
  // settings.spec.ts flips the instance-settings singleton (the reference
  // currency) — the one piece of state every spec shares. order-snapshot and
  // order-lossless read that value in a beforeAll and assert stamps against
  // it, so the flip must never overlap them; a project dependency is the only
  // cross-file ordering Playwright offers. The trade: a failure in `app`
  // skips `settings` for that run.
  projects: [
    { name: "app", testIgnore: /settings\.spec\.ts/ },
    { name: "settings", testMatch: /settings\.spec\.ts/, dependencies: ["app"] },
  ],
  webServer: [
    {
      command: "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/healthz",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});

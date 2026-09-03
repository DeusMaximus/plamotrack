/**
 * The owner credential the e2e suite runs under (M6-3, #188).
 *
 * Since the default-deny flip every collection route wants a signed-in owner,
 * so the suite signs in once — `auth.setup.ts`, the `setup` project every other
 * project depends on — and reuses that session two ways:
 *
 * - **browser contexts** load `STORAGE_STATE` (the session cookie on the SPA's
 *   own host); the SPA then fetches its own CSRF token from `GET /auth/session`
 *   exactly as it does for a real owner;
 * - **the specs' own API calls** go through `apiContext()`, which attaches the
 *   same cookie plus the two things a cookie-borne write owes the dependency:
 *   an `Origin` and the session-bound `X-CSRF-Token` (§5.6).
 *
 * Both files live under `e2e/.auth/` (gitignored) and are rewritten by every run.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { request, type APIRequestContext } from "@playwright/test";

/** The API, spoken to directly (the dev server proxies `/api/*` here). */
export const API = "http://127.0.0.1:8000";
/** The SPA — the origin whose cookie jar the browser contexts reuse. */
export const APP = "http://localhost:5173";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const AUTH_DIR = path.join(HERE, ".auth");
export const STORAGE_STATE = path.join(AUTH_DIR, "owner.json");
export const API_CREDENTIALS = path.join(AUTH_DIR, "api.json");

/** The owner password the suite signs in with. A fresh (unclaimed) instance is
 *  claimed with it by `auth.setup.ts`; an instance somebody already claimed —
 *  a developer's own dev database — must be told its password here, because
 *  the suite will not overwrite a credential it did not create. */
export const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "e2e-owner-password";

export type ApiCredentials = {
  /** `name=value` of the session cookie, whichever name the scheme selected. */
  cookie: string;
  /** From `GET /auth/session` (or the login response) for that session. */
  csrfToken: string;
};

export function readApiCredentials(): ApiCredentials {
  try {
    return JSON.parse(fs.readFileSync(API_CREDENTIALS, "utf8")) as ApiCredentials;
  } catch (err) {
    throw new Error(
      `No e2e owner session at ${API_CREDENTIALS} — the "setup" project (auth.setup.ts) ` +
        `writes it and every other project depends on it. Run the full suite, or ` +
        `\`npx playwright test --project=setup\` first. (${String(err)})`,
    );
  }
}

/** An API client signed in as the owner, for a spec's own reads, seeding and
 *  cleanup. Dispose it when done, as before. */
export async function apiContext(): Promise<APIRequestContext> {
  const { cookie, csrfToken } = readApiCredentials();
  return request.newContext({
    baseURL: API,
    extraHTTPHeaders: {
      Cookie: cookie,
      // The dependency refuses a cookie-borne unsafe request that says nowhere
      // it came from; the API's own origin passes the ingress's same-origin rule.
      Origin: API,
      "X-CSRF-Token": csrfToken,
    },
  });
}

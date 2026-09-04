/**
 * The `setup` project: make sure the instance has an owner whose password the
 * suite knows, sign in as them once, and leave the session where the other
 * projects pick it up (`api.ts`).
 *
 * An **unclaimed** instance — CI's fresh database, the from-empty recipe in
 * `.agents/testing-and-review.md` — is claimed here through the host-side
 * recovery command, which is the one way in that needs no setup token from a log
 * line (`backend/app/auth/recovery.py`; it sets the credential and, on a fresh
 * instance, marks the owner claimed). A **claimed** instance is only ever signed
 * into: if `OWNER_PASSWORD` is not its password the run stops with the two ways
 * out, rather than resetting a credential the suite did not create.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test as setup } from "@playwright/test";

import { API, API_CREDENTIALS, APP, AUTH_DIR, OWNER_PASSWORD, STORAGE_STATE } from "./api";

const BACKEND = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "backend");

setup("claim the owner (if unclaimed) and sign in", async ({ request }) => {
  const state = (await (await request.get(`${API}/auth/session`)).json()) as { state: string };

  if (state.state === "unclaimed") {
    // Same config path as the API the suite runs against: the repo-root .env,
    // overridden by DATABASE_URL when the from-empty recipe sets one.
    execFileSync(
      "uv",
      ["run", "python", "-m", "app.auth.recovery", "reset-password", "--password-stdin"],
      { cwd: BACKEND, input: `${OWNER_PASSWORD}\n`, stdio: ["pipe", "inherit", "inherit"] },
    );
  }

  // Through the dev proxy, so the cookie is set for the SPA's own host and the
  // browser contexts that load STORAGE_STATE send it without any remapping.
  const login = await request.post(`${APP}/api/auth/login`, {
    data: { password: OWNER_PASSWORD },
    headers: { Origin: APP },
  });
  // Keyed on the envelope's code, not the status: a wrong password is 403
  // `auth.login_failed` since #202 round 2 (a rejected form credential), and
  // family 3 has other 403s — a hostile Origin, a CSRF failure — that deserve
  // the generic assertion below, not this diagnosis (Codex #202 round 3, f6).
  if (!login.ok()) {
    const body = (await login.json().catch(() => null)) as { code?: string } | null;
    if (body?.code === "auth.login_failed") {
      throw new Error(
        "This instance already has an owner and E2E_OWNER_PASSWORD is not their password. " +
          "Either export E2E_OWNER_PASSWORD=<the owner password>, or reset it " +
          "(cd backend && uv run python -m app.auth.recovery reset-password) — " +
          "the suite will not overwrite a credential it did not create.",
      );
    }
  }
  expect(login.status(), await login.text()).toBe(200);
  const { state: signedIn, csrf_token: csrfToken } = (await login.json()) as {
    state: string;
    csrf_token: string | null;
  };
  expect(signedIn).toBe("owner");
  expect(csrfToken).toBeTruthy();

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const storage = await request.storageState({ path: STORAGE_STATE });
  const session = storage.cookies.find((cookie) => cookie.name.endsWith("plamotrack_session"));
  expect(session, "the login response set no session cookie").toBeTruthy();
  fs.writeFileSync(
    API_CREDENTIALS,
    JSON.stringify({ cookie: `${session!.name}=${session!.value}`, csrfToken }, null, 2),
  );
});

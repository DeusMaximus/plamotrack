/**
 * The authentication boundary from the browser's side (§5.5 families 2–3; #188):
 * a browser with no session sees the sign-in screen and nothing of the
 * collection; a wrong password is refused with the API's own message; the right
 * one opens the app (the SPA fetched its CSRF token, so a cookie-borne write
 * works); signing out lands back on the sign-in screen and the session it
 * revoked no longer opens the app.
 *
 * Runs in its own signed-out browser — the storage state the other specs reuse
 * is deliberately not loaded — so the shared owner session is never signed out.
 */
import { expect, test } from "@playwright/test";

import { OWNER_PASSWORD, apiContext } from "./api";

test.use({ storageState: { cookies: [], origins: [] } });

const suffix = Date.now().toString(36);
const SHOP = `E2E Auth Shop ${suffix}`;

test("a signed-out browser must sign in, and sign out really ends the session", async ({
  page,
}) => {
  await page.goto("/");
  const signIn = page.getByRole("heading", { name: "Sign in" });
  await expect(signIn).toBeVisible();
  await expect(page.getByRole("link", { name: /orders/i })).toHaveCount(0);

  // The wrong password: refused, and still on the sign-in screen.
  await page.getByLabel("Password").fill(`${OWNER_PASSWORD}-wrong`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("That password isn't right.");
  await expect(signIn).toBeVisible();

  // The failure budget (§5.6): one failure shuts the gate for BASE_DELAY (1 s),
  // during which the right password would be 429. Wait it out rather than race it.
  await page.waitForTimeout(1_500);

  await page.getByLabel("Password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // A cookie-borne write through the SPA: the session works, CSRF token and all.
  await page.goto("/retailers");
  await page.getByRole("button", { name: "+ Add retailer" }).click();
  await page.getByLabel("Name").fill(SHOP);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(SHOP)).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(signIn).toBeVisible();

  // The revocation held: a reload does not quietly resume the old session.
  await page.reload();
  await expect(signIn).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
});

test.afterAll("clean up the retailer this run created", async () => {
  const api = await apiContext();
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((r) => r.name === SHOP);
  if (shop) await api.delete(`/retailers/${shop.id}`);
  await api.dispose();
});

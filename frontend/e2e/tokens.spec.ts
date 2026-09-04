/**
 * Personal access tokens through the real UI (M6-4, #189; §5.8 T7): mint one
 * under Settings → Access tokens, read it off the one-time card, use it as a
 * bearer against the API (a read token reads and cannot write), see it in the
 * list by prefix only, revoke it, and watch the bearer stop working.
 *
 * Leaves the revoked row behind on purpose — nothing deletes a token row, and
 * the auth tables are outside the "zero rows left" count.
 */
import { expect, request, test } from "@playwright/test";

import { API } from "./api";

test("an access token is shown once, works as a bearer, and revocation ends it", async ({
  page,
}) => {
  const name = `E2E token ${Date.now()}`;
  await page.goto("/settings/tokens");
  await expect(page.getByRole("heading", { level: 2, name: "Access tokens" })).toBeVisible();

  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Access").selectOption("read");
  await page.getByRole("button", { name: "Create token" }).click();

  const token = (await page.getByTestId("minted-token").textContent())?.trim() ?? "";
  expect(token).toMatch(/^ptk_[0-9a-f]{12}_[A-Za-z0-9_-]+$/);

  // The bearer authenticates the API on its own: no cookie, no CSRF token —
  // and a read grant cannot write.
  const bearer = await request.newContext({
    baseURL: API,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
  expect((await bearer.get("/kits")).status()).toBe(200);
  const refused = await bearer.post("/retailers", { data: { name } });
  expect(refused.status()).toBe(403);
  expect(((await refused.json()) as { code: string }).code).toBe("auth.forbidden");

  // Dismissed, the secret is gone from the page; the list shows the row by
  // its public prefix and its grant.
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("minted-token")).toHaveCount(0);
  const row = page.getByTestId("token-row").filter({ hasText: name });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Read-only");
  await expect(row).toContainText(`ptk_${token.split("_")[1]}_…`);
  await expect(page.getByText(token)).toHaveCount(0);

  // Revoke — the confirm is accepted — and the bearer is refused at once.
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Revoke" }).click();
  await expect(row).toContainText("Revoked");
  const afterwards = await bearer.get("/kits");
  expect(afterwards.status()).toBe(401);
  expect(((await afterwards.json()) as { code: string }).code).toBe("auth.bearer_invalid");
  await bearer.dispose();
});

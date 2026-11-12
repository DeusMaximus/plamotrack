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

import { API, apiContext } from "./api";

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

/**
 * The Revoke control stays inside the table box at desktop widths. The Settings
 * pane is capped (max-w-4xl less the section nav: the box is ~650 px wide from
 * 1210 px up, however wide the window), and a populated row once pushed the
 * table to 979 px inside it — the button clipped off the box's right edge,
 * reachable only by scrolling the box sideways. Drives the widest shapes a row
 * takes: a live token with every date set (an expiry, and used once so "Last
 * used" is a date, not "Never") and a revoked neighbour whose name is one
 * unbroken word; both rows at once, since column widths are the table's.
 *
 * Leaves its revoked rows behind like the test above — nothing deletes a token.
 */
test("the Revoke control stays inside the table box at desktop widths", async ({ page }) => {
  const api = await apiContext();
  const stamp = Date.now();
  const live = `E2E wide token ${stamp} for the desktop on the laptop`;
  const dead = `E2E-${stamp}-${"x".repeat(60)}`;
  const mint = async (name: string, expiresAt?: string) => {
    const resp = await api.post("/auth/tokens", {
      data: {
        name,
        scopes: ["collection:read", "collection:write"],
        ...(expiresAt ? { expires_at: expiresAt } : {}),
      },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return (await resp.json()) as { id: string; token: string };
  };
  const liveToken = await mint(live, new Date(stamp + 30 * 86_400_000).toISOString());
  const deadToken = await mint(dead);
  try {
    // One request on the live token, so its row carries a last-use date.
    const bearer = await request.newContext({
      baseURL: API,
      extraHTTPHeaders: { Authorization: `Bearer ${liveToken.token}` },
    });
    expect((await bearer.get("/kits")).status()).toBe(200);
    await bearer.dispose();
    expect((await api.delete(`/auth/tokens/${deadToken.id}`)).status()).toBe(204);

    for (const width of [1180, 1366, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/settings/tokens");
      const liveRow = page.getByTestId("token-row").filter({ hasText: live });
      const deadRow = page.getByTestId("token-row").filter({ hasText: dead });
      await expect(liveRow).toBeVisible();
      await expect(deadRow).toContainText("Revoked");
      // The populated shape, not the empty one: Last used is a date. Found by
      // its header, so a different column order is still this precondition
      // and not a failure of its own.
      const columns = await page.getByRole("columnheader").allTextContents();
      const lastUsed = liveRow.getByRole("cell").nth(columns.indexOf("Last used"));
      await expect(lastUsed).not.toHaveText("Never");

      const box = await page.getByTestId("token-table").evaluate((el) => ({
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        right: el.getBoundingClientRect().right,
      }));
      expect(box.scrollWidth, `${width}px: the table box scrolls sideways`).toBeLessThanOrEqual(
        box.clientWidth,
      );
      const revoke = liveRow.getByRole("button", { name: "Revoke" });
      await expect(revoke).toBeVisible();
      const button = (await revoke.boundingBox())!;
      expect(button.x + button.width, `${width}px: Revoke past the box`).toBeLessThanOrEqual(
        box.right + 0.5,
      );
      expect(button.x + button.width, `${width}px: Revoke past the viewport`).toBeLessThanOrEqual(
        width,
      );
      const pageOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(pageOverflow, `${width}px: horizontal page overflow`).toBe(0);
      // The exact instant is the cell's tooltip, not its text.
      await expect(lastUsed.locator("span")).toHaveAttribute("title", /\d{1,2}:\d{2}/);
    }
  } finally {
    await api.delete(`/auth/tokens/${liveToken.id}`);
    await api.dispose();
  }
});

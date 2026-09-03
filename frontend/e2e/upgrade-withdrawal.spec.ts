import { expect, test } from "@playwright/test";

/**
 * #61 — withdrawing an upgrade application from the kit editor.
 *
 * The backend suite proves the service; what only the browser can prove is the
 * shape of the *choice*: the withdrawal is offered as two equal-weight buttons
 * and no pre-selected default, because whether the part physically survived is
 * not inferable (§3.6). Both buttons are driven — restore and keep-spent — and
 * the assertion for each is the number the API stores afterwards, not what the
 * page shows.
 *
 * Applications are seeded through the API: applying via the Inventory modal is
 * its own control with its own coverage; this spec is about the withdrawal.
 */

import { apiContext } from "./api";
const suffix = Date.now().toString(36);
const UPGRADE = `E2E Metal Thrusters ${suffix}`;
const KIT = `E2E Sazabi ${suffix}`;

type Upgrade = { id: string; name: string; quantity_on_hand: number };

test.describe.configure({ mode: "serial" });

let upgradeId = "";
let kitId = "";

test.beforeAll(async () => {
  const api = await apiContext();
  const upgrade = (await (
    await api.post("/upgrades", {
      data: { name: UPGRADE, manufacturer: "E2E Works", quantity_on_hand: 5 },
    })
  ).json()) as Upgrade;
  upgradeId = upgrade.id;
  const kit = (await (
    await api.post("/kits", { data: { name: KIT, grade: "MG" } })
  ).json()) as { id: string };
  kitId = kit.id;
  await api.dispose();
});

test.afterAll(async () => {
  // Withdrawals in the tests empty the application list, so both deletes are
  // legal again — the cleanup itself exercises the released guards.
  const api = await apiContext();
  if (kitId) await api.delete(`/kits/${kitId}`);
  if (upgradeId) await api.delete(`/upgrades/${upgradeId}`);
  await api.dispose();
});

async function applyViaApi(quantity: number): Promise<void> {
  const api = await apiContext();
  const resp = await api.post(`/upgrades/${upgradeId}/apply`, {
    data: { kit_id: kitId, quantity },
  });
  expect(resp.status(), "seeding the application").toBe(201);
  await api.dispose();
}

async function stockOnHand(): Promise<number> {
  const api = await apiContext();
  const upgrades = (await (await api.get("/upgrades")).json()) as Upgrade[];
  await api.dispose();
  return upgrades.find((u) => u.name === UPGRADE)!.quantity_on_hand;
}

test("withdraw with restore returns the stock", async ({ page }) => {
  await applyViaApi(2); // 5 -> 3
  await page.goto("/kits");
  await page
    .getByRole("row", { name: new RegExp(KIT) })
    .getByRole("button", { name: "Edit" })
    .click();

  const dialog = page.getByRole("dialog", { name: `Edit ${KIT}` });
  await expect(dialog.getByText("Applied upgrades")).toBeVisible();
  await expect(dialog.getByText(`${UPGRADE} ×2`)).toBeVisible();
  await dialog.getByRole("button", { name: "Withdraw…" }).click();

  // The question, and both choices present with neither pre-selected.
  await expect(dialog.getByText("Choose whether the stock comes back")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Withdraw — stock stays spent" })).toBeVisible();
  await dialog.getByRole("button", { name: "Withdraw — return to stock" }).click();

  // The section unmounts once the last application is gone.
  await expect(dialog.getByText("Applied upgrades")).toHaveCount(0);
  expect(await stockOnHand()).toBe(5); // 3 + 2, restored
  await dialog.getByRole("button", { name: "Cancel" }).click();
});

test("withdraw without restore keeps the stock spent", async ({ page }) => {
  await applyViaApi(1); // 5 -> 4
  await page.goto("/kits");
  await page
    .getByRole("row", { name: new RegExp(KIT) })
    .getByRole("button", { name: "Edit" })
    .click();

  const dialog = page.getByRole("dialog", { name: `Edit ${KIT}` });
  await dialog.getByRole("button", { name: "Withdraw…" }).click();
  await dialog.getByRole("button", { name: "Withdraw — stock stays spent" }).click();

  await expect(dialog.getByText("Applied upgrades")).toHaveCount(0);
  expect(await stockOnHand()).toBe(4); // still spent
  await dialog.getByRole("button", { name: "Cancel" }).click();
});

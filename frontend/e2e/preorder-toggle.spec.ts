import { expect, test } from "@playwright/test";

/**
 * #120 — pre-order is one order-wide toggle, applied to every kit line.
 *
 * The per-line Ordered/Pre-ordered picker is gone; what replaced it is a submit-
 * time fan-out in the browser (the API still stores status per kit). The claim
 * worth pinning is "every line": a regression that applies the toggle to the
 * first line only is invisible with one kit, so this order carries two kit
 * lines — and the second is the one a broken loop would miss.
 */

import { apiContext } from "./api";
const suffix = Date.now().toString(36);
const SHOP = `E2E Preorder Shop ${suffix}`;
const KIT_A = `E2E Preorder Kit A ${suffix}`;
const KIT_B = `E2E Preorder Kit B ${suffix}`;

test("the pre-order toggle spawns every kit line as pre_ordered", async ({ page }) => {
  await page.goto("/orders");
  await page.getByRole("button", { name: "+ New order" }).click();

  await page.getByRole("button", { name: "+", exact: true }).click();
  await page.getByPlaceholder("New retailer name").fill(SHOP);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await page.getByLabel("Unit price").first().fill("10");
  await page.getByPlaceholder("Kit name *").first().fill(KIT_A);
  await page.getByPlaceholder("Grade *").first().fill("HG");

  await page.getByRole("button", { name: "+ Add line" }).click();
  await page.getByLabel("Unit price").nth(1).fill("20");
  await page.getByPlaceholder("Kit name *").nth(1).fill(KIT_B);
  await page.getByPlaceholder("Grade *").nth(1).fill("MG");

  await page.getByLabel(/Pre-order/).check();
  await page.getByRole("button", { name: "Record order" }).click();

  // The derived badge (#95): all kits pre_ordered = the order is the pre-order.
  const orderRow = page.getByRole("row").filter({ hasText: SHOP });
  await expect(orderRow.getByText("Pre-order")).toBeVisible();

  // Both kits, not just the first — read through the API, which is what stores.
  const api = await apiContext();
  const kits = (await (await api.get("/kits")).json()) as { name: string; status: string }[];
  expect(kits.find((kit) => kit.name === KIT_A)?.status).toBe("pre_ordered");
  expect(kits.find((kit) => kit.name === KIT_B)?.status).toBe("pre_ordered");
  await api.dispose();
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();
  const retailers = (await (await api.get("/retailers")).json()) as {
    id: string;
    name: string;
  }[];
  const shop = retailers.find((row) => row.name === SHOP);
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as {
      id: string;
      retailer_id: string;
    }[];
    for (const order of orders.filter((row) => row.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`); // undoes the spawned kits
    }
    await api.delete(`/retailers/${shop.id}`);
  }
  await api.dispose();
});

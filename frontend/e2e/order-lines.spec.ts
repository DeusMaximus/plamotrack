/** The Orders row's money and its expanded lines box (design §13.4, §6): the
 *  stored conversion sits under the order's own total whatever the header
 *  currency, an explicitly free shipping is a line, and the lines share one type
 *  column (Codex #236 P3-3, P3-4, P3-6). Two orders of this run's own, written
 *  through the API and removed after, the consumable and the retailer with them. */
import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const SHOP = `E2E Lines Shop ${suffix}`;
const FREE_POST = `LINES-A-${suffix}`; // free shipping, a JPY line converted to the header's AUD
const SHIPPED = `LINES-B-${suffix}`; // a quantity-two kit line beside a consumable line
const orders: string[] = [];
let consumableId: string | null = null;
let retailerId: string;

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeAll(async () => {
  const api = await apiContext();
  retailerId = ((await (await api.post("/retailers", { data: { name: SHOP } })).json()) as {
    id: string;
  }).id;
  let resp = await api.post("/orders", {
    data: {
      retailer_id: retailerId,
      order_date: "2026-08-01",
      order_number: FREE_POST,
      currency_code: "AUD",
      shipping_cost_minor: 0,
      delivery_service: "Free Post",
      items: [
        {
          item_type: "kit",
          quantity: 1,
          unit_price_minor: 1000,
          currency_code: "JPY",
          converted_price_minor: 1234,
          converted_currency_code: "AUD",
          kit: { name: `E2E Lines Kit A ${suffix}`, grade: "HG" },
        },
      ],
    },
  });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  orders.push(((await resp.json()) as { id: string }).id);
  resp = await api.post("/orders", {
    data: {
      retailer_id: retailerId,
      order_date: "2026-08-02",
      order_number: SHIPPED,
      currency_code: "AUD",
      shipped_at: "2026-08-03T10:00:00+00:00",
      items: [
        {
          item_type: "kit",
          quantity: 2,
          unit_price_minor: 2000,
          currency_code: "AUD",
          kit: { name: `E2E Lines Kit B ${suffix}`, grade: "HG" },
        },
        {
          item_type: "consumable",
          quantity: 1,
          unit_price_minor: 500,
          currency_code: "AUD",
          new_item: { name: `E2E Lines Cement ${suffix}`, category: "Adhesive" },
        },
      ],
    },
  });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const shipped = (await resp.json()) as {
    id: string;
    items: { item_type: string; catalog_ref_id: string | null }[];
  };
  orders.push(shipped.id);
  consumableId = shipped.items.find((item) => item.item_type === "consumable")!.catalog_ref_id;
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  for (const id of orders) await api.delete(`/orders/${id}`); // undoes the spawned kits too
  if (consumableId) await api.delete(`/consumables/${consumableId}`);
  await api.delete(`/retailers/${retailerId}`);
  await api.dispose();
});

const rowOf = (page: import("@playwright/test").Page, number: string) =>
  page.getByRole("row").filter({ hasText: number });

async function expand(page: import("@playwright/test").Page, number: string) {
  const row = rowOf(page, number);
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /line items/ }).click();
  return row.locator("xpath=following-sibling::tr[1]");
}

test("the stored conversion sits under the total whatever the header currency", async ({
  page,
}) => {
  await page.goto("/orders");
  const row = rowOf(page, FREE_POST);
  await expect(row).toBeVisible();
  // The header is AUD, the line JPY: the line's own total, then its snapshot.
  await expect(row).toContainText("JPY 1,000");
  await expect(row).toContainText("$12.34");
});

test("an explicitly free shipping is a line in the box, with its service", async ({ page }) => {
  await page.goto("/orders");
  const box = await expand(page, FREE_POST);
  await expect(box).toContainText("Shipping · Free Post");
  await expect(box).toContainText("$0.00");
  await expect(box).toContainText("1 × JPY 1,000");
});

test("the expanded lines share one type column", async ({ page }) => {
  await page.goto("/orders");
  const box = await expand(page, SHIPPED);
  const kit = box.getByText(/^kit$/i);
  const consumable = box.getByText(/^consumable$/i);
  await expect(kit).toBeVisible();
  await expect(consumable).toBeVisible();
  // The status chip on the kit line must not push the kit line's type column
  // over: both cells start where the shared track starts.
  const [a, b] = [await kit.boundingBox(), await consumable.boundingBox()];
  expect(a!.x, `kit type at ${a!.x}, consumable type at ${b!.x}`).toBeCloseTo(b!.x, 0);
  await expect(box).toContainText("stock applies on receipt");
  await expect(box).toContainText("2 × $20.00");
});

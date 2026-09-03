import { expect, test } from "@playwright/test";

/**
 * #93 — a receipt backdated through the browser survives the whole trip; since
 * #120 the ship date rides along, both set in one save of the Edit dialog (the
 * transitions dispatch ship first, then receive).
 *
 * The trap this pins is timezone folding: the picked date is sent as midnight
 * local *in the browser's own offset*, and the server judges "future" on the
 * instant's own calendar. A regression that converts to UTC first shifts the
 * asserted date for every user east of Greenwich — invisible to unit tests on
 * either side, because each half is individually consistent. So the assertion
 * reads the stored instants back through the API and puts them on the local
 * calendar the user picked from.
 */

import { apiContext } from "./api";
const suffix = Date.now().toString(36);
const SHOP = `E2E Backdate Shop ${suffix}`;
const KIT = `E2E Backdate Kit ${suffix}`;

function localDateISO(value: Date): string {
  const shifted = new Date(value);
  shifted.setMinutes(shifted.getMinutes() - shifted.getTimezoneOffset());
  return shifted.toISOString().slice(0, 10);
}

const YESTERDAY = localDateISO(new Date(Date.now() - 24 * 60 * 60 * 1000));

test("shipping and receiving with a backdate stamps the order and its kits with those dates", async ({
  page,
}) => {
  const api = await apiContext();
  const retailer = await (await api.post("/retailers", { data: { name: SHOP } })).json();
  const order = await (
    await api.post("/orders", {
      data: {
        retailer_id: retailer.id,
        order_date: YESTERDAY,
        currency_code: "AUD",
        items: [
          {
            item_type: "kit",
            quantity: 1,
            unit_price_minor: 4999,
            currency_code: "AUD",
            kit: { name: KIT, grade: "HG" },
          },
        ],
      },
    })
  ).json();

  await page.goto("/orders");
  const orderRow = page.getByRole("row").filter({ hasText: SHOP });
  await orderRow.getByRole("button", { name: "Edit" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit order" });
  await dialog.getByLabel("Shipped on").fill(YESTERDAY);
  await dialog.getByLabel("Received on").fill(YESTERDAY);
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(orderRow.getByText("Received")).toBeVisible();

  const stored = await (await api.get(`/orders/${order.id}`)).json();
  expect(localDateISO(new Date(stored.shipped_at))).toBe(YESTERDAY);
  expect(localDateISO(new Date(stored.received_at))).toBe(YESTERDAY);

  const kits: Array<{ id: string; status: string; status_updated_at: string }> = await (
    await api.get("/kits")
  ).json();
  const kit = kits.find((row) => row.id === stored.items[0].spawned_kit_ids[0]);
  expect(kit?.status).toBe("backlog");
  // The same instant as the order, not merely the same day — one value stamps both.
  expect(new Date(kit!.status_updated_at).getTime()).toBe(
    new Date(stored.received_at).getTime(),
  );
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();
  const orders: Array<{ id: string; retailer_id: string }> = await (
    await api.get("/orders")
  ).json();
  const retailers: Array<{ id: string; name: string }> = await (
    await api.get("/retailers")
  ).json();
  const mine = retailers.filter((shop) => shop.name === SHOP);
  for (const order of orders) {
    if (mine.some((shop) => shop.id === order.retailer_id)) {
      await api.delete(`/orders/${order.id}`); // undoes kits + stock
    }
  }
  for (const shop of mine) await api.delete(`/retailers/${shop.id}`);
});

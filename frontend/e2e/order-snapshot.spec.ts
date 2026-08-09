/** Issue #3: editing an order must not destroy a line's §6 conversion snapshot.
 *
 * The bug lived on both sides — the API treated an omitted field as "clear it", and
 * the form recomputed a snapshot it had no rate for. These are UI-round-trip
 * assertions, so they belong here rather than in the backend suite: each case below
 * is one the browser used to overwrite, and each is checked through the API after a
 * plain quantity edit made in the page.
 */
import type { Page } from "@playwright/test";
import { expect, request, test } from "@playwright/test";

const API = "http://127.0.0.1:8000";

const suffix = Date.now().toString(36);
const SHOP = `E2E Snapshot Shop ${suffix}`;
const TYPED_ORDER = `SNAP-A-${suffix}`; // entered through the form
const SEEDED_ORDER = `SNAP-B-${suffix}`; // written straight to the API

type Line = {
  id: string;
  quantity: number;
  converted_price_minor: number | null;
  converted_currency_code: string | null;
};

test.describe.configure({ mode: "serial" });

let reference: string; // this instance's currency — the rule must not depend on it
let foreign: string; // a purchase currency that isn't it
let otherCode: string; // a snapshot currency that is neither

test.beforeAll("read the instance currency and seed a retailer", async () => {
  const api = await request.newContext({ baseURL: API });
  reference = ((await (await api.get("/meta")).json()) as { reference_currency: string })
    .reference_currency;
  foreign = reference === "JPY" ? "EUR" : "JPY";
  otherCode = reference === "GBP" ? "SEK" : "GBP";
  await api.post("/retailers", { data: { name: SHOP } });
  await api.dispose();
});

async function findOrder(orderNumber: string): Promise<{ id: string; items: Line[] }> {
  const api = await request.newContext({ baseURL: API });
  const orders = (await (await api.get("/orders")).json()) as {
    id: string;
    order_number: string | null;
    items: Line[];
  }[];
  await api.dispose();
  return orders.find((order) => order.order_number === orderNumber)!;
}

/** Open the order in the UI, bump its first line's quantity, save. Deliberately an
 *  edit that says nothing about the snapshot — that's the whole scenario. */
async function bumpQuantityInTheBrowser(page: Page, orderNumber: string, quantity: number) {
  await page.goto("/orders");
  const row = page.getByRole("row").filter({ hasText: orderNumber });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Quantity").first().fill(String(quantity));
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();
}

test("a snapshot typed into the form survives a later quantity edit", async ({ page }) => {
  await page.goto("/orders");
  await page.getByRole("button", { name: "+ New order" }).click();
  await page.getByLabel("Retailer").selectOption({ label: SHOP });
  await page.getByLabel("Currency").fill(foreign);
  await page.getByLabel("Order number").fill(TYPED_ORDER);

  // Line 1: a foreign-currency purchase with a converted amount the user knows and
  // the browser cannot compute. Line 2: the same, minus the amount.
  await page.getByLabel("Unit price").first().fill("38");
  await page.getByLabel("Converted price").first().fill("73.50");
  await page.getByPlaceholder("Kit name *").first().fill(`E2E Snapshot Kit ${suffix}`);
  await page.getByPlaceholder("Grade *").first().fill("HG");

  await page.getByRole("button", { name: "+ Add line" }).click();
  await page.getByLabel("Unit price").nth(1).fill("12");
  await page.getByPlaceholder("Kit name *").nth(1).fill(`E2E Bare Kit ${suffix}`);
  await page.getByPlaceholder("Grade *").nth(1).fill("HG");

  await page.getByRole("button", { name: "Record order" }).click();
  await expect(page.getByRole("row").filter({ hasText: TYPED_ORDER })).toBeVisible();

  const before = await findOrder(TYPED_ORDER);
  const withSnapshot = before.items.find((line) => line.converted_price_minor !== null)!;
  const without = before.items.find((line) => line.converted_price_minor === null)!;
  expect(withSnapshot.converted_currency_code).toBe(reference);

  await bumpQuantityInTheBrowser(page, TYPED_ORDER, 3);

  const after = await findOrder(TYPED_ORDER);
  const sameLine = after.items.find((line) => line.id === withSnapshot.id)!;
  const stillBare = after.items.find((line) => line.id === without.id)!;
  // Preserved, not recomputed…
  expect(sameLine.converted_price_minor).toBe(withSnapshot.converted_price_minor);
  expect(sameLine.converted_currency_code).toBe(withSnapshot.converted_currency_code);
  // …and a line that never had one doesn't acquire one from an unrelated edit.
  expect(stillBare.converted_price_minor).toBeNull();
  expect(stillBare.converted_currency_code).toBeNull();
  expect(after.items.some((line) => line.quantity === 3)).toBe(true);
});

test("a stored snapshot survives even when the purchase is in the instance's own currency", async ({
  page,
}) => {
  // The two cases a "purchase currency === reference currency" shortcut silently
  // rewrites: a snapshot recorded in some *other* currency (an import, or an agent
  // writing before the operator moved REFERENCE_CURRENCY), and one whose amount
  // simply isn't the unit price. Both are recorded facts, neither is derivable.
  const api = await request.newContext({ baseURL: API });
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const kitLine = (name: string, converted: number, code: string) => ({
    item_type: "kit",
    quantity: 1,
    unit_price_minor: 10000,
    currency_code: reference,
    converted_price_minor: converted,
    converted_currency_code: code,
    kit: { name, grade: "RG" },
  });
  const seeded = await api.post("/orders", {
    data: {
      retailer_id: retailers.find((r) => r.name === SHOP)!.id,
      order_date: "2026-08-01",
      order_number: SEEDED_ORDER,
      currency_code: reference,
      items: [
        kitLine(`E2E Imported Kit ${suffix}`, 4200, otherCode),
        kitLine(`E2E Discounted Kit ${suffix}`, 9500, reference),
      ],
    },
  });
  expect(seeded.status()).toBe(201);
  await api.dispose();

  const before = await findOrder(SEEDED_ORDER);
  await bumpQuantityInTheBrowser(page, SEEDED_ORDER, 2);
  const after = await findOrder(SEEDED_ORDER);

  for (const line of before.items) {
    const edited = after.items.find((candidate) => candidate.id === line.id)!;
    expect(edited.converted_price_minor).toBe(line.converted_price_minor);
    expect(edited.converted_currency_code).toBe(line.converted_currency_code);
  }
  // The edit really did happen — otherwise the assertions above prove nothing.
  expect(after.items.some((line) => line.quantity === 2)).toBe(true);
});

test.afterAll("clean up everything this run created", async () => {
  const api = await request.newContext({ baseURL: API });
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((r) => r.name === SHOP);
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as {
      id: string;
      retailer_id: string;
    }[];
    for (const order of orders.filter((o) => o.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`); // undoes the spawned kits too
    }
    await api.delete(`/retailers/${shop.id}`);
  }
  await api.dispose();
});

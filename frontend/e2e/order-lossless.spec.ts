/** Issue #34: an order edit must not restate facts it never mentioned.
 *
 * The form was not a faithful projection of the stored row — it modelled one
 * currency per order, no kit scale, and no difference between "free postage" and
 * "no shipping cost recorded". Editing a tracking number therefore rewrote a
 * line's money, re-derived its kit's scale, and turned a recorded 0 into null.
 *
 * These are round-trip assertions, so they belong here rather than in the backend
 * suite: the API already stores all of this correctly, and did throughout. Each
 * case below is one the browser used to destroy on the way past.
 */
import { expect, request, test } from "@playwright/test";

const API = "http://127.0.0.1:8000";

const suffix = Date.now().toString(36);
const SHOP = `E2E Lossless Shop ${suffix}`;
const ORDER = `LOSSLESS-${suffix}`;
const KIT = `E2E Scaled Kit ${suffix}`;

type Line = {
  id: string;
  unit_price_minor: number;
  currency_code: string;
  converted_price_minor: number | null;
  converted_currency_code: string | null;
  spawned_kit_ids: string[];
};

type StoredOrder = {
  id: string;
  order_number: string | null;
  shipping_cost_minor: number | null;
  tracking_number: string | null;
  items: Line[];
};

test.describe.configure({ mode: "serial" });

let reference: string; // this instance's currency
let foreign: string; // a purchase currency with a *different* exponent

async function findOrder(): Promise<StoredOrder> {
  const api = await request.newContext({ baseURL: API });
  const orders = (await (await api.get("/orders")).json()) as StoredOrder[];
  await api.dispose();
  return orders.find((order) => order.order_number === ORDER)!;
}

async function kitScale(kitId: string): Promise<string | null> {
  const api = await request.newContext({ baseURL: API });
  const kits = (await (await api.get("/kits")).json()) as { id: string; scale: string | null }[];
  await api.dispose();
  return kits.find((kit) => kit.id === kitId)!.scale;
}

test.beforeAll("seed an order carrying everything the form used to lose", async () => {
  const api = await request.newContext({ baseURL: API });
  reference = ((await (await api.get("/meta")).json()) as { reference_currency: string })
    .reference_currency;
  // A *different exponent* is what makes a mis-scaled amount visible: 1200 whole
  // yen read as if it were dollars-and-cents comes back as 120000.
  foreign = reference === "JPY" ? "AUD" : "JPY";

  const retailer = (await (await api.post("/retailers", { data: { name: SHOP } })).json()) as {
    id: string;
  };
  const created = await api.post("/orders", {
    data: {
      retailer_id: retailer.id,
      order_date: "2026-08-01",
      order_number: ORDER,
      currency_code: reference,
      // Free postage: a recorded fact, not a missing value.
      shipping_cost_minor: 0,
      items: [
        {
          item_type: "kit",
          quantity: 1,
          // A line denominated in something other than the order header. Only
          // REST, MCP and CSV can create this shape; the browser must not break it.
          unit_price_minor: 1200,
          currency_code: foreign,
          converted_price_minor: 1850,
          converted_currency_code: reference,
          // HG derives 1/144, so 1/100 is only ever here because someone chose it.
          kit: { name: KIT, grade: "HG", scale: "1/100" },
        },
      ],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();
});

test("editing only the tracking number leaves currency, scale and free shipping alone", async ({
  page,
}) => {
  const before = await findOrder();
  const line = before.items[0];
  const kitId = line.spawned_kit_ids[0];
  // Controls: the seed really did store what the assertions below depend on.
  expect(line.currency_code).toBe(foreign);
  expect(before.shipping_cost_minor).toBe(0);
  expect(await kitScale(kitId)).toBe("1/100");

  await page.goto("/orders");
  const row = page.getByRole("row").filter({ hasText: ORDER });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  // The scale reached the form at all — without it there is nothing to send back
  // and the API re-derives 1/144 from the grade.
  await expect(page.getByLabel("Scale")).toHaveValue("1/100");

  await page.getByLabel("Tracking number").fill(`TRK-${suffix}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const after = await findOrder();
  const edited = after.items.find((candidate) => candidate.id === line.id)!;
  // The edit really happened — otherwise everything below proves nothing.
  expect(after.tracking_number).toBe(`TRK-${suffix}`);

  expect(edited.currency_code).toBe(foreign);
  expect(edited.unit_price_minor).toBe(1200);
  expect(edited.converted_price_minor).toBe(1850);
  expect(edited.converted_currency_code).toBe(reference);
  expect(after.shipping_cost_minor).toBe(0);
  expect(await kitScale(edited.spawned_kit_ids[0])).toBe("1/100");
});

test("a cold edit waits for the data it rebuilds the form from", async ({ page }) => {
  // A kit line's name, grade, scale and number live on the spawned kits, not the
  // line. Mounting the form before that query resolves captured blanks in
  // defaultValues — which react-hook-form never revisits — and wrote them back.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/kits", async (route) => {
    await held;
    await route.continue();
  });

  await page.goto("/orders");
  const row = page.getByRole("row").filter({ hasText: ORDER });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();

  // No form at all while the data is outstanding. Not rendering the fields would
  // not be enough — the hooks would already have run.
  await expect(page.getByRole("dialog")).toContainText("Loading…");
  await expect(page.getByPlaceholder("Kit name *")).toBeHidden();

  release();
  await expect(page.getByPlaceholder("Kit name *")).toHaveValue(KIT);
  await expect(page.getByLabel("Scale")).toHaveValue("1/100");
});

test.afterAll("clean up everything this run created", async () => {
  const api = await request.newContext({ baseURL: API });
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((retailer) => retailer.name === SHOP);
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as {
      id: string;
      retailer_id: string;
    }[];
    for (const order of orders.filter((candidate) => candidate.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`); // undoes the spawned kits too
    }
    await api.delete(`/retailers/${shop.id}`);
  }
  await api.dispose();
});

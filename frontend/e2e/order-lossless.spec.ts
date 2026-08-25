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
  // Mounting the form before its queries resolve captured blanks in defaultValues,
  // which react-hook-form never revisits, and wrote them back.
  //
  // This used to hold `/api/kits`, because kit details were read from that list.
  // They now arrive on the order itself (#65), so the list is no longer a
  // dependency and holding it would prove nothing. The gate that remains covers
  // catalog naming, so that is what this holds — and the kit assertions below
  // still stand, because those values must survive regardless of which query is slow.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/consumables", async (route) => {
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

/** Issue #65: the same invariant, for the kits a line spawned rather than the line.
 *
 * A line renders one set of kit fields but can own several kits, so the form shows
 * the first and every save echoed it back over all of them. Two spawned kits made
 * deliberately different were flattened by an edit that never mentioned kits.
 */
const MULTI = `MULTI-${suffix}`;

type SpawnedKit = { id: string; scale: string | null; kit_number: string | null; name: string };

/** Resolved through `/kits` rather than the order payload's nested kits, so this
 *  reads the same on either side of the fix — these tests are about what ends up
 *  stored, and the payload's shape is the backend suite's business. */
async function kitsOf(orderNumber: string): Promise<SpawnedKit[]> {
  const api = await request.newContext({ baseURL: API });
  const orders = (await (await api.get("/orders")).json()) as StoredOrder[];
  const ids = orders.find((order) => order.order_number === orderNumber)!.items[0].spawned_kit_ids;
  const all = (await (await api.get("/kits")).json()) as SpawnedKit[];
  await api.dispose();
  return ids.map((id) => all.find((kit) => kit.id === id)!);
}

async function patchKit(id: string, data: Record<string, string>): Promise<void> {
  const api = await request.newContext({ baseURL: API });
  const resp = await api.patch(`/kits/${id}`, { data });
  expect(resp.status(), await resp.text()).toBe(200);
  await api.dispose();
}

test.beforeAll("seed a two-kit line whose kits are then made different", async () => {
  const api = await request.newContext({ baseURL: API });
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const created = await api.post("/orders", {
    data: {
      retailer_id: retailers.find((r) => r.name === SHOP)!.id,
      order_date: "2026-08-01",
      order_number: MULTI,
      currency_code: reference,
      items: [
        {
          item_type: "kit",
          quantity: 2,
          unit_price_minor: 4999,
          currency_code: reference,
          kit: { name: `${KIT} pair`, grade: "HG", kit_number: "HGUC 210" },
        },
      ],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();

  // Through the supported Kits path, exactly as an owner would.
  const [, second] = await kitsOf(MULTI);
  await patchKit(second.id, { scale: "1/60", kit_number: "DIVERGENT" });
});

test("a tracking-only edit leaves two divergent kits on the same line divergent", async ({
  page,
}) => {
  const [firstBefore, secondBefore] = await kitsOf(MULTI);
  expect(secondBefore.scale).toBe("1/60"); // control: the seed diverged

  await page.goto("/orders");
  const row = page.getByRole("row").filter({ hasText: MULTI });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  // The form shows the *first* kit — it has one set of fields for two kits, which
  // is exactly why echoing them back was destructive.
  await expect(page.getByLabel("Scale")).toHaveValue(firstBefore.scale!);

  await page.getByLabel("Tracking number").fill(`TRK-MULTI-${suffix}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const [firstAfter, secondAfter] = await kitsOf(MULTI);
  expect(secondAfter.scale).toBe("1/60");
  expect(secondAfter.kit_number).toBe("DIVERGENT");
  expect(firstAfter).toEqual(firstBefore); // and the one it did show is untouched
});

test("a warm page does not revert a kit changed while it was open", async ({ page }) => {
  // The cached kit list satisfied the old hydration gate instantly, so the form
  // snapshotted values already superseded in the database and wrote them back.
  await page.goto("/orders");
  await expect(page.getByRole("row").filter({ hasText: MULTI })).toBeVisible();

  // From here the kit list is frozen at what the page already holds. Opening the
  // editor does trigger a refetch, and on localhost it usually wins the race — so
  // without this the test passes against the broken code and detects nothing.
  // Stalling it makes the stale window certain instead of likely.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/kits", async (route) => {
    await held;
    await route.continue();
  });

  const [first] = await kitsOf(MULTI);
  await patchKit(first.id, { scale: "1/48", kit_number: "CACHE-NEW" });

  // No reload: the page has been sitting there since before that change landed.
  const row = page.getByRole("row").filter({ hasText: MULTI });
  await row.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Tracking number").fill(`TRK-WARM-${suffix}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  // Released as soon as the click lands: the form's defaults were frozen at mount,
  // so the payload is already decided, and holding it any longer only blocks the
  // cache invalidation the save does on its way out.
  release();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const [firstAfter] = await kitsOf(MULTI);
  expect(firstAfter.scale).toBe("1/48");
  expect(firstAfter.kit_number).toBe("CACHE-NEW");
});

test("the editor hydrates from a fresh read, not the page's cache (#67)", async ({ page }) => {
  await page.goto("/orders");
  await expect(page.getByRole("row").filter({ hasText: MULTI })).toBeVisible();

  // Lands after the page cached its list. The pre-#67 editor hydrated from that
  // cache and would render the old number here.
  const [first] = await kitsOf(MULTI);
  await patchKit(first.id, { kit_number: "FRESH-67" });

  const row = page.getByRole("row").filter({ hasText: MULTI });
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByPlaceholder("Kit #")).toHaveValue("FRESH-67");
  await page.getByRole("button", { name: "Close" }).click();
});

test("a price edit does not revert a kit changed while the dialog was open (#67)", async ({
  page,
}) => {
  // The window the fresh read cannot close: the change lands *after* the form
  // hydrated. The form provably holds the older values — only the dirty-only
  // kit payload keeps it from echoing them. No stall needed: the ordering is
  // enforced by awaiting hydration (the field renders) before the change.
  await page.goto("/orders");
  const row = page.getByRole("row").filter({ hasText: MULTI });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByPlaceholder("Kit #")).toHaveValue("FRESH-67"); // hydrated, pre-change

  const [first] = await kitsOf(MULTI);
  await patchKit(first.id, { kit_number: "MID-EDIT-67", scale: "1/35" });

  await page.getByLabel("Unit price").fill("99");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const [firstAfter] = await kitsOf(MULTI);
  expect(firstAfter.kit_number).toBe("MID-EDIT-67"); // survived the price edit
  expect(firstAfter.scale).toBe("1/35");
  const api = await request.newContext({ baseURL: API });
  const orders = (await (await api.get("/orders")).json()) as StoredOrder[];
  await api.dispose();
  const line = orders.find((order) => order.order_number === MULTI)!.items[0];
  expect(line.unit_price_minor).not.toBe(4999); // and the edit itself landed
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

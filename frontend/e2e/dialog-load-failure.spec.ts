/** Issue #238: a dialog whose form waits on an input that failed says so.
 *
 * The order dialog mounts its form only on everything it rebuilds the stored
 * order from — the order's own fresh read, the four catalog lists (an existing
 * catalog line is named from them) and a current `/meta` (#366) — and the
 * inventory dialogs only on a current `/meta`. Mounting without one wrote blanks
 * back (#65) or recorded the old currency (#366), so the gate stays. But a list
 * that *failed* is not one still on its way: before this the dialog sat on
 * Loading… for good, with Cancel the only way out.
 *
 * So each input is failed alone, on both of TanStack's attempts, and the dialog
 * must show what could not be loaded and Retry, mount no form, and — with the
 * route answering again — Retry must ask for that input alone and mount the form
 * on the stored values. A save after it must send only what the person changed
 * (#65, #358), read off the request body.
 *
 * The order's own read failing keeps its error (`order-lossless.spec.ts`, the
 * 404) and is not repeated here. Runs in `phone` and `tablet` too, where the
 * dialog is a sheet and Retry sits in its bar.
 */
import { expect, type Page, test } from "@playwright/test";

import { apiContext } from "./api";
import { openListAt } from "./listRows";

const suffix = Date.now().toString(36);
const SHOP = `E2E Load Failure Shop ${suffix}`;
const TOOL = `E2E Load Failure Nippers ${suffix}`;
const INVENTORY_TOOL = `E2E Load Failure Sander ${suffix}`;

/** The five reads the dialogs wait on besides the order itself, as routed. */
const INPUTS = {
  meta: "/api/meta",
  tools: "/api/tools",
  consumables: "/api/consumables",
  upgrades: "/api/upgrades",
  "display-items": "/api/display-items",
} as const;
type Input = keyof typeof INPUTS;

/** What the dialog says for each, as the en-AU catalogue has it. */
const SAYS: Record<Input, RegExp> = {
  meta: /^Couldn't load the reference currency: /,
  tools: /^Couldn't load the tools: /,
  consumables: /^Couldn't load the consumables: /,
  upgrades: /^Couldn't load the upgrades: /,
  "display-items": /^Couldn't load the display items: /,
};

test.describe.configure({ mode: "serial" });

let shopId: string;
let toolId: string;
let reference: string;
let seeded = 0;

test.beforeAll(async () => {
  const api = await apiContext();
  reference = ((await (await api.get("/meta")).json()) as { reference_currency: string })
    .reference_currency;
  const shop = await api.post("/retailers", { data: { name: SHOP } });
  expect(shop.status(), await shop.text()).toBe(201);
  shopId = ((await shop.json()) as { id: string }).id;
  const tool = await api.post("/tools", { data: { name: TOOL, category: "cutting" } });
  expect(tool.status(), await tool.text()).toBe(201);
  toolId = ((await tool.json()) as { id: string }).id;
  const inventoryTool = await api.post("/tools", {
    data: { name: INVENTORY_TOOL, category: "sanding", quantity_on_hand: 4, condition_notes: "as stored" },
  });
  expect(inventoryTool.status(), await inventoryTool.text()).toBe(201);
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as { id: string; retailer_id: string }[];
  for (const order of orders.filter((candidate) => candidate.retailer_id === shopId)) {
    await api.delete(`/orders/${order.id}`); // undoes its kits and its stock
  }
  await api.delete(`/retailers/${shopId}`);
  const tools = (await (await api.get("/tools")).json()) as { id: string; name: string }[];
  for (const tool of tools.filter((row) => row.name === TOOL || row.name === INVENTORY_TOOL)) {
    await api.delete(`/tools/${tool.id}`);
  }
  await api.dispose();
});

/** Every read in `INPUTS` routed: counted, and answered 503 while it is in
 *  `failing`. Clearing `failing` is "the route answering again". */
async function watchInputs(page: Page, failing: Input[]) {
  const asked: Record<Input, number> = { meta: 0, tools: 0, consumables: 0, upgrades: 0, "display-items": 0 };
  const down = new Set<Input>(failing);
  for (const input of Object.keys(INPUTS) as Input[]) {
    await page.route(
      (url) => url.pathname === INPUTS[input],
      async (route) => {
        if (route.request().method() !== "GET") return route.continue();
        asked[input] += 1;
        if (down.has(input)) return route.fulfill({ status: 503, body: "" });
        return route.continue();
      },
    );
  }
  return { asked: () => ({ ...asked }), recover: () => down.clear(), fail: (input: Input) => down.add(input) };
}

type StoredOrder = {
  id: string;
  order_number: string | null;
  tracking_number: string | null;
  notes: string | null;
  items: {
    item_type: string;
    catalog_ref_id: string | null;
    quantity: number;
    unit_price_minor: number;
    kits: { name: string; grade: string; scale: string | null; kit_number: string | null }[];
  }[];
};

/** An order with a kit line and a line naming the file's tool. */
async function seedOrder(): Promise<{ id: string; number: string; read: () => Promise<StoredOrder> }> {
  const number = `LOADFAIL-${suffix}-${++seeded}`;
  const api = await apiContext();
  const created = await api.post("/orders", {
    data: {
      retailer_id: shopId,
      order_date: "2026-08-01",
      order_number: number,
      currency_code: reference,
      tracking_number: "STORED-TRK",
      notes: "The stored note.",
      items: [
        {
          item_type: "kit",
          quantity: 1,
          unit_price_minor: 2500,
          currency_code: reference,
          kit: { name: `E2E Load Failure Kit ${number}`, grade: "HG", scale: "1/100", kit_number: "K-238" },
        },
        {
          item_type: "tool",
          quantity: 1,
          unit_price_minor: 1500,
          currency_code: reference,
          catalog_ref_id: toolId,
        },
      ],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  await api.dispose();
  const read = async () => {
    const reader = await apiContext();
    const stored = (await (await reader.get(`/orders/${id}`)).json()) as StoredOrder;
    await reader.dispose();
    return stored;
  };
  return { id, number, read };
}

/** A stored value without the columns every write moves. */
function withoutClock(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutClock);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => key !== "updated_at")
      .map(([key, inner]) => [key, withoutClock(inner)]),
  );
}

/** Go to `path` inside the running app, as a link would: the cache survives. */
async function navigate(page: Page, path: string) {
  await page.evaluate((to) => {
    history.pushState(null, "", to);
    dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

/** The order's edit control, on whichever shape the list draws. */
function editButton(page: Page) {
  return page.getByRole("button", { name: new RegExp(`^Edit ${SHOP}`) }).filter({ visible: true }).first();
}

/** The failure state: what could not be loaded, alone, and no form beneath it. */
async function expectFailure(page: Page, input: Input) {
  const dialog = page.getByRole("dialog");
  const alerts = dialog.getByRole("alert");
  await expect(alerts.first()).toHaveText(SAYS[input], { timeout: 15_000 });
  await expect(alerts, "only the input that failed is named").toHaveCount(1);
  await expect(dialog.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  await expect(dialog.getByText("Loading…")).toHaveCount(0);
}

/** The order form is not mounted: none of its fields exist. */
async function expectNoOrderForm(page: Page) {
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Tracking number")).toHaveCount(0);
  await expect(dialog.getByPlaceholder("Kit name *")).toHaveCount(0);
}

/** Retry, and the form it mounts on the stored order. */
async function retryIntoOrderForm(page: Page, number: string) {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(dialog.getByLabel("Tracking number")).toHaveValue("STORED-TRK");
  await expect(dialog.getByLabel("Order number")).toHaveValue(number);
  await expect(dialog.getByLabel("Notes")).toHaveValue("The stored note.");
  await expect(dialog.getByPlaceholder("Kit name *")).toHaveValue(`E2E Load Failure Kit ${number}`);
  await expect(dialog.getByLabel("Scale")).toHaveValue("1/100");
  await expect(dialog.getByPlaceholder("Kit #")).toHaveValue("K-238");
  // The catalog line by its name: the list that names it has arrived.
  await expect(dialog.getByText(TOOL, { exact: true })).toBeVisible();
  await expect(dialog.getByText("(unknown item)")).toHaveCount(0);
  await expect(dialog.getByLabel("Currency").first()).toHaveValue(reference);
}

/** Change the note alone and save; the request carries the note alone, and
 *  what was stored besides it is as it was. */
async function saveNoteOnly(page: Page, order: { id: string; number: string; read: () => Promise<StoredOrder> }) {
  const before = await order.read();
  const patched = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().endsWith(`/orders/${order.id}`),
  );
  await page.getByRole("dialog").getByLabel("Notes").fill("The person's note.");
  const save = page.getByRole("button", { name: "Save changes" });
  await save.click();
  await expect(save).toBeHidden();
  expect((await patched).postDataJSON()).toEqual({ notes: "The person's note." });
  const after = await order.read();
  expect(after.notes).toBe("The person's note.");
  expect(withoutClock({ ...after, notes: before.notes })).toEqual(withoutClock(before));
}

for (const input of ["tools", "consumables", "upgrades", "display-items"] as const) {
  test(`the order dialog says the ${input} list failed, and Retry mounts the form on the stored order`, async ({
    page,
  }) => {
    const order = await seedOrder();
    const watch = await watchInputs(page, [input]);
    await page.goto(`/orders?q=${encodeURIComponent(order.number)}`);
    await editButton(page).click();

    await expectFailure(page, input);
    await expectNoOrderForm(page);

    watch.recover();
    const before = watch.asked();
    await retryIntoOrderForm(page, order.number);
    const after = watch.asked();
    // Retry asked again for the list that failed, and nothing else.
    for (const other of Object.keys(INPUTS) as Input[]) {
      if (other === input) expect(after[other], `Retry asks for ${other} again`).toBeGreaterThan(before[other]);
      else expect(after[other], `Retry leaves ${other} alone`).toBe(before[other]);
    }

    await saveNoteOnly(page, order);
  });
}

// The control on the four above: a new order names no catalog row it did not
// just pick, so it never waited on the lists and a failed one does not hold it.
test("a new order is not held by a list that failed", async ({ page }) => {
  await watchInputs(page, ["tools"]);
  await page.goto("/orders");
  await page.getByRole("button", { name: "New order" }).filter({ visible: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Currency").first()).toHaveValue(reference);
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await page.keyboard.press("Escape");
});

test("the order dialog says /meta failed on its first fetch, and Retry mounts the form", async ({ page }) => {
  const order = await seedOrder();
  const watch = await watchInputs(page, ["meta"]);
  await page.goto(`/orders?q=${encodeURIComponent(order.number)}`);
  await editButton(page).click();

  await expectFailure(page, "meta");
  await expectNoOrderForm(page);

  watch.recover();
  await retryIntoOrderForm(page, order.number);
  await saveNoteOnly(page, order);
});

test("the order dialog says the refetch of an invalidated /meta failed, and never mounts on the old copy", async ({
  page,
}) => {
  // The #366 window: a currency save invalidates /meta and its refetch fails
  // on both attempts, which leaves the overtaken copy in the cache beside the
  // error. Neither the copy nor the failure may mount the form.
  //
  // The save is answered here with the row as stored, so nothing on the
  // instance changes (settings.spec.ts owns flipping the singleton): what is
  // under test is the client's invalidation, which the answer does not decide.
  const order = await seedOrder();
  const api = await apiContext();
  const stored = await (await api.get("/settings")).json();
  await api.dispose();
  await page.route(
    (url) => url.pathname === "/api/settings",
    (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(stored) })
        : route.continue(),
  );
  const watch = await watchInputs(page, []);

  // A copy of /meta in the cache first: the page reads it.
  await page.goto(`/orders?q=${encodeURIComponent(order.number)}`);
  await expect(editButton(page)).toBeVisible();
  await expect.poll(() => watch.asked().meta).toBeGreaterThan(0);

  // Client-side from here on: a reload would empty the cache, and this would be
  // the first-fetch case again.
  await navigate(page, "/settings/general");
  const currency = page.getByLabel("Currency code");
  await expect(currency).toHaveValue(reference);
  await currency.fill(reference === "JPY" ? "AUD" : "JPY");
  watch.fail("meta");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");

  // Back to the order, the overtaken copy still in the cache.
  await navigate(page, `/orders?q=${encodeURIComponent(order.number)}`);
  await editButton(page).click();

  await expectFailure(page, "meta");
  await expectNoOrderForm(page);

  watch.recover();
  await retryIntoOrderForm(page, order.number);
  await saveNoteOnly(page, order);
});

test("a Retry that fails again says so again, and waits while it asks", async ({ page }) => {
  const order = await seedOrder();
  // Every read of the tools fails; while `gate` is set it is held first.
  let gate: Promise<void> | null = null;
  let asked = 0;
  await page.route(
    (url) => url.pathname === "/api/tools",
    async (route) => {
      asked += 1;
      if (gate) await gate;
      await route.fulfill({ status: 503, body: "" });
    },
  );
  await page.goto(`/orders?q=${encodeURIComponent(order.number)}`);
  await editButton(page).click();
  await expectFailure(page, "tools");

  let release = () => {};
  gate = new Promise<void>((resolve) => (release = resolve));
  const dialog = page.getByRole("dialog");
  const retry = dialog.getByRole("button", { name: "Retry", exact: true });
  // By the keyboard, which is what a press that waits must keep: WebKit does
  // not focus a button it is clicked on.
  const askedBefore = asked;
  await retry.focus();
  await page.keyboard.press("Enter");
  // Asking: the failure stays up, Retry waits and keeps the keyboard.
  const waiting = dialog.getByRole("button", { name: "Retrying…", exact: true });
  await expect(waiting).toHaveAttribute("aria-disabled", "true");
  await expect(waiting).toBeFocused();
  await expect(dialog.getByRole("alert")).toHaveText(SAYS.tools);
  await expectNoOrderForm(page);
  // A second press while it asks is refused: still one request in flight.
  await page.keyboard.press("Enter");
  release();
  gate = null;
  // Both attempts failed again: Retry is offered again, and still no form.
  await expect(retry).toBeVisible({ timeout: 15_000 });
  await expect(retry).not.toHaveAttribute("aria-disabled", "true");
  await expectFailure(page, "tools");
  await expectNoOrderForm(page);
  // The query's own two attempts, once: the second press asked nothing.
  expect(asked - askedBefore).toBe(2);

  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("the inventory dialog says /meta failed, and Retry mounts the form on the stored row", async ({ page }) => {
  const watch = await watchInputs(page, ["meta"]);
  await openListAt(page, "/inventory?tab=tools", INVENTORY_TOOL);
  await page.getByRole("button", { name: `Edit ${INVENTORY_TOOL}` }).filter({ visible: true }).first().click();

  await expectFailure(page, "meta");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Quantity on hand")).toHaveCount(0);

  watch.recover();
  await dialog.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(dialog.getByLabel("Name")).toHaveValue(INVENTORY_TOOL);
  await expect(dialog.getByLabel("Quantity on hand")).toHaveValue("4");
  await expect(dialog.getByLabel("Condition notes")).toHaveValue("as stored");

  const patched = page.waitForRequest((request) => request.method() === "PATCH" && /\/tools\/[^/]+$/.test(request.url()));
  await dialog.getByLabel("Condition notes").fill("the person's");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect((await patched).postDataJSON()).toEqual({ condition_notes: "the person's" });
});

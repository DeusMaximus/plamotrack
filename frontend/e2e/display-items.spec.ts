import { expect, test } from "@playwright/test";

/**
 * #126 — the display-items tab and the order line that stocks it.
 *
 * Two things the backend suite cannot see, both of them string-shaped and both of
 * them wrong in an earlier draft of this branch:
 *
 * 1. **The tab is not a plain plural.** Every other Inventory tab id doubles as the
 *    noun (`tools` → "tool"), the REST path, the query key *and* the CSV table key.
 *    `display-items` is none of those at once: the row is a "display item", the CSV
 *    is `display_items.csv`, and `tab.slice(0, -1)` would have offered "+ Add
 *    display-item". A `<h1>` renders the same either way, so only a test that reads
 *    the actual control catches it.
 *
 * 2. **Blank optional fields must reach the API as null, not "".** `scale` and
 *    `manufacturer` are the two columns no sibling table has. An empty string round-
 *    trips through the form, the payload and the table cell looking like a value the
 *    user typed, and only the API response distinguishes them — so the assertion is
 *    on what came back from the server, not on what the page shows.
 *
 * The order line is driven through the UI rather than the API because the picker's
 * new-item branch renders different fields per item_type, and display is the only
 * type that shows category *and* manufacturer *and* scale at once.
 */

import { apiContext } from "./api";
const suffix = Date.now().toString(36);
const STAND = `E2E Stand ${suffix}`;
const SCENERY = `E2E Diorama Set ${suffix}`;
const SHOP = `E2E Display Shop ${suffix}`;

type DisplayItem = {
  id: string;
  name: string;
  category: string;
  scale: string | null;
  manufacturer: string | null;
  quantity_on_hand: number;
  notes: string | null;
};

test.describe.configure({ mode: "serial" });

test("the Display tab adds an item, and blank optional fields store as null", async ({ page }) => {
  await page.goto("/inventory");
  await page.getByRole("button", { name: "Display", exact: true }).click();

  // The noun, not the tab id — "+ Add display item", never "+ Add display-item".
  const add = page.getByRole("button", { name: "+ Add display item" });
  await expect(add).toBeVisible();
  await add.click();

  await expect(page.getByRole("dialog", { name: "Add display item" })).toBeVisible();
  await page.getByLabel("Name").fill(STAND);
  await page.getByLabel("Category").fill("stand");
  // Manufacturer and Scale deliberately left blank — this is the null case.
  await page.getByLabel("Quantity on hand").fill("2");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // `exact`, because the row's stepper buttons carry the name too ("Remove one …").
  await expect(page.getByRole("cell", { name: STAND, exact: true })).toBeVisible();

  const api = await apiContext();
  const items = (await (await api.get("/display-items")).json()) as DisplayItem[];
  const stored = items.find((i) => i.name === STAND);
  expect(stored, "the item reached the API").toBeTruthy();
  expect(stored!.category).toBe("stand");
  expect(stored!.quantity_on_hand).toBe(2);
  // The point of the test: blank means "not recorded", which is null on the wire.
  expect(stored!.scale).toBeNull();
  expect(stored!.manufacturer).toBeNull();
  expect(stored!.notes).toBeNull();
  await api.dispose();
});

test("an order line creates a display item and stocks it on receive", async ({ page }) => {
  await page.goto("/orders");
  await page.getByRole("button", { name: "+ New order" }).click();

  await page.getByRole("button", { name: "+", exact: true }).click();
  await page.getByPlaceholder("New retailer name").fill(SHOP);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByPlaceholder("New retailer name")).toHaveCount(0);

  await page.locator("select").last().selectOption("display");

  // The picker's create-new branch: display is the only type showing all three.
  await page.getByPlaceholder("Search display items…").fill(SCENERY);
  await page.getByRole("button", { name: `＋ Create new display item “${SCENERY}”` }).click();
  await page.getByPlaceholder(/^Category \(required\)/).fill("scenery");
  await page.getByPlaceholder("Manufacturer", { exact: true }).fill("Tomytec");
  await page.getByPlaceholder("Scale, e.g. 1/144").fill("1/144");

  await page.getByPlaceholder("Unit price").fill("45.99");
  await page.getByRole("button", { name: "Record order" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const api = await apiContext();
  let items = (await (await api.get("/display-items")).json()) as DisplayItem[];
  let created = items.find((i) => i.name === SCENERY);
  expect(created, "the line created the catalog row").toBeTruthy();
  expect(created!.manufacturer).toBe("Tomytec");
  expect(created!.scale).toBe("1/144");
  // Pending: the row exists, the stock does not (rule 2).
  expect(created!.quantity_on_hand).toBe(0);

  const orders = (await (await api.get("/orders")).json()) as {
    id: string;
    retailer_id: string;
  }[];
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((r) => r.name === SHOP)!;
  const order = orders.find((o) => o.retailer_id === shop.id)!;
  expect((await api.post(`/orders/${order.id}/receive`)).ok()).toBe(true);

  items = (await (await api.get("/display-items")).json()) as DisplayItem[];
  created = items.find((i) => i.name === SCENERY);
  expect(created!.quantity_on_hand).toBe(1);
  await api.dispose();
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((r) => r.name === SHOP);
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as {
      id: string;
      retailer_id: string;
    }[];
    // Deleting the order undoes the stock it applied, which is what lets the
    // display item below be deleted at all — a referenced row refuses (rule 3).
    for (const order of orders.filter((o) => o.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`);
    }
  }
  const items = (await (await api.get("/display-items")).json()) as DisplayItem[];
  for (const item of items.filter((i) => i.name === STAND || i.name === SCENERY)) {
    await api.delete(`/display-items/${item.id}`);
  }
  if (shop) await api.delete(`/retailers/${shop.id}`);
  await api.dispose();
});

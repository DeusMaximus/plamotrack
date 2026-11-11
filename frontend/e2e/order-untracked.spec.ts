/** An order line the collection doesn't track (#349): entered in the order
 *  dialog by its description, counted in the order's total, shown in the lines
 *  box as what it is, and stored with no kit and no catalog item behind it.
 *  Entered beside a kit line, so "made nothing" is read against a line that
 *  did make something. This run's own retailer and order, removed after. */
import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const SHOP = `E2E Untracked Shop ${suffix}`;
const KIT = `E2E Untracked Kit ${suffix}`;
const BAG = `E2E Carry bag ${suffix}`;
const TOTE = `E2E Tote bag ${suffix}`;
let retailerId: string;

type StoredLine = {
  id: string;
  item_type: string;
  description: string | null;
  catalog_ref_id: string | null;
  quantity: number;
  unit_price_minor: number;
  kits: { name: string }[];
};

async function storedOrders(): Promise<{ id: string; items: StoredLine[] }[]> {
  const api = await apiContext();
  const all = (await (await api.get("/orders")).json()) as {
    id: string;
    retailer_id: string;
    items: StoredLine[];
  }[];
  await api.dispose();
  return all.filter((order) => order.retailer_id === retailerId);
}

test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1440, height: 900 } });

test.beforeAll(async () => {
  const api = await apiContext();
  const resp = await api.post("/retailers", { data: { name: SHOP } });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  retailerId = ((await resp.json()) as { id: string }).id;
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  for (const order of await storedOrders()) await api.delete(`/orders/${order.id}`);
  await api.delete(`/retailers/${retailerId}`);
  await api.dispose();
});

test("an other line is entered by its description and makes nothing", async ({ page }) => {
  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  await page.getByRole("button", { name: "New order" }).click();
  const dialog = page.getByRole("dialog", { name: "New order" });
  await dialog.locator('select[name="retailer_id"]').selectOption(retailerId);

  await dialog.getByLabel("Unit price").first().fill("10");
  await dialog.getByPlaceholder("Kit name *").fill(KIT);
  await dialog.getByPlaceholder("Grade *").fill("HG");

  await dialog.getByRole("button", { name: "Add line" }).click();
  await dialog.locator('select:has(option[value="other"])').nth(1).selectOption("other");
  // The type takes a description, and neither kit fields nor a catalog search.
  await expect(dialog.getByPlaceholder("Kit name *")).toHaveCount(1);
  await expect(dialog.getByPlaceholder(/^Search /)).toHaveCount(0);
  await expect(dialog.getByText("Not tracked in your collection")).toBeVisible();
  await dialog.getByLabel("Quantity").nth(1).fill("2");
  await dialog.getByLabel("Unit price").nth(1).fill("3.5");

  // Blank, it says so and nothing is sent; the control is the save after it.
  await dialog.getByRole("button", { name: "Record order" }).click();
  await expect(dialog.getByText("Say what this line was")).toBeVisible();
  expect(await storedOrders()).toEqual([]);

  await dialog.getByLabel("Description").fill(`  ${BAG} `);
  await dialog.getByRole("button", { name: "Record order" }).click();
  await expect(dialog).toBeHidden();

  // 1 × $10.00 and 2 × $3.50: the other line counts toward the total.
  const row = page.getByRole("row").filter({ hasText: SHOP });
  await expect(row).toBeVisible();
  await expect(row).toContainText("$17.00");
  await row.getByRole("button", { name: /line items/ }).click();
  const box = row.locator("xpath=following-sibling::tr[1]");
  await expect(box).toContainText(BAG);
  await expect(box).toContainText("other item");
  await expect(box).toContainText("not tracked");
  await expect(box).toContainText("2 × $3.50");

  const [order] = await storedOrders();
  const [kit, other] = order.items;
  expect(kit.kits.map((spawned) => spawned.name)).toEqual([KIT]);
  expect(other).toMatchObject({
    item_type: "other",
    description: BAG,
    catalog_ref_id: null,
    quantity: 2,
    unit_price_minor: 350,
    kits: [],
  });
  // Nothing in any catalog answers to it.
  const api = await apiContext();
  const found = (await (
    await api.get(`/catalog/search?q=${encodeURIComponent(BAG)}`)
  ).json()) as unknown[];
  await api.dispose();
  expect(found).toEqual([]);
});

test("an edit restates the description and keeps the line", async ({ page }) => {
  const [before] = await storedOrders();
  const lineId = before.items.find((item) => item.item_type === "other")!.id;

  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: SHOP });
  await row.getByRole("button", { name: "Edit" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit order" });
  await expect(dialog.getByLabel("Description")).toHaveValue(BAG);
  await dialog.getByLabel("Description").fill(TOTE);
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toBeHidden();

  const [after] = await storedOrders();
  const other = after.items.find((item) => item.item_type === "other")!;
  expect(other).toMatchObject({ id: lineId, description: TOTE, quantity: 2, kits: [] });
  // The kit line beside it was not restated into anything else.
  expect(after.items.find((item) => item.item_type === "kit")!.kits.map((k) => k.name)).toEqual([
    KIT,
  ]);
});

/** What came off an order's price (#350): a gift card entered in the order
 *  dialog under the lines, the lines left at the shop's prices, and the order
 *  saying what was paid — in the list's total and in a breakdown under its lines.
 *  The issue's own receipt: two kits at $24.75 and $26.50, a $33.88 gift card,
 *  $17.37 paid. This run's own retailer and order, removed after. */
import { expect, test, type Page } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const SHOP = `E2E Adjust Shop ${suffix}`;
const DEMI = `E2E Demi Trainer ${suffix}`;
const DILANZA = `E2E Dilanza ${suffix}`;
const CARD = `E2E gift card ${suffix}`;
const PROMO = `E2E promo ${suffix}`;
let retailerId: string;

type StoredOrder = {
  id: string;
  retailer_id: string;
  items: { unit_price_minor: number }[];
  adjustments: { id: string; label: string; amount_minor: number }[];
  totals: { currency_code: string; items_minor: number; adjustments_minor: number; paid_minor: number }[];
};

async function storedOrders(): Promise<StoredOrder[]> {
  const api = await apiContext();
  const all = (await (await api.get("/orders")).json()) as StoredOrder[];
  await api.dispose();
  return all.filter((order) => order.retailer_id === retailerId);
}

async function openEditor(page: Page) {
  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: SHOP });
  await row.getByRole("button", { name: "Edit" }).click();
  return page.getByRole("dialog", { name: "Edit order" });
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

test("a gift card is entered under the lines and the order says what was paid", async ({
  page,
}) => {
  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  await page.getByRole("button", { name: "New order" }).click();
  const dialog = page.getByRole("dialog", { name: "New order" });
  await dialog.locator('select[name="retailer_id"]').selectOption(retailerId);

  await dialog.getByLabel("Unit price").first().fill("24.75");
  await dialog.getByPlaceholder("Kit name *").first().fill(DEMI);
  await dialog.getByPlaceholder("Grade *").first().fill("HG");
  await dialog.getByRole("button", { name: "Add line" }).click();
  await dialog.getByLabel("Unit price").nth(1).fill("26.50");
  await dialog.getByPlaceholder("Kit name *").nth(1).fill(DILANZA);
  await dialog.getByPlaceholder("Grade *").nth(1).fill("HG");

  // No adjustment rows until one is asked for.
  await expect(dialog.getByLabel("What came off")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Add discount" }).click();
  await dialog.getByLabel("Amount off").fill("33.88");

  // Without a label it says so and nothing is sent; the control is the save after.
  await dialog.getByRole("button", { name: "Record order" }).click();
  await expect(dialog.getByText("Say what came off")).toBeVisible();
  expect(await storedOrders()).toEqual([]);

  await dialog.getByLabel("What came off").fill(`  ${CARD} `);
  await dialog.getByRole("button", { name: "Record order" }).click();
  await expect(dialog).toBeHidden();

  // The list's total is what was paid, not the shelf price.
  const row = page.getByRole("row").filter({ hasText: SHOP });
  await expect(row).toContainText("$17.37");
  await expect(row).not.toContainText("$51.25");
  await row.getByRole("button", { name: /line items/ }).click();
  const box = row.locator("xpath=following-sibling::tr[1]");
  // The lines at the shop's prices, then what came off, then what was paid.
  await expect(box).toContainText("1 × $24.75");
  await expect(box).toContainText("1 × $26.50");
  await expect(box).toContainText(CARD);
  await expect(box).toContainText(/[-−]\$33\.88/);
  await expect(box).toContainText(/Paid\s*\$17\.37/);

  const [order] = await storedOrders();
  expect(order.items.map((item) => item.unit_price_minor).sort()).toEqual([2475, 2650]);
  expect(order.adjustments).toMatchObject([{ label: CARD, amount_minor: 3388 }]);
  expect(order.totals).toEqual([
    {
      currency_code: "AUD",
      items_minor: 5125,
      shipping_minor: 0,
      adjustments_minor: 3388,
      paid_minor: 1737,
    },
  ]);
});

test("an edit that leaves the adjustments alone does not restate them", async ({ page }) => {
  const [before] = await storedOrders();
  const dialog = await openEditor(page);
  await expect(dialog.getByLabel("What came off")).toHaveValue(CARD);
  await expect(dialog.getByLabel("Amount off")).toHaveValue("33.88");

  await dialog.getByLabel("Order number").fill(`ADJ-${suffix}`);
  const patch = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes(`/orders/${before.id}`),
  );
  await dialog.getByRole("button", { name: "Save changes" }).click();
  const body = (await patch).postDataJSON() as Record<string, unknown>;
  await expect(dialog).toBeHidden();
  // The control for the absence: the field this edit did change is in the body.
  expect(body.order_number).toBe(`ADJ-${suffix}`);
  expect("adjustments" in body).toBe(false);
  expect("items" in body).toBe(false);
  // Same rows, same ids: nothing was rewritten.
  expect((await storedOrders())[0].adjustments).toEqual(before.adjustments);
});

test("more than was charged is refused in the dialog, and less is saved", async ({ page }) => {
  const [before] = await storedOrders();
  const dialog = await openEditor(page);
  await dialog.getByRole("button", { name: "Add discount" }).click();
  await dialog.getByLabel("What came off").nth(1).fill(PROMO);
  // $33.88 + $17.38 is one cent more than the $51.25 the lines come to.
  await dialog.getByLabel("Amount off").nth(1).fill("17.38");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog.getByText(/come to more than this order's AUD lines and shipping/)).toBeVisible();
  await expect(dialog).toBeVisible();
  expect((await storedOrders())[0].adjustments).toEqual(before.adjustments);

  // To the cent: paid nothing, which is a total and not an absence.
  await dialog.getByLabel("Amount off").nth(1).fill("17.37");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toBeHidden();
  const row = page.getByRole("row").filter({ hasText: SHOP });
  await expect(row).toContainText("$0.00");
  const [after] = await storedOrders();
  expect(after.adjustments.map((entry) => [entry.label, entry.amount_minor])).toEqual([
    [CARD, 3388],
    [PROMO, 1737],
  ]);
  expect(after.totals[0].paid_minor).toBe(0);
});

test("removing them all brings the shelf total back and the breakdown goes", async ({ page }) => {
  const dialog = await openEditor(page);
  await dialog.getByRole("button", { name: "Remove discount" }).first().click();
  await dialog.getByRole("button", { name: "Remove discount" }).first().click();
  await expect(dialog.getByLabel("What came off")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toBeHidden();

  const row = page.getByRole("row").filter({ hasText: SHOP });
  await expect(row).toContainText("$51.25");
  await row.getByRole("button", { name: /line items/ }).click();
  const box = row.locator("xpath=following-sibling::tr[1]");
  await expect(box).toContainText("1 × $24.75");
  await expect(box).not.toContainText("Paid");
  expect((await storedOrders())[0].adjustments).toEqual([]);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the card says what came off and what was paid, and the dialog fits", async ({ page }) => {
    const api = await apiContext();
    const [order] = await storedOrders();
    const resp = await api.patch(`/orders/${order.id}`, {
      data: { adjustments: [{ label: CARD, amount_minor: 3388 }] },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    await api.dispose();

    await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
    const card = page.getByRole("listitem").filter({ hasText: SHOP });
    await expect(card).toContainText("$17.37");
    await card.getByRole("button", { name: /line items/ }).click();
    await expect(card).toContainText(CARD);
    await expect(card).toContainText(/[-−]\$33\.88/);
    await expect(card).toContainText(/Paid\s*\$17\.37/);

    await card.getByRole("button", { name: "Edit" }).click();
    const dialog = page.getByRole("dialog", { name: "Edit order" });
    // The phone's labels show, and name their fields.
    await expect(dialog.getByText("What came off", { exact: true })).toBeVisible();
    await expect(dialog.getByLabel("Amount off")).toHaveValue("33.88");
    const overflow = await dialog.evaluate((node) => {
      const scroller = node.querySelector("form")?.parentElement ?? node;
      return scroller.scrollWidth - scroller.clientWidth;
    });
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

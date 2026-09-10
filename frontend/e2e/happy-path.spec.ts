import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

// Unique names so the test never collides with (or damages) real dev data.
const suffix = Date.now().toString(36);
const SHOP = `E2E Shop ${suffix}`;
const KIT = `E2E Zaku ${suffix}`;
const MARKER = `E2E Marker ${suffix}`;

// Today on the browser's own calendar, matching what the date inputs display —
// toISOString alone is yesterday for a while every morning east of Greenwich.
const TODAY = (() => {
  const shifted = new Date();
  shifted.setMinutes(shifted.getMinutes() - shifted.getTimezoneOffset());
  return shifted.toISOString().slice(0, 10);
})();

test.describe.configure({ mode: "serial" });

// Wide enough for Home's two-up bench cards and three mail columns to sit
// side by side, as the README captures do.
test.use({ viewport: { width: 1440, height: 900 } });

test("create order → receive → kits and stock update", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());

  await page.goto("/orders");
  await page.getByRole("button", { name: "New order" }).click();

  // Retailer quick-add
  await page.getByRole("button", { name: "New retailer" }).click();
  await page.getByPlaceholder("New retailer name").fill(SHOP);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // Line 1: a kit
  await page.getByLabel("Unit price").first().fill("10");
  await page.getByPlaceholder("Kit name *").fill(KIT);
  await page.getByPlaceholder("Grade *").fill("HG");

  // Line 2: a brand-new consumable via the select-or-create typeahead
  await page.getByRole("button", { name: "Add line" }).click();
  await page.locator('select:has(option[value="consumable"])').nth(1).selectOption("consumable");
  await page.getByLabel("Quantity").nth(1).fill("3");
  await page.getByLabel("Unit price").nth(1).fill("2");
  await page.getByPlaceholder("Search consumables…").fill(MARKER);
  await page.getByRole("button", { name: /Create new consumable/ }).click();
  await page.getByPlaceholder("Category (required)").fill("paint");

  await page.getByRole("button", { name: "Record order" }).click();

  // Order recorded as pending
  const orderRow = page.getByRole("row").filter({ hasText: SHOP });
  await expect(orderRow).toBeVisible();
  await expect(orderRow.getByText("Pending")).toBeVisible();

  // Stock must NOT count while the order is pending
  await page.goto("/inventory");
  await page.getByRole("button", { name: "Consumables" }).click();
  const markerRow = page.getByRole("row").filter({ hasText: MARKER });
  await expect(markerRow).toBeVisible();
  // The count, not the cell: the "on hand" cell also holds the −/+ stepper (#55),
  // so the cell's own text is "0−+". `toHaveText` on the number is still exact,
  // which `toContainText` on the cell would not be — "10" contains "0".
  await expect(markerRow.getByTestId("stock-count")).toHaveText("0");

  // Ship, then receive — both live in the Edit dialog now (#120): filling a
  // date that isn't stored yet performs the transition on save. Today's date =
  // "it happened now" (the server stamps the moment), matching the old dialogs.
  await page.goto("/orders");
  await orderRow.getByRole("button", { name: "Edit" }).click();
  const editDialog = page.getByRole("dialog", { name: "Edit order" });
  await editDialog.getByLabel("Shipped on").fill(TODAY);
  await editDialog.getByRole("button", { name: "Save changes" }).click();
  await expect(orderRow.getByText("Shipped")).toBeVisible();
  // The Received column counts transit live while the box is on its way (#120).
  await expect(orderRow.getByText("in transit · today")).toBeVisible();

  await orderRow.getByRole("button", { name: "Edit" }).click();
  await editDialog.getByLabel("Received on").fill(TODAY);
  await editDialog.getByRole("button", { name: "Save changes" }).click();
  await expect(orderRow.getByText("Received")).toBeVisible();
  // …and switches to the delivery date with the transit time beside it.
  await expect(orderRow.getByText(/· same day/)).toBeVisible();

  // Stock applied…
  await page.goto("/inventory");
  await page.getByRole("button", { name: "Consumables" }).click();
  await expect(markerRow.getByTestId("stock-count")).toHaveText("3");

  // …and the kit advanced to Backlog (in hand, unbuilt)
  await page.goto("/kits");
  const kitRow = page.getByRole("row").filter({ hasText: KIT });
  await expect(kitRow).toBeVisible();
  await expect(kitRow.getByText("Backlog").first()).toBeVisible();
});

test("the kit's status changes from Home's edit dialog (#233 — the drag is gone)", async ({
  page,
}) => {
  // Home lists the backlog by the status clock, newest first, and the kit the
  // order just delivered is the newest — its row is on the first strip.
  await page.goto("/");
  const row = page.getByRole("region", { name: "Backlog" }).getByText(KIT, { exact: true });
  await expect(row).toBeVisible();
  await page.getByRole("button", { name: `Edit ${KIT}` }).click();
  const dialog = page.getByRole("dialog", { name: `Edit ${KIT}` });
  await dialog.getByLabel("Status").selectOption("building");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toHaveCount(0);

  // The bench shows it, with the start date the transition stamped (#94), and
  // the API agrees — the same PATCH the Kits page and an agent make.
  const bench = page.getByRole("region", { name: "On the bench" });
  await expect(bench.getByRole("heading", { level: 3, name: KIT })).toBeVisible();
  await expect(bench.getByText(/^Started /).first()).toBeVisible();
  const api = await apiContext();
  const kits = (await (await api.get("/kits")).json()) as { name: string; status: string }[];
  expect(kits.find((kit) => kit.name === KIT)?.status).toBe("building");
  await api.dispose();
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();

  const kits = (await (await api.get("/kits")).json()) as { id: string; name: string }[];
  const kit = kits.find((k) => k.name === KIT);
  // Un-progress the kit so the order's undo-delete guard allows removal.
  if (kit) await api.patch(`/kits/${kit.id}`, { data: { status: "backlog" } });

  const retailers = (await (await api.get("/retailers")).json()) as {
    id: string;
    name: string;
  }[];
  const shop = retailers.find((r) => r.name === SHOP);
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as {
      id: string;
      retailer_id: string;
    }[];
    for (const order of orders.filter((o) => o.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`); // undoes kits + stock
    }
  }

  const consumables = (await (await api.get("/consumables")).json()) as {
    id: string;
    name: string;
  }[];
  const marker = consumables.find((c) => c.name === MARKER);
  if (marker) await api.delete(`/consumables/${marker.id}`);

  if (shop) await api.delete(`/retailers/${shop.id}`);
  await api.dispose();
});

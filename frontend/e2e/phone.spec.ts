/** The happy path by thumb (#260, design §13.7) — happy-path.spec.ts is the
 *  desktop's, pinned to 1440 px and reading table rows; this is the same story
 *  through what a phone draws: sign in, record an order, receive it, move its
 *  kit to Building from Home, take one off the stock the order brought, sign
 *  out. Only the navigation a phone has is used — the tab bar, More, the cards'
 *  pencils, the sheets' action bars — and every step is checked against the
 *  API, not only the screen.
 *
 *  Its own signed-out browser and its own session, as auth.spec.ts does: the
 *  owner session the other specs share is never the one signed out. Runs in
 *  the `phone` project alone (390 × 844, a touch screen).
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { OWNER_PASSWORD, apiContext } from "./api";

test.use({ storageState: { cookies: [], origins: [] } });

const suffix = Date.now().toString(36);
const SHOP = `E2E Phone Shop ${suffix}`;
const KIT = `E2E Phone Zaku ${suffix}`;
const THINNER = `E2E Phone Thinner ${suffix}`;

// Today on the browser's own calendar, as happy-path.spec.ts says why.
const TODAY = (() => {
  const shifted = new Date();
  shifted.setMinutes(shifted.getMinutes() - shifted.getTimezoneOffset());
  return shifted.toISOString().slice(0, 10);
})();

const tabs = (page: Page): Locator => page.getByRole("navigation", { name: "Main" });
const sheet = (page: Page): Locator => page.getByRole("dialog");
const card = (page: Page, text: string): Locator =>
  page.getByRole("main").locator("li").filter({ hasText: text }).filter({ visible: true });

test("sign in, record an order, receive it, start the build, use some stock, sign out — on a phone", async ({
  page,
}) => {
  page.on("dialog", (native) => native.accept());
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // The phone's shell: a tab bar, no sidebar.
  await expect(tabs(page).getByRole("link")).toHaveText(["Home", "Kits", "Orders", "Inventory", "More"]);
  await expect(page.locator("aside")).toHaveCount(0);

  // Record an order: a kit, and three of a consumable nobody has seen before.
  await tabs(page).getByRole("link", { name: "Orders" }).click();
  await page.getByRole("button", { name: "New order" }).click();
  await sheet(page).getByRole("button", { name: "New retailer" }).click();
  await sheet(page).getByPlaceholder("New retailer name").fill(SHOP);
  await sheet(page).getByRole("button", { name: "Add", exact: true }).click();
  await sheet(page).getByLabel("Unit price").first().fill("10");
  await sheet(page).getByPlaceholder("Kit name *").fill(KIT);
  await sheet(page).getByPlaceholder("Grade *").fill("HG");
  await sheet(page).getByRole("button", { name: "Add line" }).click();
  await sheet(page).locator('select:has(option[value="consumable"])').last().selectOption("consumable");
  await sheet(page).getByLabel("Quantity").last().fill("3");
  await sheet(page).getByLabel("Unit price").last().fill("2");
  await sheet(page).getByPlaceholder(/Search consumables/).fill(THINNER);
  await sheet(page).getByRole("button", { name: /Create new consumable/ }).click();
  await sheet(page).getByPlaceholder("Category (required)").fill("thinner");
  await sheet(page).getByRole("button", { name: "Record order", exact: true }).click();
  await expect(sheet(page)).toBeHidden();

  const order = card(page, SHOP);
  await expect(order).toBeVisible();
  await expect(order.getByText("Pending")).toBeVisible();

  // Not on hand while it is on order (rule 2).
  await tabs(page).getByRole("link", { name: "Inventory" }).click();
  await page.getByRole("button", { name: "Consumables" }).click();
  const thinner = card(page, THINNER);
  await expect(thinner.getByTestId("stock-count")).toHaveText("0");

  // Receive it: the date in the order's sheet is the transition (#120).
  await tabs(page).getByRole("link", { name: "Orders" }).click();
  await order.getByRole("button", { name: /^Edit / }).click();
  await sheet(page).getByLabel("Received on").fill(TODAY);
  await sheet(page).getByRole("button", { name: "Save changes" }).click();
  await expect(sheet(page)).toBeHidden();
  await expect(order.getByText("Received").first()).toBeVisible();

  // Home: the kit is in the backlog; its pencil opens the kit's sheet, and
  // Building puts it on the bench.
  await tabs(page).getByRole("link", { name: "Home" }).click();
  await expect(page.getByRole("region", { name: "Backlog" }).getByText(KIT, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: `Edit ${KIT}` }).click();
  await sheet(page).getByLabel("Status").selectOption("building");
  await sheet(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet(page)).toBeHidden();
  await expect(page.getByRole("region", { name: "On the bench" }).getByRole("heading", { level: 3, name: KIT })).toBeVisible();

  // The stock arrived with the order; one goes into the build.
  await tabs(page).getByRole("link", { name: "Inventory" }).click();
  await page.getByRole("button", { name: "Consumables" }).click();
  await expect(thinner.getByTestId("stock-count")).toHaveText("3");
  await thinner.getByRole("button", { name: `Remove one ${THINNER}` }).click();
  await expect(thinner.getByTestId("stock-count")).toHaveText("2");

  // What the server holds, not what the screen says.
  const api = await apiContext();
  const kits = (await (await api.get(`/kits?q=${encodeURIComponent(KIT)}`)).json()) as { name: string; status: string }[];
  expect(kits.find((kit) => kit.name === KIT)?.status).toBe("building");
  const consumables = (await (await api.get("/consumables")).json()) as { name: string; quantity_on_hand: number }[];
  expect(consumables.find((item) => item.name === THINNER)?.quantity_on_hand).toBe(2);
  await api.dispose();

  // Sign out lives on More.
  await tabs(page).getByRole("link", { name: "More" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();
  const kits = (await (await api.get("/kits")).json()) as { id: string; name: string }[];
  const kit = kits.find((k) => k.name === KIT);
  // Un-progress the kit so the order's undo-delete guard allows removal.
  if (kit) await api.patch(`/kits/${kit.id}`, { data: { status: "backlog" } });
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((r) => r.name === SHOP);
  const consumables = (await (await api.get("/consumables")).json()) as { id: string; name: string; quantity_on_hand: number }[];
  const thinner = consumables.find((c) => c.name === THINNER);
  // The one that was used goes back first: deleting the order reverses the
  // three it applied, and consumed stock blocks that (rule 2's guard).
  if (thinner && thinner.quantity_on_hand < 3) {
    await api.post(`/catalog/${thinner.id}/adjust`, { data: { delta: 3 - thinner.quantity_on_hand } });
  }
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as { id: string; retailer_id: string }[];
    for (const order of orders.filter((o) => o.retailer_id === shop.id)) await api.delete(`/orders/${order.id}`);
  }
  if (thinner) await api.delete(`/consumables/${thinner.id}`);
  if (shop) await api.delete(`/retailers/${shop.id}`);
  await api.dispose();
});

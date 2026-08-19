import { expect, request, test } from "@playwright/test";

/**
 * #49 — the two browser paths that could create a duplicate.
 *
 * 1. The inline "+ retailer" control had no pending state, so a double-click posted
 *    twice. The POST is held with `page.route` so both clicks land while the first
 *    request is still in flight — on the unfixed code that is two requests, on the
 *    fixed code the second click is refused before it reaches the network. Holding
 *    the request is what makes this deterministic rather than a race the detector
 *    happens to win on localhost.
 *
 * 2. `CatalogItemPicker` searched through the app-wide 5 s `staleTime`, so an item
 *    created from one order form was invisible to the same search in the next one,
 *    and "Create new" was offered for something that now existed. `Date.now()` is
 *    pinned with `page.clock.setFixedTime` so the cached result can *never* age out
 *    within the test: on the unfixed code the stale empty result is served every
 *    time; on the fixed code the picker re-asks the server regardless.
 */

const API = "http://127.0.0.1:8000";
const suffix = Date.now().toString(36);
const SHOP = `E2E Dedup Shop ${suffix}`;
const SEARCH_SHOP = `E2E Dedup Search Shop ${suffix}`;
const MARKER = `E2E Dedup Marker ${suffix}`;

test.describe.configure({ mode: "serial" });

test("double-clicking Add on the inline retailer control creates one retailer", async ({
  page,
}) => {
  await page.goto("/orders");
  await page.getByRole("button", { name: "+ New order" }).click();
  await page.getByRole("button", { name: "+", exact: true }).click();
  await page.getByPlaceholder("New retailer name").fill(SHOP);

  // Hold every POST /retailers so the second click cannot be saved by a fast API.
  const held: Array<() => Promise<void>> = [];
  await page.route(/\/api\/retailers$/, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await new Promise<void>((release) => held.push(() => route.continue().then(release)));
  });

  await page.getByRole("button", { name: "Add", exact: true }).dblclick();

  // Give a second request every chance to arrive before we let the first through.
  await page.waitForTimeout(250);
  const requestsMade = held.length;
  for (const release of held.splice(0)) await release();
  await page.unroute(/\/api\/retailers$/);

  // The control collapses back to the select with the new shop chosen.
  await expect(page.getByPlaceholder("New retailer name")).toHaveCount(0);
  await expect(page.locator("select").first()).toHaveValue(/.+/);

  expect(requestsMade, "clicks that reached the network").toBe(1);
  const api = await request.newContext({ baseURL: API });
  const retailers = (await (await api.get("/retailers")).json()) as { name: string }[];
  expect(retailers.filter((r) => r.name === SHOP)).toHaveLength(1);
  await api.dispose();
});

test("the catalog picker offers an item created seconds ago instead of a second create", async ({
  page,
}) => {
  const api = await request.newContext({ baseURL: API });
  const shop = (await (await api.post("/retailers", { data: { name: SEARCH_SHOP } })).json()) as {
    id: string;
  };
  await api.dispose();

  // Freeze the wall clock the page sees. TanStack Query decides staleness from
  // Date.now(), so under the app-wide staleTime the cached search result below can
  // never expire during this test — the unfixed picker will always serve it.
  // Timers keep running, so the picker's 250 ms debounce still fires.
  await page.clock.setFixedTime(new Date());

  await page.goto("/orders");

  // Order A: a brand-new consumable via the typeahead — this populates the cache
  // for the search term with "no results".
  await page.getByRole("button", { name: "+ New order" }).click();
  await page.locator("select").first().selectOption({ label: SEARCH_SHOP });
  await page.locator('select:has(option[value="consumable"])').first().selectOption("consumable");
  await page.getByLabel("Unit price").first().fill("2");
  await page.getByPlaceholder("Search consumables…").fill(MARKER);
  await page.getByRole("button", { name: /Create new consumable/ }).click();
  await page.getByPlaceholder("Category (required)").fill("paint");
  await page.getByRole("button", { name: "Record order" }).click();
  await expect(page.getByRole("row").filter({ hasText: SEARCH_SHOP })).toBeVisible();

  // Order B, immediately: the same search must now show the item, not only offer
  // to create it again.
  await page.getByRole("button", { name: "+ New order" }).click();
  await page.locator('select:has(option[value="consumable"])').first().selectOption("consumable");
  await page.getByPlaceholder("Search consumables…").fill(MARKER);
  await expect(
    page.getByRole("button", { name: /on hand/ }).filter({ hasText: MARKER }),
    "the existing consumable is offered as a match",
  ).toBeVisible();

  // The results dropdown overlays the footer, so leave via the keyboard (#51).
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  void shop;
});

test.afterAll("clean up everything this run created", async () => {
  const api = await request.newContext({ baseURL: API });
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const mine = retailers.filter((r) => r.name === SHOP || r.name === SEARCH_SHOP);
  const orders = (await (await api.get("/orders")).json()) as { id: string; retailer_id: string }[];
  for (const shop of mine) {
    for (const order of orders.filter((o) => o.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`); // undoes stock + kits
    }
  }
  const consumables = (await (await api.get("/consumables")).json()) as {
    id: string;
    name: string;
  }[];
  for (const c of consumables.filter((c) => c.name === MARKER)) await api.delete(`/consumables/${c.id}`);
  for (const shop of mine) await api.delete(`/retailers/${shop.id}`);
  await api.dispose();
});

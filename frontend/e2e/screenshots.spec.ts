/**
 * README screenshot capture — NOT part of the test suite. Skipped unless
 * SCREENSHOTS=1, so `npm run test:e2e` never runs it.
 *
 * Re-shoot (from the repo root, dev `db` container up) against a throwaway
 * database so the demo data never touches real data:
 *
 *   eval "$(grep -E '^POSTGRES_(USER|PASSWORD|PORT)=' .env | sed 's/^/export /')"
 *   DSN="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:${POSTGRES_PORT:-5432}/plamotrack_demo"
 *   # create plamotrack_demo + alembic upgrade head as for the e2e from-empty
 *   # recipe in .agents/testing-and-review.md, then:
 *   ( cd frontend && DATABASE_URL="$DSN" SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts )
 *
 * Writes six 2× PNGs into docs/screenshots/, same names and logical sizes as
 * the originals. Everything seeded here is invented demo data — the README
 * says so under the retailers screenshot, so keep it that way: no real shops,
 * no real ratings. The one cross-reference the README prose makes must hold:
 * Mr. Color Thinner at 0 on hand, sitting on a *pending* Mecha Supply Co
 * order.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8000";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "..", "..", "docs", "screenshots");

const DAY = 24 * 60 * 60 * 1000;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString();
const day = (daysAgo: number) => iso(daysAgo).slice(0, 10);

test.describe.configure({ mode: "serial" });
test.skip(!process.env.SCREENSHOTS, "screenshot capture runs only with SCREENSHOTS=1");

test.use({ deviceScaleFactor: 2, viewport: { width: 1440, height: 900 } });

test("seed the demo collection and capture the README screenshots", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const post = async (route: string, json: object) => {
    const resp = await request.post(`${API}${route}`, { data: json });
    expect(resp.ok(), `${route}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const patch = async (route: string, json: object) => {
    const resp = await request.patch(`${API}${route}`, { data: json });
    expect(resp.ok(), `${route}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };

  // Refuse to seed into a database that already holds anything — this spec is
  // for the throwaway demo DB, and a stray run against dev data would pollute it.
  const existing = await (await request.get(`${API}/retailers`)).json();
  expect(existing, "screenshots seed wants an empty database").toEqual([]);

  // --- retailers (all invented; the README disclaimer depends on it) ------------
  const mecha = await post("/retailers", {
    name: "Mecha Supply Co",
    url: "https://mecha-supply.example",
    rating: 4,
    packing_quality: "good",
    shipping_speed: "fast",
    would_order_again: "yes",
    notes: "Double-boxes everything. Restocks P-Bandai fast.",
  });
  const side7 = await post("/retailers", {
    name: "Side 7 Hobby Works",
    rating: 5,
    packing_quality: "excellent",
    shipping_speed: "very_fast",
    would_order_again: "yes",
    notes: "Gold standard. Bubble wrap for days.",
  });
  const panel = await post("/retailers", {
    name: "Panel Line Imports",
    rating: 3,
    packing_quality: "average",
    shipping_speed: "slow",
    would_order_again: "maybe",
    notes: "Cheap, but three weeks in a mailer bag.",
  });
  const orbit = await post("/retailers", {
    name: "Orbit Hobby Depot",
    rating: 2,
    packing_quality: "below_average",
    shipping_speed: "very_slow",
    would_order_again: "no",
    notes: "PG box arrived crushed. Never again.",
  });

  // --- catalog ------------------------------------------------------------------
  const thinner = await post("/consumables", {
    name: "Mr. Color Thinner 400",
    category: "thinner",
    quantity_on_hand: 0,
  });
  await post("/consumables", {
    name: "Tamiya Extra Thin Cement",
    category: "cement",
    quantity_on_hand: 1,
    low_stock_threshold: 2,
  });
  const marker = await post("/consumables", {
    name: "Gundam Marker GM02",
    category: "paint",
    quantity_on_hand: 3,
    low_stock_threshold: 1,
  });
  await post("/consumables", {
    name: "Mr. Premium Top Coat (Flat)",
    category: "topcoat",
    quantity_on_hand: 2,
    low_stock_threshold: 1,
  });
  await post("/consumables", {
    name: "Tamiya Panel Line Accent (Black)",
    category: "paint",
    quantity_on_hand: 4,
  });
  await post("/tools", { name: "God Hand SPN-120", category: "cutting", quantity_on_hand: 1 });
  await post("/tools", { name: "Glass file", category: "finishing", quantity_on_hand: 2 });
  const tweezers = await post("/tools", {
    name: "Angled tweezers",
    category: "handling",
    quantity_on_hand: 1,
  });
  await post("/upgrades", {
    name: "Metal thruster set (1/144)",
    manufacturer: "Metallic Forge",
    quantity_on_hand: 2,
  });
  await post("/upgrades", {
    name: "RG waterslide decals — Nu Gundam",
    manufacturer: "D.L. Decal",
    quantity_on_hand: 1,
  });
  await post("/display-items", {
    name: "Action Base 5 (Clear)",
    category: "action base",
    scale: "1/144",
    quantity_on_hand: 3,
  });
  await post("/display-items", {
    name: "Action Base 1 (Grey)",
    category: "action base",
    scale: "1/100",
    quantity_on_hand: 2,
  });

  const kitLine = (
    name: string,
    grade: string,
    price: number,
    extra: object = {},
    quantity = 1,
  ) => ({
    item_type: "kit",
    quantity,
    unit_price_minor: price,
    currency_code: "JPY",
    kit: { name, grade, ...extra },
  });

  // --- received history: builds the backlog, the bench, and the shelf -----------
  const historic = await post("/orders", {
    retailer_id: side7.id,
    order_date: day(160),
    order_number: "S7-20260315",
    currency_code: "JPY",
    received: true,
    received_at: iso(150),
    items: [
      kitLine("MG RX-78-2 Ver. 3.0", "MG", 5500, { series: "Mobile Suit Gundam" }),
      kitLine("MG Sazabi Ver.Ka", "MG", 9200, { series: "Char's Counterattack" }),
      kitLine("HG Barbatos Lupus", "HG", 1400, { series: "Iron-Blooded Orphans" }),
    ],
  });
  const bench = await post("/orders", {
    retailer_id: mecha.id,
    order_date: day(75),
    order_number: "MS-88742",
    currency_code: "JPY",
    received: true,
    received_at: iso(60),
    items: [
      kitLine("HG Sinanju Stein (Narrative Ver.)", "HG", 2600, { series: "Gundam NT" }),
      kitLine("RG Wing Gundam Zero EW", "RG", 3300, { series: "Endless Waltz" }),
      { item_type: "tool", quantity: 1, unit_price_minor: 1200, currency_code: "JPY", catalog_ref_id: tweezers.id },
    ],
  });
  await post("/orders", {
    retailer_id: panel.id,
    order_date: day(40),
    order_number: "PLI-1207",
    currency_code: "JPY",
    received: true,
    received_at: iso(21),
    items: [
      kitLine("HG Zaku II", "HG", 1100, { series: "Mobile Suit Gundam" }, 2),
      kitLine("HG Gouf Custom", "HG", 1700, { series: "08th MS Team" }),
      kitLine("MG Freedom Gundam 2.0", "MG", 4500, { series: "Gundam SEED" }),
      kitLine("RG Nu Gundam", "RG", 4900, { series: "Char's Counterattack" }),
      { item_type: "consumable", quantity: 2, unit_price_minor: 300, currency_code: "JPY", catalog_ref_id: marker.id },
    ],
  });

  // --- in flight ----------------------------------------------------------------
  await post("/orders", {
    retailer_id: side7.id,
    order_date: day(9),
    order_number: "S7-20260812",
    currency_code: "JPY",
    shipped_at: iso(4),
    items: [
      kitLine("HG Unicorn Gundam (Perfectibility)", "HG", 2800, { series: "Gundam UC" }),
      kitLine("HG Hi-Nu Gundam", "HG", 2000, { series: "Char's Counterattack" }),
    ],
  });
  // Pending — carries the thinner the README prose points at (0 on hand until
  // this order is received).
  await post("/orders", {
    retailer_id: mecha.id,
    order_date: day(3),
    order_number: "MS-91055",
    currency_code: "JPY",
    items: [
      kitLine("HG Gundam Aerial", "HG", 1500, { series: "The Witch from Mercury" }),
      { item_type: "consumable", quantity: 1, unit_price_minor: 400, currency_code: "JPY", catalog_ref_id: thinner.id },
    ],
  });
  await post("/orders", {
    retailer_id: panel.id,
    order_date: day(12),
    order_number: "PLI-1298",
    currency_code: "JPY",
    items: [kitLine("MGSD Freedom Gundam", "MGSD", 3900, { series: "Gundam SEED", status: "pre_ordered" })],
  });
  await post("/orders", {
    retailer_id: orbit.id,
    order_date: day(30),
    order_number: "OHD-5521",
    currency_code: "JPY",
    items: [
      kitLine("PG Unleashed RX-78-2", "PG", 27500, {
        series: "Mobile Suit Gundam",
        status: "pre_ordered",
      }),
    ],
  });

  // --- move the shelf and the bench into their statuses -------------------------
  const kitId = (order: { items: { spawned_kit_ids: string[] }[] }, line: number, n = 0) =>
    order.items[line].spawned_kit_ids[n];

  await patch(`/kits/${kitId(historic, 0)}`, {
    status: "complete",
    build_started_at: iso(140),
    build_completed_at: iso(118),
    rating: 5,
    build_notes: "First MG. Panel-lined and top-coated.",
  });
  await patch(`/kits/${kitId(historic, 1)}`, {
    status: "complete",
    build_started_at: iso(110),
    build_completed_at: iso(64),
    rating: 4,
  });
  await patch(`/kits/${kitId(historic, 2)}`, {
    status: "complete",
    build_started_at: iso(58),
    build_completed_at: iso(50),
    rating: 4,
  });
  await patch(`/kits/${kitId(bench, 0)}`, { status: "building", build_started_at: iso(18) });
  await patch(`/kits/${kitId(bench, 1)}`, { status: "building", build_started_at: iso(6) });

  // --- capture ------------------------------------------------------------------
  const shot = async (
    route: string,
    file: string,
    size: { width: number; height: number },
    ready: () => Promise<void>,
    arrange?: () => Promise<void>,
  ) => {
    await page.setViewportSize(size);
    await page.goto(route);
    await ready();
    if (arrange) await arrange();
    await page.waitForTimeout(400); // let layout, fonts and counters settle
    await page.screenshot({ path: path.join(OUT, file) });
  };

  await shot("/board", "board.png", { width: 1440, height: 900 }, async () => {
    await expect(page.getByText("Build Pipeline")).toBeVisible();
    await expect(page.getByText("MG RX-78-2 Ver. 3.0")).toBeVisible();
  });

  await shot(
    "/board",
    "board-orders.png",
    { width: 1800, height: 820 },
    async () => {
      await expect(page.getByText("Build Pipeline")).toBeVisible();
    },
    async () => {
      await page.getByRole("button", { name: "Orders", exact: true }).click();
      await expect(page.getByText("Orders Pipeline")).toBeVisible();
      await expect(page.getByText("HG Unicorn Gundam (Perfectibility)")).toBeVisible();
    },
  );

  await shot(
    "/orders",
    "orders.png",
    { width: 1440, height: 820 },
    async () => {
      await expect(page.getByText("MS-91055")).toBeVisible();
    },
    async () => {
      // Expand the pending Mecha Supply Co order so its lines show.
      await page.getByRole("row").filter({ hasText: "MS-91055" }).first().click();
      await expect(page.getByText("Mr. Color Thinner 400")).toBeVisible();
    },
  );

  await shot(
    "/inventory",
    "inventory.png",
    { width: 1440, height: 620 },
    async () => {
      await expect(page.getByRole("button", { name: "Consumables" })).toBeVisible();
    },
    async () => {
      await page.getByRole("button", { name: "Consumables" }).click();
      await expect(page.getByText("Mr. Color Thinner 400")).toBeVisible();
    },
  );

  await shot("/retailers", "retailers.png", { width: 1440, height: 560 }, async () => {
    await expect(page.getByText("Mecha Supply Co")).toBeVisible();
    await expect(page.getByText("Orbit Hobby Depot")).toBeVisible();
  });

  await shot("/settings/data", "data.png", { width: 1440, height: 900 }, async () => {
    await expect(page.getByText(/export/i).first()).toBeVisible();
  });
});

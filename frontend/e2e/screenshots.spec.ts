/**
 * Screenshot capture for the README and the docs site — NOT part of the test
 * suite. Skipped unless SCREENSHOTS=1, so `npm run test:e2e` never runs it.
 *
 * Re-shoot (from the repo root, dev `db` container up) against a throwaway
 * database so the demo data never touches real data:
 *
 *   eval "$(grep -E '^POSTGRES_(USER|PASSWORD|PORT)=' .env | sed 's/^/export /')"
 *   DSN="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:${POSTGRES_PORT:-5432}/plamotrack_demo"
 *   # create plamotrack_demo + alembic upgrade head as for the e2e from-empty
 *   # recipe in .agents/testing-and-review.md, then EITHER
 *   ( cd frontend && DATABASE_URL="$DSN" SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts )
 *   # — the README's seven files into docs/screenshots/ — OR, for the docs site,
 *   ( cd frontend && DATABASE_URL="$DSN" SCREENSHOTS=1 SCREENSHOTS_OUT=../../plamotrack-docs/images/screenshots \
 *       npx playwright test e2e/screenshots.spec.ts )
 *   # — the full set there: every page and dialog, `name.png` dark and
 *   # `name-light.png` light, plus the unclaimed "Set up plamotrack" screen
 *   # that auth.setup.ts captures on its way through (screenshots.ts says
 *   # which set is which).
 *
 * The database must be fresh: the seed refuses a populated one, and the setup
 * screen exists only before the first claim. Everything seeded here is invented
 * demo data — the README and the docs say so under the screenshots, so keep it
 * that way: no real shops, no real ratings. The one cross-reference the README
 * prose makes must hold: Mr. Color Thinner at 0 on hand, sitting on a *pending*
 * Mecha Supply Co order. Nothing is written through the browser: every dialog
 * is filled for the picture and abandoned by the next navigation.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { STORAGE_STATE, apiContext } from "./api";
import { SCREENSHOTS, THEMES, anonymousContext, save, type Theme } from "./screenshots";

const DAY = 24 * 60 * 60 * 1000;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString();
const day = (daysAgo: number) => iso(daysAgo).slice(0, 10);

test.describe.configure({ mode: "serial" });
test.skip(!SCREENSHOTS, "screenshot capture runs only with SCREENSHOTS=1");

// Dark: the default look (design §13). A browser with no stored preference
// follows its device, and Playwright's device is light unless told otherwise.
test.use({
  deviceScaleFactor: 2,
  viewport: { width: 1440, height: 900 },
  colorScheme: "dark",
  // A capture that cannot find its element should say so in seconds, not sit
  // out the whole test timeout.
  actionTimeout: 15_000,
});

type Order = { id: string; items: { spawned_kit_ids: string[] }[] };

test("seed the demo collection and capture the screenshots", async ({ page, browser }) => {
  test.setTimeout(420_000);
  const api = await apiContext();
  const post = async (route: string, json: object) => {
    const resp = await api.post(route, { data: json });
    expect(resp.ok(), `${route}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const patch = async (route: string, json: object) => {
    const resp = await api.patch(route, { data: json });
    expect(resp.ok(), `${route}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };

  // Refuse to seed into a database that already holds anything — this spec is
  // for the throwaway demo DB, and a stray run against dev data would pollute it.
  const existing = await (await api.get("/retailers")).json();
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
  const decals = await post("/upgrades", {
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
  const historic: Order = await post("/orders", {
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
  const bench: Order = await post("/orders", {
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
  const shelf: Order = await post("/orders", {
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
  const kitId = (order: Order, line: number, n = 0) => order.items[line].spawned_kit_ids[n];

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

  // --- the docs' extra state ----------------------------------------------------
  // An applied upgrade, so the kit editor has something to withdraw; a token, so
  // the Access tokens page has a row. The token's secret is never shown: the
  // page lists it by prefix, and the one-time card is not captured.
  await post(`/upgrades/${decals.id}/apply`, { kit_id: kitId(shelf, 3), quantity: 1 });
  await post("/auth/tokens", {
    name: "Claude Desktop on the laptop",
    scopes: ["collection:read", "collection:write"],
  });

  // A starter sheet to preview: the real header from the API, four invented
  // rows under it — two kits on one Side 7 order, one waiting at Orbit, one with
  // no purchase at all. Previewed only, never applied.
  const header = (await (await api.get("/export/starter-sheet.csv?examples=false")).text())
    .trim()
    .split("\n")[0]
    .split(",");
  const csvRow = (row: Record<string, string>) =>
    header.map((column) => row[column] ?? "").join(",");
  const starterSheet = Buffer.from(
    [
      header.join(","),
      csvRow({ kit_name: "HG Gundam Aerial Rebuild", grade: "HG", status: "backlog", quantity: "1", retailer: "Side 7 Hobby Works", order_date: day(2), order_number: "S7-20260910", unit_price: "15.00", received: "yes" }),
      csvRow({ kit_name: "HG Darilbalde", grade: "HG", status: "backlog", quantity: "1", retailer: "Side 7 Hobby Works", order_date: day(2), order_number: "S7-20260910", unit_price: "18.00", received: "yes" }),
      csvRow({ kit_name: "MG Gundam Barbatos", grade: "MG", status: "ordered", quantity: "1", retailer: "Orbit Hobby Depot", order_date: day(1), order_number: "OHD-5602", unit_price: "48.00", received: "no" }),
      csvRow({ kit_name: "HG Gundam Schwarzette", grade: "HG", status: "backlog", quantity: "1" }),
      "",
    ].join("\n"),
  );
  await api.dispose();

  // --- capture, once per theme --------------------------------------------------
  // The dark pass is the test's own page. The light pass is a second context
  // whose device is light and that holds no stored preference — what a light-mode
  // browser sees on first visit (§13.1: the same tokens under [data-theme="light"]).
  for (const theme of THEMES) {
    const context =
      theme === "dark"
        ? null
        : await browser.newContext({
            storageState: STORAGE_STATE,
            colorScheme: "light",
            deviceScaleFactor: 2,
            viewport: { width: 1440, height: 900 },
          });
    const p = context ? await context.newPage() : page;
    await captureSignedIn(p, theme, starterSheet);
    if (context) await context.close();

    // The sign-in screen (local mode): a context with no session cookie.
    const anonymous = await anonymousContext(browser, theme, 720);
    const anonymousPage = await anonymous.newPage();
    await anonymousPage.goto("/");
    await expect(anonymousPage.getByRole("button", { name: "Sign in" })).toBeVisible();
    await save(anonymousPage, "sign-in", theme);
    await anonymous.close();
  }
});

/** Every signed-in capture, in one theme. Each starts with its own navigation,
 *  which is also what discards the dialog the previous one left open. */
async function captureSignedIn(p: Page, theme: Theme, starterSheet: Buffer): Promise<void> {
  const shot = async (
    name: string,
    size: { width: number; height: number },
    act: () => Promise<Page | Locator>,
  ) => {
    await p.setViewportSize(size);
    await save(await act(), name, theme);
  };
  // Today on the browser's own calendar, matching what the date inputs accept.
  const today = (() => {
    const shifted = new Date();
    shifted.setMinutes(shifted.getMinutes() - shifted.getTimezoneOffset());
    return shifted.toISOString().slice(0, 10);
  })();
  await p.goto("/");
  await expect(p.locator("html")).toHaveAttribute("data-theme", theme);

  // Home (§13.2, #233): the bench, the two strips and the mail columns, all
  // populated by the seed above.
  await shot("home", { width: 1440, height: 1000 }, async () => {
    await p.goto("/");
    await expect(p.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
    // The bench card, a completed row and an in-transit card, from the seed.
    await expect(
      p.getByRole("heading", { level: 3, name: "HG Sinanju Stein (Narrative Ver.)" }),
    ).toBeVisible();
    await expect(p.getByText("MG RX-78-2 Ver. 3.0")).toBeVisible();
    await expect(p.getByText("HG Unicorn Gundam (Perfectibility)")).toBeVisible();
    await expect(p.getByTestId("home-count-mail")).not.toHaveText("0");
    return p;
  });

  // Kits, filtered to the backlog through the URL — the bookmarkable view the
  // docs describe.
  await shot("kits", { width: 1440, height: 820 }, async () => {
    await p.goto("/kits?status=backlog");
    await expect(p.getByLabel("Filter by status")).toHaveValue("backlog");
    await expect(p.getByText("HG Zaku II").first()).toBeVisible();
    await expect(p.getByText("HG Gouf Custom")).toBeVisible();
    return p;
  });

  // The Add kit dialog, filled in for a kit that was never on an order.
  await shot("kit-form", { width: 1440, height: 900 }, async () => {
    await p.goto("/kits");
    await p.getByRole("button", { name: "Add kit" }).click();
    const dialog = p.getByRole("dialog", { name: "Add kit" });
    await dialog.getByPlaceholder("RX-79(G) Gundam Ground Type").fill("HG Gundam Calibarn");
    await dialog.getByPlaceholder("HG", { exact: true }).fill("HG");
    await dialog.getByPlaceholder("HGUC 210").fill("HG 1/144 #26");
    await dialog.getByPlaceholder("Iron-Blooded Orphans").fill("The Witch from Mercury");
    await dialog.getByLabel("Status").selectOption("backlog");
    await dialog.getByRole("heading", { name: "Add kit" }).click(); // drop the focus ring
    return dialog;
  });

  // Orders, with the pending Mecha Supply Co order expanded so its lines show.
  await shot("orders", { width: 1440, height: 820 }, async () => {
    await p.goto("/orders");
    // `visible`: the row also holds the number for where the table folds its
    // column away (#258), hidden at this width.
    await expect(p.getByText("MS-91055").filter({ visible: true })).toBeVisible();
    await p.getByRole("row").filter({ hasText: "MS-91055" }).first().click();
    await expect(p.getByText("Mr. Color Thinner 400")).toBeVisible();
    return p;
  });

  // The New order dialog: a two-copy kit line and a consumable chosen through
  // the catalogue picker, still pending — stock waits for the arrival.
  await shot("order-form", { width: 1440, height: 1100 }, async () => {
    await p.goto("/orders");
    await p.getByRole("button", { name: "New order" }).click();
    const dialog = p.getByRole("dialog", { name: "New order" });
    await dialog.locator('select[name="retailer_id"]').selectOption({ label: "Mecha Supply Co" });
    await dialog.getByLabel("Currency").fill("JPY");
    await dialog.getByLabel("Order number").fill("MS-91201");
    await dialog.getByLabel("Delivery service").fill("Japan Post EMS");
    await dialog.getByPlaceholder("Kit name *").fill("HG Zaku II");
    await dialog.getByPlaceholder("Grade *").fill("HG");
    await dialog.getByLabel("Quantity").first().fill("2");
    await dialog.getByLabel("Unit price").first().fill("1100");
    await dialog.getByRole("button", { name: "Add line" }).click();
    await dialog.locator('select:has(option[value="consumable"])').nth(1).selectOption("consumable");
    await dialog.getByLabel("Quantity").nth(1).fill("1");
    await dialog.getByLabel("Unit price").nth(1).fill("300");
    await dialog.getByPlaceholder("Search consumables…").fill("Gundam Marker");
    await dialog.getByRole("button", { name: /on hand/ }).filter({ hasText: "Gundam Marker GM02" }).click();
    await expect(dialog.getByRole("button", { name: "Change" })).toBeVisible();
    return dialog;
  });

  // Edit order on the in-transit Side 7 order: Shipped on is stored, Received
  // on filled in for the picture.
  await shot("order-edit", { width: 1440, height: 1100 }, async () => {
    await p.goto("/orders");
    await p.getByRole("row").filter({ hasText: "S7-20260812" }).getByRole("button", { name: "Edit" }).click();
    const dialog = p.getByRole("dialog", { name: "Edit order" });
    // Stored as an instant, shown on the browser's own calendar — so the date,
    // not the UTC day the seed computed.
    await expect(dialog.getByLabel("Shipped on")).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
    await dialog.getByLabel("Received on").fill(today);
    return dialog;
  });

  // Inventory, on Consumables: the thinner at 0 and the cement below its threshold.
  await shot("inventory", { width: 1440, height: 620 }, async () => {
    await p.goto("/inventory");
    await p.getByRole("button", { name: "Consumables" }).click();
    await expect(p.getByText("Mr. Color Thinner 400")).toBeVisible();
    await expect(p.getByText("restock")).toBeVisible();
    return p;
  });

  // Apply to kit, from the Upgrades tab, with the bench kit chosen.
  await shot("upgrade-apply", { width: 1440, height: 800 }, async () => {
    await p.goto("/inventory");
    await p.getByRole("button", { name: "Upgrades" }).click();
    await p
      .getByRole("row")
      .filter({ hasText: "Metal thruster set (1/144)" })
      .getByRole("button", { name: "Apply to kit" })
      .click();
    const dialog = p.getByRole("dialog", { name: /Apply/ });
    const kit = dialog.getByLabel("Kit");
    const value = await kit.locator("option", { hasText: "Sinanju Stein" }).getAttribute("value");
    await kit.selectOption(value!);
    return dialog;
  });

  // The withdrawal question in the kit editor, both choices offered and neither
  // pre-selected (§3.6).
  await shot("kit-withdraw", { width: 1440, height: 1000 }, async () => {
    // Searched for, so the row is on the first page whatever the sort.
    await p.goto("/kits?q=RG%20Nu");
    await p.getByRole("row", { name: /RG Nu Gundam/ }).getByRole("button", { name: "Edit" }).click();
    const dialog = p.getByRole("dialog", { name: "Edit RG Nu Gundam" });
    await expect(dialog.getByText("Applied upgrades")).toBeVisible();
    await dialog.getByRole("button", { name: "Withdraw…" }).click();
    await expect(dialog.getByRole("button", { name: "Withdraw — return to stock" })).toBeVisible();
    return dialog;
  });

  await shot("retailers", { width: 1440, height: 560 }, async () => {
    await p.goto("/retailers");
    await expect(p.getByText("Mecha Supply Co")).toBeVisible();
    await expect(p.getByText("Orbit Hobby Depot")).toBeVisible();
    return p;
  });

  await shot("data", { width: 1440, height: 900 }, async () => {
    await p.goto("/settings/data");
    await expect(p.getByRole("button", { name: "Download full archive (.zip)" })).toBeVisible();
    return p;
  });

  // The import preview: the starter sheet read, nothing written. The card is
  // the picture — the export and template cards above it are `data.png`'s.
  await shot("import-preview", { width: 1440, height: 1100 }, async () => {
    await p.goto("/settings/data");
    await p.locator("#import-file").setInputFiles({
      name: "my-collection.csv",
      mimeType: "text/csv",
      buffer: starterSheet,
    });
    await p.getByRole("button", { name: "Preview changes" }).click();
    await expect(p.getByRole("button", { name: "Apply import" })).toBeVisible();
    return p.locator("section").filter({
      has: p.getByRole("heading", { level: 3, name: "Import", exact: true }),
    });
  });

  await shot("tokens", { width: 1440, height: 900 }, async () => {
    await p.goto("/settings/tokens");
    await expect(p.getByRole("heading", { level: 2, name: "Access tokens" })).toBeVisible();
    await expect(p.getByTestId("token-row").filter({ hasText: "Claude Desktop on the laptop" })).toBeVisible();
    return p;
  });

  await shot("settings-general", { width: 1440, height: 620 }, async () => {
    await p.goto("/settings/general");
    await expect(p.getByText("Reference currency")).toBeVisible();
    return p;
  });

  await shot("settings-language", { width: 1440, height: 800 }, async () => {
    await p.goto("/settings/language");
    await expect(p.getByText("Time zone")).toBeVisible();
    return p;
  });
}

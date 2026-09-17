/**
 * List pages on a phone and a tablet (design §13.7, #258). Below 768 px a list is
 * card rows and its filters one bottom sheet; from 768 px it stays a table, and a
 * table folds to the width its *box* has — under the rail that is the viewport
 * less 130 px, so every iPad folds something. Runs in three projects
 * (playwright.config.ts): `phone` and `tablet` with a touch screen, `app` with a
 * mouse, which is also the rail in a narrow desktop window. What it holds:
 *
 * - no list page scrolls sideways, no table is wider than its box, and no row
 *   control sits outside its list — measured on the *box* (`scrollWidth` against
 *   `clientWidth`), because a table that scrolls inside its own box never moves
 *   the document, which is how the first audit called iPad landscape fine;
 * - a fold moves what a column said and never drops it: each fact is on screen
 *   exactly once at every width, in the column or where the column went;
 * - the phone's edit controls and steppers are 44 px;
 * - the filter sheet writes the URL a link and the desktop's selects write, and
 *   all three produce the same list;
 * - a dialog closed after a rotation hands focus to the control for the *same
 *   record* — a `<tr>`'s pencil and a card's are different nodes (Codex #265,
 *   finding 1, the class; `Modal`'s `restoreFocus`, the answer) — and so does
 *   the rotation itself, when the keyboard was on a row (`useFocusAcrossShells`).
 *
 * It seeds its own rows through the API and deletes them: CI's database is
 * empty, and an empty list has no box to measure (the from-empty suite saw only
 * empty states until now). Every list is scoped by this run's tag where the page
 * has a search, so a populated dev database changes nothing. The rows carry each
 * field's *null* as well as its widest value — a kit with no scale, number or
 * series; a retailer with only a name; an order with no number or dates — since
 * a fold is a place a null can leave a dangling separator or an empty line.
 *
 * Widths, fold lines and sizes are literals from the decision record, never
 * imported from `src/` — a test that reads its expectations from the code under
 * test moves with it.
 */
import { expect, request, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { API, apiContext } from "./api";

type Size = { width: number; height: number };

// Both ends of each shell, and the four tablet widths #258's done-when names
// (768, 820, 1024, 1180). `app` has a mouse: 900 and 1100 are the rail in a
// narrow desktop window — the other pointer across the same fold lines.
const SIZES: Record<string, Size[]> = {
  app: [
    { width: 900, height: 800 },
    { width: 1100, height: 800 },
    { width: 1280, height: 720 },
  ],
  phone: [
    { width: 390, height: 844 },
    { width: 744, height: 1133 },
  ],
  tablet: [
    { width: 768, height: 1024 },
    { width: 820, height: 1180 },
    { width: 1024, height: 768 },
    { width: 1180, height: 820 },
    { width: 1366, height: 1024 },
  ],
};
const sizesFor = (project: string): Size[] => {
  const sizes = SIZES[project];
  if (!sizes) throw new Error(`lists.spec.ts has no viewports for the "${project}" project`);
  return sizes;
};
const isPhone = (size: Size) => size.width < 768;

/** The fold lines, in px of the table's box at the default 16 px rem (§13.7,
 *  "Built — #258"): at or above it the column is a column — at every viewport,
 *  the desktop's included. */
const FOLD = {
  orderNumber: 1056,
  orderDates: 960,
  kitGrade: 768,
  retailerNotes: 736,
  tokenTable: 576,
};

// Digits, not base 36: the tag is a word of the retailer's name and a segment of
// the order number, the two cells that set their columns' minimum widths, and
// table cells set figures tabular — so every run's rows are the same width to
// the pixel. In letters the table needed up to 25 px more from one run to the
// next, and a fit that depends on which letters the clock dealt is not a test.
const suffix = String(Date.now()).slice(-8);
const TAG = `E2E Lists ${suffix}`;
const q = encodeURIComponent(TAG);
const DAY = 86_400_000;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString();
const day = (daysAgo: number) => iso(daysAgo).slice(0, 10);

const NAMES = {
  retailer: `${TAG} Hobby Works`,
  bareRetailer: `${TAG} Bare Shop`,
  twin: `${TAG} Twin`,
  bareKit: `${TAG} Bare`,
  transitKit: `${TAG} Shipped Kit`,
  tool: `${TAG} Nippers`,
  consumable: `${TAG} Cement`,
  upgrade: `${TAG} Thrusters`,
  display: `${TAG} Action Base`,
};
const SERIES = `${TAG} Saga`;
const NOTES = "Double-boxes everything and answers email within the hour, which is rarer than it should be.";
const ORDER_NUMBER = `LST-${suffix}-0001`;
const TRACKING = "EJ482113905JP";
const SHIPPED_TITLE = "Shipped by the retailer";
const RECEIVED_TITLE = "Delivered · days in transit";

const seeded: { route: string; id: string }[] = [];
let retailerId = "";

async function post<T extends { id: string }>(api: APIRequestContext, route: string, data: object): Promise<T> {
  const resp = await api.post(route, { data });
  expect(resp.ok(), `${route}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const row = (await resp.json()) as T;
  // Newest first: an order goes before the retailer and the catalog rows it names.
  seeded.unshift({ route, id: row.id });
  return row;
}

test.beforeAll(async () => {
  const api = await apiContext();
  const retailer = await post(api, "/retailers", {
    name: NAMES.retailer,
    url: "https://lists-e2e.example/a-shop-with-a-long-address",
    rating: 5,
    packing_quality: "below_average",
    shipping_speed: "very_fast",
    would_order_again: "maybe",
    notes: NOTES,
  });
  retailerId = retailer.id;
  await post(api, "/retailers", { name: NAMES.bareRetailer });

  // Two kits under one name — an order line of two spawns exactly this — so
  // "the control for the same record" cannot be answered by the name alone.
  for (let n = 0; n < 2; n += 1) {
    await post(api, "/kits", { name: NAMES.twin, grade: "HG", kit_number: "5061234", series: SERIES });
  }
  await post(api, "/kits", { name: NAMES.bareKit, grade: "SD" }); // SD derives no scale
  // And the widest a kit row gets: rated, started and completed ("… · 12 d").
  const built = await post(api, "/kits", {
    name: `${TAG} Built`,
    grade: "MG",
    status: "complete",
    build_started_at: iso(30),
    build_completed_at: iso(18),
  });
  const rated = await api.patch(`/kits/${built.id}`, { data: { rating: 4 } });
  expect(rated.ok(), await rated.text()).toBeTruthy();

  await post(api, "/tools", {
    name: NAMES.tool,
    category: "nippers",
    quantity_on_hand: 1,
    unit_cost_reference_minor: 4500,
    unit_cost_reference_currency: "AUD",
    condition_notes: "Blade slightly worn at the tip",
  });
  const consumable = await post(api, "/consumables", {
    name: NAMES.consumable,
    category: "cement",
    quantity_on_hand: 1,
    low_stock_threshold: 2,
  });
  await post(api, "/upgrades", { name: NAMES.upgrade, manufacturer: "Metallic Forge", quantity_on_hand: 2 });
  await post(api, "/display-items", {
    name: NAMES.display,
    category: "action base",
    scale: "1/144",
    manufacturer: "Bandai",
    quantity_on_hand: 3,
    notes: "Clear, with the long arm",
  });

  const kitLine = (name: string, grade: string, price: number) => ({
    item_type: "kit",
    quantity: 1,
    unit_price_minor: price,
    currency_code: "JPY",
    kit: { name, grade },
  });
  // Three orders from one retailer on one day, so all three edit controls have
  // one accessible name ("Edit <retailer> <date>") and only the record can say
  // which is which. In transit, with everything a row can carry; a catalog
  // line, whose stock applies on receipt.
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(40),
    order_number: ORDER_NUMBER,
    delivery_service: "Japan Post EMS",
    tracking_number: TRACKING,
    tracking_url: `https://lists-e2e.example/track/${TRACKING}`,
    shipping_cost_minor: 1800,
    currency_code: "JPY",
    shipped_at: iso(4),
    items: [
      kitLine(NAMES.transitKit, "HG", 2800),
      { item_type: "consumable", quantity: 2, unit_price_minor: 400, currency_code: "JPY", catalog_ref_id: consumable.id },
    ],
  });
  // Received, shipped before that: both dates. And pending with nothing: no
  // number, no dates, no tracking.
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(40),
    order_number: `LST-${suffix}-0002`,
    currency_code: "JPY",
    shipped_at: iso(30),
    received: true,
    received_at: iso(21),
    items: [kitLine(`${TAG} Received Kit`, "MG", 5500)],
  });
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(40),
    currency_code: "JPY",
    items: [kitLine(`${TAG} Pending Kit`, "RG", 3300)],
  });
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  for (const { route, id } of seeded) await api.delete(`${route}/${id}`); // a 404 is a row a test deleted
  seeded.length = 0;
  await api.dispose();
});

// ---------------------------------------------------------------------------

const main = (page: Page): Locator => page.locator("main");
const shown = (locator: Locator): Locator => locator.filter({ visible: true });

/** A list row in whichever shape the shell gives it: a table row or a card. */
const rowOf = (page: Page, text: string): Locator =>
  shown(main(page).locator("tbody tr, li")).filter({ hasText: text });

async function openList(page: Page, path: string, anchor: string): Promise<void> {
  await page.goto(path);
  // A shown match: on a table shell the retailer's name is first an <option> of
  // the inline filter, which no closed select displays.
  await expect(shown(main(page).getByText(anchor)).first()).toBeVisible();
}

async function expandEveryOrder(page: Page): Promise<void> {
  const closed = main(page).getByRole("button", { name: /^Show line items/ });
  while ((await closed.count()) > 0) await closed.first().click();
}

/** The width the container queries read: the table box's content width. */
const boxWidth = (page: Page): Promise<number> =>
  shown(main(page).locator(".overflow-x-auto").filter({ has: page.locator("table") }))
    .first()
    .evaluate((box) => box.clientWidth);

/** The document does not scroll sideways, no table is wider than its box, and
 *  every control of every list is inside its list and the viewport. */
async function expectFits(page: Page, label: string): Promise<void> {
  const report = await page.evaluate(() => {
    const onScreen = (element: Element) => element.getClientRects().length > 0;
    const root = document.querySelector("main");
    if (!root) return null;
    const boxes = [...root.querySelectorAll<HTMLElement>(".overflow-x-auto")].filter(
      (box) => box.querySelector("table") && onScreen(box),
    );
    const cardLists = [...root.querySelectorAll<HTMLElement>("ul")].filter(onScreen);
    const escaped: string[] = [];
    let controls = 0;
    for (const list of [...boxes, ...cardLists]) {
      const bounds = list.getBoundingClientRect();
      for (const control of list.querySelectorAll<HTMLElement>("button, a[href]")) {
        if (!onScreen(control)) continue;
        controls += 1;
        const rect = control.getBoundingClientRect();
        const inside =
          rect.left >= bounds.left - 0.5 &&
          rect.right <= bounds.right + 0.5 &&
          rect.left >= -0.5 &&
          rect.right <= innerWidth + 0.5;
        if (!inside) {
          escaped.push(
            `${control.getAttribute("aria-label") ?? control.textContent?.trim()} [${Math.round(rect.left)}–${Math.round(rect.right)}] outside [${Math.round(bounds.left)}–${Math.round(bounds.right)}]`,
          );
        }
      }
    }
    return {
      document: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
      boxes: boxes.map((box) => [box.scrollWidth, box.clientWidth]),
      lists: boxes.length + cardLists.length,
      controls,
      escaped,
    };
  });
  if (!report) throw new Error(`${label}: no <main> on the page`);
  // A page with no list, or a list with no control, measured nothing.
  expect(report.lists, `${label}: no list on the page`).toBeGreaterThan(0);
  expect(report.controls, `${label}: no control in any list`).toBeGreaterThan(0);
  expect.soft(report.document[0], `${label}: the document scrolls sideways`).toBeLessThanOrEqual(report.document[1]);
  for (const [scroll, client] of report.boxes) {
    expect.soft(scroll, `${label}: a table is wider than its box`).toBeLessThanOrEqual(client);
  }
  expect.soft(report.escaped, `${label}: controls outside their list`).toEqual([]);
}

// ---------------------------------------------------------------------------

test("no list page scrolls sideways, no table outgrows its box, no row control is off its list", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  const pages: [string, string][] = [
    [`/kits?q=${q}`, NAMES.twin],
    [`/orders?q=${q}`, NAMES.retailer],
    [`/retailers?q=${q}`, NAMES.retailer],
    ["/inventory", NAMES.tool],
    ["/inventory?tab=consumables", NAMES.consumable],
    ["/inventory?tab=upgrades", NAMES.upgrade],
    ["/inventory?tab=display-items", NAMES.display],
  ];
  for (const size of sizesFor(testInfo.project.name)) {
    await page.setViewportSize(size);
    for (const [path, anchor] of pages) {
      await openList(page, path, anchor);
      // Cards below the line, a table from it up — never both, never neither.
      // Soft, so a wrong shape still gets measured: on the code before #258 a
      // phone has a table, and it is the table's overflow that is the defect.
      await expect
        .soft(shown(main(page).locator("table")), `${path} at ${size.width} px: cards on a phone, a table from 768 px`)
        .toHaveCount(isPhone(size) ? 0 : 1);
      if (path.startsWith("/orders")) await expandEveryOrder(page);
      await expectFits(page, `${path} at ${size.width} px`);
    }
  }
});

test("at no box width is a table wider than its box", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "a phone has cards, not a table to fold");
  // The sizes above are nine points on a line; a fold line a few pixels short
  // of what its table needs is a band a few pixels wide between them — the
  // second Orders fold was exactly that for an afternoon, overflowing from 866
  // to 927 px and nowhere a viewport was looking. So: every width. The box is
  // given each width from a little under the rail's narrowest (638 px, the
  // viewport less 130 at 768 — a real iPad; the 4 px under it is slack the
  // fully folded Orders table, which needs 625, has to keep) to the desktop's
  // at 1600 px (1300), by hand — container queries answer the box, whatever set
  // its width, so the viewport it is done under does not matter.
  // `tablet` runs it with a touch screen and `app` with a mouse: the 44 px
  // pencil must cost the table nothing.
  await page.setViewportSize({ width: 1270, height: 900 });
  for (const [path, anchor, from, to] of [
    [`/kits?q=${q}`, NAMES.twin, 634, 1300],
    [`/orders?q=${q}`, NAMES.retailer, 634, 1300],
    [`/retailers?q=${q}`, NAMES.retailer, 634, 1300],
  ] as const) {
    await openList(page, path, anchor);
    if (path.startsWith("/orders")) await expandEveryOrder(page);
    const overflowing = await sweepBox(page, from, to);
    expect(overflowing, `${path}: no table box on the page`).not.toBeNull();
    expect.soft(overflowing?.measured, `${path}: every width measured`).toBe(to - from + 1);
    expect.soft(overflowing?.widths, `${path}: box widths at which the list is wider than its box`).toEqual([]);
  }
});

/** Give the list's box every width from `first` to `last` and report the ones at
 *  which the list — the table, or the cards that replace it — is wider than the
 *  box or has a control past its edge. */
function sweepBox(page: Page, first: number, last: number): Promise<{ widths: number[]; measured: number } | null> {
  return page.evaluate(
      ([from, to]) => {
        const onScreen = (element: Element) => element.getClientRects().length > 0;
        const root = document.querySelector("main") as HTMLElement;
        const box = [...root.querySelectorAll<HTMLElement>(".overflow-x-auto")].find((el) => el.querySelector("table"));
        if (!box) return null;
        // The element the container queries read: the box, or the wrapper round
        // it where a list swaps the table for cards (Access tokens).
        const container = (box.closest('[class*="@container"]') as HTMLElement | null) ?? box;
        const widths: number[] = [];
        let measured = 0;
        for (let width = from; width <= to; width += 1) {
          container.style.width = `${width}px`;
          const list = onScreen(box) ? box : (container.querySelector("ul") as HTMLElement);
          if (!list || !onScreen(list)) return { widths: [-width], measured };
          measured += 1;
          const controls = [...list.querySelectorAll<HTMLElement>("button, a[href]")].filter(onScreen);
          const edge = list.getBoundingClientRect().right + 0.5;
          if (list.scrollWidth > list.clientWidth || controls.some((control) => control.getBoundingClientRect().right > edge)) {
            widths.push(width);
          }
        }
        container.style.width = "";
        return { widths, measured };
      },
      [first, last],
  );
}

test("a phone's edit controls and steppers are 44 px", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the card rows are the phone shell's");
  const pages: [string, string, RegExp][] = [
    [`/kits?q=${q}`, NAMES.twin, /^Edit /],
    [`/orders?q=${q}`, NAMES.retailer, /^Edit /],
    [`/retailers?q=${q}`, NAMES.retailer, /^Edit /],
    ["/inventory", NAMES.tool, /^(Edit|Remove one|Add one) /],
    ["/inventory?tab=consumables", NAMES.consumable, /^(Edit|Remove one|Add one) /],
    ["/inventory?tab=upgrades", NAMES.upgrade, /^(Edit|Remove one|Add one) /],
    ["/inventory?tab=display-items", NAMES.display, /^(Edit|Remove one|Add one) /],
  ];
  for (const size of sizesFor("phone")) {
    await page.setViewportSize(size);
    for (const [path, anchor, names] of pages) {
      await openList(page, path, anchor);
      const controls = await main(page).getByRole("button", { name: names }).all();
      expect(controls.length, `${path}: no control found by ${names}`).toBeGreaterThan(0);
      for (const control of controls) {
        const box = await control.boundingBox();
        const name = await control.getAttribute("aria-label");
        expect.soft(box?.width, `${name} at ${size.width} px: width`).toBeGreaterThanOrEqual(44);
        expect.soft(box?.height, `${name} at ${size.width} px: height`).toBeGreaterThanOrEqual(44);
      }
    }
  }
});

test("a fold moves what a column said and never drops it", async ({ page }, testInfo) => {
  // An honest skip: every `phone` size is below the line, and a loop over none
  // of them would pass having looked at nothing.
  test.skip(testInfo.project.name === "phone", "a phone has cards, not a table to fold");
  test.setTimeout(120_000);
  /** On screen exactly once: not dropped, and not said twice. */
  const once = (scope: Locator, target: Locator | string | RegExp, label: string) =>
    expect
      .soft(shown(typeof target === "string" || target instanceof RegExp ? scope.getByText(target) : target), label)
      .toHaveCount(1);
  const header = (name: string) => shown(main(page).getByRole("columnheader", { name, exact: true }));
  const unfolded = (box: number, line: number) => box >= line;

  for (const size of sizesFor(testInfo.project.name)) {
    await page.setViewportSize(size);
    const at = `at ${size.width} px`;

    // --- Kits: Grade and Scale, to the name's second line.
    await openList(page, `/kits?q=${q}`, NAMES.twin);
    let box = await boxWidth(page);
    for (const name of ["Grade", "Scale"]) {
      await expect.soft(header(name), `Kits "${name}" column ${at} (box ${box})`).toHaveCount(unfolded(box, FOLD.kitGrade) ? 1 : 0);
    }
    const twin = rowOf(page, NAMES.twin).first();
    await once(twin, twin.getByText("HG", { exact: true }), `Kits ${at}: the grade`);
    await once(twin, twin.getByText("1/144", { exact: true }), `Kits ${at}: the scale`);
    await once(twin, /5061234/, `Kits ${at}: the kit number`);
    // The nulls: no scale, number or series. The grade still shows, once, and a
    // folded line ends on it — no separator with nothing after it.
    const bare = rowOf(page, NAMES.bareKit);
    await once(bare, bare.getByText("SD", { exact: true }), `Kits ${at}: a bare kit's grade`);
    // textContent, so shown or not: the line under the name is the grade and
    // nothing else — no separator with nothing after it.
    await expect.soft(bare.locator("td").first(), `Kits ${at}: a bare kit's second line`).toHaveText(`${NAMES.bareKit}SD`);

    // --- Orders: the number under the retailer; the dates under the chip; the
    // tracking into the expanded lines.
    await openList(page, `/orders?q=${q}`, NAMES.retailer);
    box = await boxWidth(page);
    await expect.soft(header("Order #"), `Orders "Order #" column ${at} (box ${box})`).toHaveCount(unfolded(box, FOLD.orderNumber) ? 1 : 0);
    for (const name of ["Shipped", "Received", "Tracking"]) {
      await expect.soft(header(name), `Orders "${name}" column ${at} (box ${box})`).toHaveCount(unfolded(box, FOLD.orderDates) ? 1 : 0);
    }
    const transit = rowOf(page, ORDER_NUMBER);
    await once(transit, ORDER_NUMBER, `Orders ${at}: the order number`);
    await once(transit, transit.getByTitle(SHIPPED_TITLE).filter({ hasText: /\d/ }), `Orders ${at}: the ship date`);
    await once(transit, /in transit/, `Orders ${at}: the days in transit`);
    const received = rowOf(page, `LST-${suffix}-0002`);
    await once(received, received.getByTitle(SHIPPED_TITLE).filter({ hasText: /\d/ }), `Orders ${at}: a received order's ship date`);
    await once(received, received.getByTitle(RECEIVED_TITLE).filter({ hasText: /\d/ }), `Orders ${at}: the delivery date`);
    // The nulls: a pending order has no number and no dates. Folded, that is
    // nothing under the name or the chip — not an empty line, not a dash.
    const pending = rowOf(page, "Pending");
    await expect.soft(pending.getByTitle(SHIPPED_TITLE).filter({ hasText: /\d/ }), `Orders ${at}: a pending order has no ship date`).toHaveCount(0);
    if (!unfolded(box, FOLD.orderDates)) {
      await expect.soft(shown(pending.getByTitle(SHIPPED_TITLE)), `Orders ${at}: no empty folded line`).toHaveCount(0);
    }
    await expandEveryOrder(page);
    await once(main(page), TRACKING, `Orders ${at}: the tracking number`);
    await expect.soft(shown(main(page).getByRole("link", { name: TRACKING })), `Orders ${at}: tracking stays a link`).toHaveCount(1);

    // --- Retailers: Notes, to a second line under the name.
    await openList(page, `/retailers?q=${q}`, NAMES.retailer);
    box = await boxWidth(page);
    await expect.soft(header("Notes"), `Retailers "Notes" column ${at} (box ${box})`).toHaveCount(unfolded(box, FOLD.retailerNotes) ? 1 : 0);
    await once(rowOf(page, NAMES.retailer), NOTES, `Retailers ${at}: the notes`);
    await expect.soft(rowOf(page, NAMES.bareRetailer).locator("td").first(), `Retailers ${at}: a bare retailer is its name`).toHaveText(NAMES.bareRetailer);
  }
});

test("the desktop folds one thing, and only where its box is short", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "a table shell's");
  // Beside the sidebar a list's box is the viewport less 306 px (the sidebar, the
  // page's padding, the box's own border). `main` left the
  // desktop alone, and with ordinary rows its Orders table was 60 px wider than
  // that box at 1280 px, the edit control off its edge (#258: the demo data the
  // widths were measured on has no order both shipped and received). The folds
  // answer the box at every width (the owner's call, 2026-09-18), so the literal
  // expectation: from 1280 to 1361 px the order number is under the retailer and
  // nothing else has moved; from 1362 px — a 1366 px laptop, a 13-inch iPad —
  // every column is a column. A fold line drawn too high or too low fails here
  // by name, where the other tests compute the shape a box should have.
  const KITS = ["Kit", "Grade", "Scale", "Status", "Rating", "Started", "Completed"];
  const RETAILERS = ["Name", "Rating", "Packing", "Shipping", "Again?", "Notes"];
  const ORDERS = ["Date", "Retailer", "Order #", "Status", "Shipped", "Received", "Items", "Total", "Tracking"];
  for (const [width, orders] of [
    [1280, ORDERS.filter((name) => name !== "Order #")],
    [1361, ORDERS.filter((name) => name !== "Order #")],
    [1362, ORDERS],
    [1366, ORDERS],
    [1440, ORDERS],
  ] as const) {
    await page.setViewportSize({ width, height: 900 });
    for (const [path, anchor, headers] of [
      [`/kits?q=${q}`, NAMES.twin, KITS],
      [`/orders?q=${q}`, NAMES.retailer, orders],
      [`/retailers?q=${q}`, NAMES.retailer, RETAILERS],
    ] as const) {
      await openList(page, path, anchor);
      const visible = await shown(main(page).getByRole("columnheader")).allInnerTexts();
      expect.soft(visible.filter(Boolean).map((text) => text.toUpperCase()), `${path} at ${width} px`).toEqual(
        headers.map((text) => text.toUpperCase()),
      );
      if (path.startsWith("/orders")) await expandEveryOrder(page);
      await expectFits(page, `${path} at ${width} px`);
    }
  }
});

test("an order card opens its lines as the table row does", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the cards are the phone shell's");
  await openList(page, `/orders?q=${q}`, NAMES.retailer);
  const card = rowOf(page, ORDER_NUMBER);
  const toggle = card.getByRole("button", { name: /line items for/ });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(card.getByText(NAMES.transitKit)).toHaveCount(0);

  // The card itself is the tap target; the button is the keyboard's way in.
  await card.getByText(NAMES.retailer).click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveAccessibleName(/^Hide line items/);
  await expect(card.getByText(NAMES.transitKit)).toBeVisible();
  await expect(card.getByText("In Transit", { exact: true })).toBeVisible(); // the kit line's own status
  await expect(card.getByText("stock applies on receipt")).toBeVisible(); // the catalog line
  await expect(card.getByText("Shipping · Japan Post EMS")).toBeVisible();
  await expect(card.getByRole("link", { name: TRACKING })).toHaveAttribute("href", new RegExp(`${TRACKING}$`));

  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(card.getByText(NAMES.transitKit)).toHaveCount(0);

  // Edit is its own control, and does not also toggle the card.
  await card.getByRole("button", { name: /^Edit / }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("the filter sheet, a link and the desktop's selects produce the same list", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the sheet is the phone shell's");
  const phone = sizesFor("phone")[0];
  /** This run's rows, by name, in the order the list shows them — a card's
   *  title and a table row's name are both the row's first medium-weight line. */
  const names = () =>
    rowOf(page, TAG).evaluateAll((rows) =>
      rows.map((row) => row.querySelector(".font-medium")?.textContent?.trim() ?? "(no name)"),
    );
  const opener = page.getByRole("button", { name: /^Filter and sort/ });
  const sheet = page.getByRole("dialog", { name: "Filter and sort" });

  await page.setViewportSize(phone);
  await openList(page, `/kits?q=${q}`, NAMES.twin);
  await expect(opener).toHaveAccessibleName("Filter and sort");

  // Seven kits carry the tag: the twins, the bare one, the built one, and one
  // spawned by each order. Nothing chosen: the button counts the whole (searched) list, and
  // applying it writes nothing — every parameter is dropped at its default.
  await opener.click();
  await expect(sheet.getByRole("button", { name: "Show 7 kits" })).toBeVisible();
  await expect(sheet.getByRole("button", { name: /^All statuses/ })).toHaveAttribute("aria-pressed", "true");
  await sheet.getByRole("button", { name: "Show 7 kits" }).click();
  await expect(sheet).toHaveCount(0);
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ q: TAG });

  // A draft is a draft: choosing and then leaving changes nothing.
  await opener.click();
  await sheet.getByRole("button", { name: /^Backlog/ }).click();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ q: TAG });

  // Status, series and sort, in one navigation; the button says what it shows.
  await opener.click();
  await expect(sheet.getByRole("button", { name: /^All statuses/ }), "a closed draft is forgotten").toHaveAttribute("aria-pressed", "true");
  await sheet.getByRole("button", { name: /^Backlog/ }).click();
  await sheet.getByLabel("Filter by series").selectOption(SERIES);
  await sheet.getByRole("button", { name: "Name A–Z" }).click();
  await sheet.getByRole("button", { name: "Show 2 kits" }).click();
  await expect(sheet).toHaveCount(0);
  const written = new URL(page.url()).searchParams;
  expect(Object.fromEntries(written)).toEqual({ q: TAG, status: "backlog", series: SERIES, sort: "name" });
  await expect(opener).toHaveAccessibleName("Filter and sort, 2 filters active");
  await expect(rowOf(page, TAG)).toHaveCount(2);
  const fromSheet = await names();
  expect(fromSheet).toEqual([NAMES.twin, NAMES.twin]);

  // Reopened, the sheet shows the URL's state; Clear empties the draft.
  await opener.click();
  await expect(sheet.getByRole("button", { name: /^Backlog/ })).toHaveAttribute("aria-pressed", "true");
  await expect(sheet.getByLabel("Filter by series")).toHaveValue(SERIES);
  await expect(sheet.getByRole("button", { name: "Name A–Z" })).toHaveAttribute("aria-pressed", "true");
  await sheet.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(sheet.getByRole("button", { name: "Show 7 kits" })).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Newest first" })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");

  // The same URL, pasted; and on the desktop, where the selects read it.
  const url = page.url();
  await page.goto(url);
  await expect(rowOf(page, TAG)).toHaveCount(2);
  expect(await names()).toEqual(fromSheet);
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(url);
  await expect(page.getByLabel("Filter by status")).toHaveValue("backlog");
  await expect(page.getByLabel("Filter by series")).toHaveValue(SERIES);
  await expect(page.getByLabel("Sort")).toHaveValue("name");
  await expect(rowOf(page, TAG)).toHaveCount(2);

  // Home's *view all* link is `?status=backlog&sort=recent` (§13.4); the sheet
  // writes the status alone, the sort being the default. One list.
  await page.setViewportSize(phone);
  await openList(page, `/kits?status=backlog&sort=recent&q=${q}`, NAMES.twin);
  const fromLink = await names();
  await openList(page, `/kits?q=${q}`, NAMES.twin);
  await opener.click();
  await sheet.getByRole("button", { name: /^Backlog/ }).click();
  await sheet.getByRole("button", { name: /^Show \d+ kits?$/ }).click();
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ q: TAG, status: "backlog" });
  await expect(opener).toHaveAccessibleName("Filter and sort, 1 filter active");
  expect(await names()).toEqual(fromLink);

  // Orders: the stage and the retailer, the same way.
  await openList(page, `/orders?q=${q}`, NAMES.retailer);
  await opener.click();
  await sheet.getByRole("button", { name: /^Shipped/ }).click();
  await sheet.getByLabel("Filter by retailer").selectOption({ label: NAMES.retailer });
  await sheet.getByRole("button", { name: "Recently changed" }).click();
  await sheet.getByRole("button", { name: "Show 1 order" }).click();
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
    q: TAG,
    status: "in_transit",
    retailer: retailerId,
    sort: "recent",
  });
  await expect(rowOf(page, TAG)).toHaveCount(1);
  await expect(rowOf(page, ORDER_NUMBER)).toBeVisible();
});

test("the filter sheet is a dialog: the page is inert under it, and closing it returns the keyboard", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the sheet is the phone shell's");
  await openList(page, `/kits?q=${q}`, NAMES.twin);
  const opener = page.getByRole("button", { name: /^Filter and sort/ });
  // First, so a page with no such control fails here, by name, in five seconds —
  // not thirty seconds into `focus()` (the negative control's one timeout).
  await expect(opener).toBeVisible();
  await opener.focus();
  await page.keyboard.press("Enter");
  const sheet = page.getByRole("dialog", { name: "Filter and sort" });
  await expect(sheet).toBeVisible();
  expect(await page.locator("#root").evaluate((root) => (root as HTMLElement).inert)).toBe(true);
  // It rises from the foot of the screen and spans it.
  const [box, viewport] = [await sheet.boundingBox(), page.viewportSize()];
  expect([box?.x, box?.width, Math.round((box?.y ?? 0) + (box?.height ?? 0))]).toEqual([0, viewport?.width, viewport?.height]);
  // Tab stays inside it, both ways round.
  for (const key of ["Tab", "Shift+Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    expect(await sheet.evaluate((dialog) => dialog.contains(document.activeElement)), `after ${key}`).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(opener).toBeFocused();
  expect(await page.locator("#root").evaluate((root) => (root as HTMLElement).inert)).toBe(false);
});

test("a dialog closed after a rotation gives focus to the control for the same record", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "an iPad mini turning: 744 px one way, 1133 the other");
  test.setTimeout(120_000);
  // The row's pencil is a `<tr>`'s on one side of the 768 px line and a card's on
  // the other — two nodes, so the one that opened the dialog is gone when it
  // closes. The second of two same-named kits and the second of three same-day
  // orders, so the name cannot find them; *Apply to kit*, which every upgrade's
  // button is called; the filter sheet, whose opener has no counterpart by name
  // at all.
  const portrait = { width: 744, height: 1133 };
  const landscape = { width: 1133, height: 744 };
  const cases: { path: string; anchor: string; opener: (page: Page) => Locator }[] = [
    { path: `/kits?q=${q}`, anchor: NAMES.twin, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.twin}` }).nth(1) },
    { path: `/orders?q=${q}`, anchor: NAMES.retailer, opener: (p) => main(p).getByRole("button", { name: new RegExp(`^Edit ${NAMES.retailer} `) }).nth(1) },
    { path: `/retailers?q=${q}`, anchor: NAMES.retailer, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.retailer}` }) },
    { path: "/inventory", anchor: NAMES.tool, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.tool}` }) },
    { path: "/inventory?tab=consumables", anchor: NAMES.consumable, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.consumable}` }) },
    { path: "/inventory?tab=display-items", anchor: NAMES.display, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.display}` }) },
    { path: "/inventory?tab=upgrades", anchor: NAMES.upgrade, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.upgrade}` }) },
    { path: "/inventory?tab=upgrades", anchor: NAMES.upgrade, opener: (p) => rowOf(p, NAMES.upgrade).getByRole("button", { name: "Apply to kit" }) },
  ];
  for (const { path, anchor, opener } of cases) {
    for (const [from, to] of [
      [portrait, landscape],
      [landscape, portrait],
    ]) {
      await page.setViewportSize(from);
      await openList(page, path, anchor);
      const control = opener(page);
      const label = `${path} "${await control.innerText().catch(() => "")}${(await control.getAttribute("aria-label")) ?? ""}": ${from.width} → ${to.width} px`;
      // By keyboard, so the opener is unarguably the focused element at open.
      await control.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.setViewportSize(to);
      await expect(shown(main(page).locator("table")), label).toHaveCount(isPhone(to) ? 0 : 1);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect.soft(opener(page), label).toBeFocused({ timeout: 2_000 });
    }
  }

  // The filter sheet stays a dialog across the line, and the filters that stand
  // where its opener stood take the keyboard when it closes.
  for (const path of [`/kits?q=${q}`, `/orders?q=${q}`]) {
    await page.setViewportSize(portrait);
    await openList(page, path, TAG);
    await page.getByRole("button", { name: /^Filter and sort/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog", { name: "Filter and sort" })).toBeVisible();
    await page.setViewportSize(landscape);
    await expect(page.getByRole("dialog", { name: "Filter and sort" }), `${path}: the sheet survives the turn`).toBeVisible();
    await page.keyboard.press("Escape");
    await expect.soft(page.getByLabel("Filter by status"), `${path}: 744 → 1133 px`).toBeFocused({ timeout: 2_000 });
  }
});

test("the keyboard keeps its place on a row when the rows change shape under it", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "an iPad mini turning: 744 px one way, 1133 the other");
  test.setTimeout(120_000);
  // No dialog this time: the focused control itself is a `<tr>`'s on one side of
  // the 768 px line and a card's on the other, so crossing the line destroys it,
  // focus falls to <body>, and the next Tab starts from the top of the page.
  // `useFocusAcrossShells` puts it on the control for the same record. Found by a
  // screenshot: a full-page capture makes the viewport 1 × 1 for a moment, and a
  // focus ring that `main` drew was missing from the branch's Orders capture.
  const portrait = { width: 744, height: 1133 };
  const landscape = { width: 1133, height: 744 };
  const cases: { path: string; anchor: string; control: (page: Page) => Locator }[] = [
    { path: `/kits?q=${q}`, anchor: NAMES.twin, control: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.twin}` }).nth(1) },
    { path: `/orders?q=${q}`, anchor: NAMES.retailer, control: (p) => main(p).getByRole("button", { name: /line items for/ }).nth(1) },
    { path: `/orders?q=${q}`, anchor: NAMES.retailer, control: (p) => main(p).getByRole("button", { name: new RegExp(`^Edit ${NAMES.retailer} `) }).nth(2) },
    { path: `/retailers?q=${q}`, anchor: NAMES.retailer, control: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.bareRetailer}` }) },
    { path: "/inventory?tab=consumables", anchor: NAMES.consumable, control: (p) => main(p).getByRole("button", { name: `Add one ${NAMES.consumable}` }) },
    { path: "/inventory?tab=upgrades", anchor: NAMES.upgrade, control: (p) => rowOf(p, NAMES.upgrade).getByRole("button", { name: "Apply to kit" }) },
  ];
  for (const { path, anchor, control } of cases) {
    for (const [from, to] of [
      [portrait, landscape],
      [landscape, portrait],
    ]) {
      await page.setViewportSize(from);
      await openList(page, path, anchor);
      const label = `${path} "${(await control(page).getAttribute("aria-label")) ?? (await control(page).innerText())}": ${from.width} → ${to.width} px`;
      await control(page).focus();
      await page.setViewportSize(to);
      await expect(shown(main(page).locator("table")), label).toHaveCount(isPhone(to) ? 0 : 1);
      await expect.soft(control(page), label).toBeFocused({ timeout: 2_000 });
    }
  }

  // The filters: a select on one side, the sheet's opener on the other.
  await page.setViewportSize(landscape);
  await openList(page, `/kits?q=${q}`, NAMES.twin);
  await page.getByLabel("Filter by status").focus();
  await page.setViewportSize(portrait);
  await expect.soft(page.getByRole("button", { name: /^Filter and sort/ }), "the filters: 1133 → 744 px").toBeFocused({ timeout: 2_000 });
  await page.setViewportSize(landscape);
  await expect.soft(page.getByLabel("Filter by status"), "the filters: 744 → 1133 px").toBeFocused({ timeout: 2_000 });

  // The values of "where the keyboard was" that must *not* be restored. A control
  // with no key (the search box is one node in every shell, so it simply stays);
  // and nowhere — someone who clicked away from a row did not ask to be taken
  // back to it at the next turn.
  await page.getByLabel("Search").focus();
  await page.setViewportSize(portrait);
  await expect.soft(page.getByLabel("Search"), "an unkeyed control that survives keeps focus").toBeFocused({ timeout: 2_000 });
  await main(page).getByRole("button", { name: `Edit ${NAMES.bareKit}` }).focus();
  await page.getByRole("heading", { level: 1 }).click();
  // The precondition, said out loud: the click did take focus off the row.
  expect(await page.evaluate(() => document.activeElement?.tagName), "clicking the page's title blurs the row").toBe("BODY");
  await page.setViewportSize(landscape);
  await expect(shown(main(page).locator("table"))).toHaveCount(1);
  expect
    .soft(
      await page.evaluate(() => `${document.activeElement?.tagName} ${document.activeElement?.getAttribute("aria-label") ?? ""}`.trim()),
      "a row left by clicking away is not returned to",
    )
    .toBe("BODY");

  // And what found it: there and back within one task's breath.
  await main(page).getByRole("button", { name: `Edit ${NAMES.bareKit}` }).focus();
  await page.setViewportSize({ width: 1, height: 1 });
  await page.setViewportSize(landscape);
  await expect.soft(main(page).getByRole("button", { name: `Edit ${NAMES.bareKit}` }), "1133 → 1 → 1133 px").toBeFocused({ timeout: 2_000 });
});

test("a long list's pager fits a phone", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the compact pager is the phone shell's");
  test.setTimeout(120_000);
  // Nine pages, opened in the middle: the full window there is nine entries
  // ("1 2 … 4 5 6 … 8 9"), wider at 44 px a page than the screen. Seeded here,
  // not for every project: it is eighty-one rows.
  const api = await apiContext();
  const pagerTag = `${TAG} Pager`;
  const ids: string[] = [];
  try {
    for (let n = 1; n <= 81; n += 1) {
      const resp = await api.post("/kits", { data: { name: `${pagerTag} ${String(n).padStart(2, "0")}`, grade: "HG" } });
      expect(resp.ok(), await resp.text()).toBeTruthy();
      ids.push(((await resp.json()) as { id: string }).id);
    }
    for (const size of sizesFor("phone")) {
      await page.setViewportSize(size);
      for (const at of [1, 5, 9]) {
        await openList(page, `/kits?q=${encodeURIComponent(pagerTag)}&page=${at}`, pagerTag);
        const pager = page.getByRole("navigation", { name: "Pages" });
        const label = `page ${at} of 9 at ${size.width} px`;
        await expect(pager.getByRole("button", { name: `Page ${at}`, exact: true }), label).toHaveAttribute("aria-current", "page");
        expect.soft(await pager.getByRole("button").count(), `${label}: pages offered`).toBeLessThanOrEqual(5);
        for (const button of await pager.getByRole("button").all()) {
          const box = await button.boundingBox();
          expect.soft(Math.min(box?.width ?? 0, box?.height ?? 0), `${label}: a page is a 44 px target`).toBeGreaterThanOrEqual(44);
        }
        const edges = await pager.evaluate((nav) => {
          const rect = nav.getBoundingClientRect();
          return [rect.left, rect.right, document.documentElement.scrollWidth, document.documentElement.clientWidth];
        });
        expect.soft(edges[0], `${label}: the pager starts on screen`).toBeGreaterThanOrEqual(0);
        expect.soft(edges[1], `${label}: the pager ends on screen`).toBeLessThanOrEqual(size.width);
        expect.soft(edges[2], `${label}: the document scrolls sideways`).toBeLessThanOrEqual(edges[3]);
      }
      // And it still pages: the ends are always offered.
      await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: "Page 1", exact: true }).click();
      await expect(page).toHaveURL((url) => !url.searchParams.has("page"));
      await expect(page.getByText("1–10 of 81")).toBeVisible();
    }
  } finally {
    for (const id of ids) await api.delete(`/kits/${id}`);
    await api.dispose();
  }
});

test("Access tokens is a table where its box has room and card rows where it has not", async ({ page }, testInfo) => {
  // Chosen by the box, not the shell (§13.7): the Settings pane is two columns
  // beside the rail, so an iPad in portrait is cards too. A live token with
  // every date set — an expiry, and used once — is the widest row there is.
  // Leaves a revoked row behind, as tokens.spec.ts does: nothing deletes a token.
  const api = await apiContext();
  const name = `${TAG} token for the desktop on the laptop`;
  const minted = await api.post("/auth/tokens", {
    data: { name, scopes: ["collection:read", "collection:write"], expires_at: new Date(Date.now() + 30 * DAY).toISOString() },
  });
  expect(minted.ok(), await minted.text()).toBeTruthy();
  const token = (await minted.json()) as { id: string; token: string };
  try {
    const bearer = await request.newContext({ baseURL: API, extraHTTPHeaders: { Authorization: `Bearer ${token.token}` } });
    expect((await bearer.get("/kits")).status()).toBe(200);
    await bearer.dispose();

    for (const size of sizesFor(testInfo.project.name)) {
      await page.setViewportSize(size);
      await page.goto("/settings/tokens");
      const at = `at ${size.width} px`;
      const cards = page.getByTestId("token-cards");
      const table = page.getByTestId("token-table");
      await expect(shown(page.getByText(name)), `${at}: the token is listed once`).toHaveCount(1);
      const room = await table.locator("xpath=..").evaluate((container) => container.clientWidth);
      await expect.soft(shown(table), `${at}: the table (box ${room})`).toHaveCount(room >= FOLD.tokenTable ? 1 : 0);
      await expect.soft(shown(cards), `${at}: the cards (box ${room})`).toHaveCount(room >= FOLD.tokenTable ? 0 : 1);

      const entry = shown(page.getByTestId(room >= FOLD.tokenTable ? "token-row" : "token-card")).filter({ hasText: name });
      const revoke = entry.getByRole("button", { name: "Revoke" });
      await expect(revoke, `${at}: Revoke`).toBeVisible();
      const edges = await revoke.evaluate((button) => {
        const list = button.closest('[data-testid="token-table"], [data-testid="token-cards"]') as HTMLElement;
        const [rect, bounds] = [button.getBoundingClientRect(), list.getBoundingClientRect()];
        return { right: rect.right, listRight: bounds.right, scroll: list.scrollWidth, client: list.clientWidth, doc: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      expect.soft(edges.right, `${at}: Revoke inside its list`).toBeLessThanOrEqual(edges.listRight + 0.5);
      expect.soft(edges.right, `${at}: Revoke inside the viewport`).toBeLessThanOrEqual(size.width + 0.5);
      expect.soft(edges.scroll, `${at}: the list is wider than its box`).toBeLessThanOrEqual(edges.client);
      expect.soft(edges.doc, `${at}: the document scrolls sideways`).toBeLessThanOrEqual(0);
      // A finger has no hover: the card says the time as well as the date.
      if (room < FOLD.tokenTable) await expect.soft(entry.getByText(/^Created: .*\d:\d\d/), `${at}: the instant in full`).toBeVisible();
    }

    // And every width the Settings pane's box can have below 1280 px — 396 px at
    // 768 (less on a phone), capped at 652 — cards or table, whichever it is.
    if (testInfo.project.name !== "phone") {
      await page.setViewportSize({ width: 1270, height: 900 });
      await page.goto("/settings/tokens");
      await expect(shown(page.getByText(name))).toHaveCount(1);
      const overflowing = await sweepBox(page, 300, 652);
      expect.soft(overflowing?.measured, "tokens: every width measured").toBe(353);
      expect.soft(overflowing?.widths, "tokens: box widths at which the list is wider than its box").toEqual([]);
    }
  } finally {
    await api.delete(`/auth/tokens/${token.id}`);
    await api.dispose();
  }
});

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
 *   the rotation itself, when the keyboard was on a row (`useFocusAcrossShells`);
 * - and the rule those are instances of, asked of every control there is: no
 *   change of representation — a shell, a fold, a table swapped for cards by its
 *   box — leaves the keyboard on `<body>` (Codex #266, findings 3 and 4);
 * - a card says who it is whatever stands beside it: a total in three currencies
 *   does not squeeze the retailer out, and a fact wraps where it would have
 *   ended in an ellipsis (finding 1) — and under the browser's own font-size
 *   preference, at 32 and 40 px: the names keep their room, every target is
 *   still a finger, the stepper is inside its card (findings 6 and 7);
 * - a reference's rule is decided from a rendered width — the narrow digits,
 *   the unbounded reference and the font arriving after the first paint are
 *   the controls for how it is measured (round 3).
 *
 * lists.settings.spec.ts asks the fit questions again under every date style the
 * Settings page offers (finding 2) — it changes the settings singleton, so it
 * runs where settings.spec.ts does, after everything else.
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
import { chromium, expect, request, test, type APIRequestContext, type Locator, type Page, type Route } from "@playwright/test";

import { API, APP, STORAGE_STATE, apiContext } from "./api";
import { expandEveryOrder, expectFits, isCut, linesOf, main, shown, sweepBox } from "./lists";
import { holdShellEvents, installShellEventHold, releaseShellEvents } from "./shellEvents";

type Size = { width: number; height: number };

// Both ends of each shell — 320 px is the narrowest phone there is (Codex #266:
// the round's fixes wrap where they used to clip, and wrapping is decided by the
// narrow end) — and the four tablet widths #258's done-when names
// (768, 820, 1024, 1180). `app` has a mouse: 900 and 1100 are the rail in a
// narrow desktop window — the other pointer across the same fold lines.
const SIZES: Record<string, Size[]> = {
  app: [
    { width: 900, height: 800 },
    { width: 1100, height: 800 },
    { width: 1280, height: 720 },
  ],
  phone: [
    { width: 320, height: 568 },
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
// The values a row can hold that are wider than the ordinary ones the fold lines
// were measured with (Codex #266, findings 1 and 2): an order number of thirty-two
// digits with nowhere to break — wider than a 320 px phone's card, so it has to
// break — a USPS tracking number with its routing prefix, thirty digits, for the
// same reason — and a total in three currencies with its converted line. Digits, like the tag, so the widths are the same every run.
const WIDE_ORDER_NUMBER = `8123456789${suffix}12345678901234`;
const WIDE_TRACKING = "420902109400111899223197428490";
const WIDE_TOTAL = ["JPY 2,800", "USD 45.00", "EUR 34.00"];
// Two currencies is the total that leaves a phone's card *some* room for the
// retailer and not enough: three takes the whole line whatever the name is given.
// Its references are the same *count* of characters as the ordinary ones and
// wider on screen — letters, not digits (Codex #266, finding 5): a rule that
// counted let them through.
const TWO_CURRENCY_NUMBER = `LST-WWWWWWWW-${suffix}`;
// Sixteen, not thirteen: at its floor's width the tracking number is two lines;
// at the column header's width, which is all that holds the column without a
// floor, it is three.
const WIDE_GLYPH_TRACKING = "WWWWWWWWWWWWWWWW";
// One value each for the three margins of the measurement that Codex's round 3
// reached with probes of its own (W7, W8, W9 in the PR): twenty narrow digits,
// 182 px of the table's tabular figures and 114 px proportionally — under the
// budget, so a ruler without the table's figures would leave them a plain word,
// 182 px unbroken; a reference wider than any table's box, which a ruler that
// did not clip would hand to the box or the document; and thirteen digits that
// sit either side of the tracking budget in a fallback font and in Inter, so
// the rule has to follow the font that is drawn, the web font arriving after
// the first paint. Letters that no other reference has a run of, so a text
// locator for one of them finds one thing.
const NARROW_TRACKING = "11111111111111111111";
const UNBOUNDED_NUMBER = "M".repeat(100);
const CROSSING_TRACKING = "8888888888888";
const SHIPPED_TITLE = "Shipped by the retailer";
const RECEIVED_TITLE = "Delivered · days in transit";

const seeded: { route: string; id: string }[] = [];
let retailerId = "";
// A retailer whose name is one short word — "HLJ" is one — so its column has
// nothing wide of its own and a folded reference under it is squeezed to the
// reference's floor and no wider. Found by its id, not by the tag: the search
// would not match it, and the point is that nothing else in the column is wide.
let shortRetailerId = "";

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
  shortRetailerId = (await post(api, "/retailers", { name: `HLJ ${suffix.slice(-3)}` })).id;

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
    quantity_on_hand: 12, // two digits: the count a phone's stepper is asked to hold under a large font
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
  // The wide one, older than the three so they keep their places in the list.
  // Its kits carry no tag: the Kits tests count this run's kits by it.
  const wideLine = (name: string, price: number, currency: string, aud: number) => ({
    item_type: "kit",
    quantity: 1,
    unit_price_minor: price,
    currency_code: currency,
    converted_price_minor: aud,
    converted_currency_code: "AUD",
    kit: { name, grade: "HG" },
  });
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(50),
    order_number: WIDE_ORDER_NUMBER,
    tracking_number: WIDE_TRACKING,
    tracking_url: `https://lists-e2e.example/track/${WIDE_TRACKING}`,
    currency_code: "JPY",
    shipped_at: iso(48),
    received: true,
    received_at: iso(39),
    items: [
      wideLine(`Wide ${suffix} A`, 2800, "JPY", 2900),
      wideLine(`Wide ${suffix} B`, 4500, "USD", 6800),
      wideLine(`Wide ${suffix} C`, 3400, "EUR", 5600),
    ],
  });
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(51),
    order_number: TWO_CURRENCY_NUMBER,
    tracking_number: WIDE_GLYPH_TRACKING,
    currency_code: "JPY",
    items: [wideLine(`Wide ${suffix} D`, 2800, "JPY", 2900), wideLine(`Wide ${suffix} E`, 4500, "USD", 6800)],
  });
  await post(api, "/orders", {
    retailer_id: shortRetailerId,
    order_date: day(52),
    order_number: TWO_CURRENCY_NUMBER,
    tracking_number: WIDE_GLYPH_TRACKING,
    currency_code: "JPY",
    shipped_at: iso(50),
    received: true,
    received_at: iso(45),
    items: [kitLine(`Wide ${suffix} F`, "HG", 1100)],
  });
  // The measurement's margins (above), on two more orders from the tagged
  // retailer; their kits carry no tag either.
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(53),
    order_number: UNBOUNDED_NUMBER,
    tracking_number: NARROW_TRACKING,
    currency_code: "JPY",
    items: [kitLine(`Wide ${suffix} G`, "HG", 1200)],
  });
  await post(api, "/orders", {
    retailer_id: retailer.id,
    order_date: day(54),
    order_number: `LST-${suffix}-0008`,
    tracking_number: CROSSING_TRACKING,
    currency_code: "JPY",
    items: [kitLine(`Wide ${suffix} H`, "HG", 1300)],
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

/** A list row in whichever shape the shell gives it: a table row or a card. */
const rowOf = (page: Page, text: string): Locator =>
  shown(main(page).locator("tbody tr, li")).filter({ hasText: text });

async function openList(page: Page, path: string, anchor: string): Promise<void> {
  await page.goto(path);
  // A shown match: on a table shell the retailer's name is first an <option> of
  // the inline filter, which no closed select displays.
  await expect(shown(main(page).getByText(anchor)).first()).toBeVisible();
}

/** What the page itself complains of while a test drives it: uncaught errors
 *  and console errors. The focus hook moves focus from inside a
 *  `ResizeObserver`, and an observation begun during delivery is reported as
 *  "ResizeObserver loop completed with undelivered notifications" — harmless to
 *  a user and a line in every error tracker. */
async function pageComplaints(page: Page): Promise<string[]> {
  const complaints: string[] = [];
  // The observer's complaint is an `error` event on `window` with no exception
  // behind it, which `pageerror` does not carry: say it on the console.
  await page.addInitScript(() => addEventListener("error", (event) => console.error(`window error: ${event.message}`)));
  page.on("pageerror", (error) => complaints.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") complaints.push(message.text());
  });
  return complaints;
}

/** The width the container queries read: the table box's content width. */
const boxWidth = (page: Page): Promise<number> =>
  shown(main(page).locator(".overflow-x-auto").filter({ has: page.locator("table") }))
    .first()
    .evaluate((box) => box.clientWidth);

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

  // A wide reference breaks within its budget and no narrower: its floor is
  // what keeps a column from squeezing it to a sliver of a letter a line. Seen
  // only where nothing else holds the column — the one order from "HLJ": its
  // number folded under that short name, its tracking number alone under the
  // column's header — and only with the table at its minimum (the sweep sees
  // no overflow either way; mutants W4 and W4b in the PR).
  await page.goto(`/orders?retailer=${shortRetailerId}`);
  await expect(shown(main(page).getByText(TWO_CURRENCY_NUMBER)).first()).toBeVisible();
  const boxOf = (width: string) =>
    page.evaluate((w) => {
      (document.querySelector("main .overflow-x-auto") as HTMLElement).style.width = w;
    }, width);
  // Just over the second fold line — 970 px outside, 968 of content, the border
  // being 2 px of the arithmetic — the Tracking column is still a column.
  await boxOf("970px");
  const tracking = shown(main(page).getByText(WIDE_GLYPH_TRACKING)).first();
  expect(await tracking.evaluate((el) => el.closest("td")?.getAttribute("colspan") ?? null), "the tracking number is in its column").toBeNull();
  expect.soft(await linesOf(tracking), "lines a wide-glyph tracking number takes alone in its column at a 970 px box").toBeLessThanOrEqual(2);
  await boxOf("500px");
  expect.soft(
    await linesOf(shown(main(page).getByText(TWO_CURRENCY_NUMBER)).first()),
    "lines a wide-glyph order number takes under a short retailer's name in a 500 px box",
  ).toBeLessThanOrEqual(4);
  await boxOf("");
});

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
    // The references at every size, folded or not: an ordinary one breaks only
    // where it always did (the number at its hyphens, three lines at most; the
    // tracking number never), and a wide one breaks within its budget and no
    // narrower — letters as wide as these take two lines of the budget where
    // the number has room, and a floor that let the column squeeze them to a
    // sliver would give many more (mutants W3 and W4 in the PR).
    for (const [text, kind, lines] of [
      [ORDER_NUMBER, "the order number", 3],
      [TWO_CURRENCY_NUMBER, "the wide-glyph order number", 4],
      [TRACKING, "the tracking number", 1],
      ...(unfolded(box, FOLD.orderDates)
        ? ([
            [WIDE_GLYPH_TRACKING, "the wide-glyph tracking number", 2],
            [NARROW_TRACKING, "the narrow-digit tracking number", 2],
          ] as const)
        : []),
    ] as const) {
      const said = shown(main(page).getByText(text)).first();
      await expect(said, `Orders ${at}: ${kind}`).toBeVisible();
      expect.soft(await linesOf(said), `Orders ${at}: lines ${kind} takes`).toBeLessThanOrEqual(lines);
    }
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
      if (path.startsWith("/orders")) {
        await expandEveryOrder(page);
        // The ordinary references lay out as they always did, at every width —
        // where the table is squeezed (1280, 1361) as where it has room: the
        // tracking number on one line, the order number breaking at its hyphens
        // and nowhere else (three pieces, so three lines at most). A reference
        // wider than its budget may break anywhere; the budget is what these
        // were measured at, and one set under them would break these first.
        for (const [text, kind, lines, wrap] of [
          [TRACKING, "tracking", 1, "normal"],
          [ORDER_NUMBER, "order number", 3, "normal"],
          [WIDE_GLYPH_TRACKING, "wide-glyph tracking", 2, "anywhere"],
          [TWO_CURRENCY_NUMBER, "wide-glyph order number", 4, "anywhere"],
          // W7: over the budget in the table's tabular figures, under it
          // measured proportionally — a ruler without the figures would leave
          // this a plain word, 182 px unbroken, and the table past its box.
          [NARROW_TRACKING, "narrow-digit tracking", 2, "anywhere"],
          [CROSSING_TRACKING, "thirteen-digit tracking", 2, "anywhere"],
        ] as const) {
          const said = shown(main(page).getByText(text)).first();
          await expect(said, `${kind} at ${width} px`).toBeVisible();
          expect.soft(await linesOf(said), `${kind} "${text}" at ${width} px: lines`).toBeLessThanOrEqual(lines);
          // The rule itself: a plain word, or one that may break anywhere.
          expect.soft(await said.evaluate((el) => getComputedStyle(el).overflowWrap), `${kind} "${text}" at ${width} px: overflow-wrap`).toBe(wrap);
        }
        // W8: a reference wider than the table's box is measured in a ruler
        // that clips. The control is live — its sizer is wider than the box —
        // and the box and the document are not (`expectFits`, below).
        const box = await main(page).locator(".overflow-x-auto").first().evaluate((el) => el.clientWidth);
        // Two sizers, the column's and the fold's copy's; either will do.
        const sizer = await main(page).locator(`[data-text="${UNBOUNDED_NUMBER}"]`).first().evaluate((el) => el.getBoundingClientRect().width);
        expect(sizer, `at ${width} px: the unbounded number's sizer is wider than the box (${box} px)`).toBeGreaterThan(box);
      }
      await expectFits(page, `${path} at ${width} px`);
    }
  }
});

test("a reference's rule follows the font that is drawn", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "a phone's cards measure nothing; a table's ruler does");
  // Codex #266, round 3 (W9): the ruler measures in whatever font is drawn,
  // and the web font arrives after the first paint — later still on a slow
  // network — so the rule has to be decided again when it does. Thirteen
  // digits sit either side of the tracking budget: under it in this machine's
  // fallback font, over it in Inter. Held, not blocked: the font's requests
  // wait until the page has painted in the fallback and been read, then go
  // on. Where a machine's fallback has Inter's figures the rule is the same
  // in both fonts and the test says so; it still holds the rule to the font
  // at each moment.
  const held: Route[] = [];
  await page.route((url) => url.pathname.endsWith(".woff2"), (route) => {
    held.push(route);
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  // Not `openList`: WebKit's `load` event waits for the held font requests,
  // and `page.goto` waits for `load` — so wait for the document and then for
  // the page to have drawn the list, as the font's absence does not stop it.
  await page.goto(`/orders?q=${q}`, { waitUntil: "domcontentloaded" });
  await expect(shown(main(page).getByText(NAMES.retailer)).first()).toBeVisible();
  await expect.poll(() => held.length, "the web font was asked for").toBeGreaterThan(0);
  // The faces' own status, not `document.fonts.check()`, which WebKit answers
  // true for a face that is still loading.
  const loaded = () => page.evaluate(() => [...document.fonts].filter((face) => face.family.includes("Inter Variable") && face.status === "loaded").length);
  expect(await loaded(), "the precondition: no face of the web font is in yet").toBe(0);
  const BUDGET_EM = 8.3; // the tracking budget (§13.7) — a literal, not imported
  const said = shown(main(page).getByText(CROSSING_TRACKING)).first();
  const sizer = main(page).locator(`[data-text="${CROSSING_TRACKING}"]`).first();
  const state = async () => {
    const em = await sizer.evaluate((el) => el.getBoundingClientRect().width / parseFloat(getComputedStyle(el).fontSize));
    const wrap = await said.evaluate((el) => getComputedStyle(el).overflowWrap);
    return { em, wrap, rule: em > BUDGET_EM ? "anywhere" : "normal" };
  };
  const before = await state();
  expect(before.wrap, `in the fallback font, ${before.em.toFixed(2)}em: the rule`).toBe(before.rule);
  for (const route of held) await route.continue();
  await expect.poll(loaded, "the web font arrives").toBeGreaterThan(0);
  // The measurement follows the font — unless this machine's fallback has the
  // web font's own metrics (Inter as the system sans), when there is nothing
  // to follow; the test says so rather than failing on where it runs (Codex
  // #266, round 4). The rule is held to the measurement either way.
  const changed = await expect
    .poll(async () => (await state()).em, { timeout: 5_000 })
    .not.toBe(before.em)
    .then(() => true, () => false);
  await expect.poll(async () => (await state()).wrap, `in the web font: the rule`).toBe((await state()).rule);
  const after = await state();
  testInfo.annotations.push({
    type: "fonts",
    description: `fallback ${before.em.toFixed(2)}em → ${before.wrap}; Inter ${after.em.toFixed(2)}em → ${after.wrap}${
      !changed ? " (the fallback has the web font's metrics: nothing to follow)" : before.rule === after.rule ? " (no crossing on this machine's fallback)" : ""
    }`,
  });
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

test("a dialog opened before the turn's news arrives gives the keyboard back too (#275)", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "an iPad mini turning: 744 px one way, 1133 the other");
  test.setTimeout(90_000);
  // The test above opens its dialog on a settled page. This one presses Enter
  // after the viewport has crossed the line and before `change` is delivered
  // (shellEvents.ts says why that gap exists and who falls into it): the rows
  // are swapped in the very commit that mounts the dialog, so the opener is
  // gone before `Modal` can ask who it was. Found under WebKit as a loss "some
  // runs in ten"; with the events held it is every run, in both engines.
  await installShellEventHold(page);
  const portrait = { width: 744, height: 1133 };
  const landscape = { width: 1133, height: 744 };
  const cases: { path: string; anchor: string; opener: (page: Page) => Locator }[] = [
    { path: `/kits?q=${q}`, anchor: NAMES.twin, opener: (p) => main(p).getByRole("button", { name: `Edit ${NAMES.twin}` }).nth(1) },
    { path: `/orders?q=${q}`, anchor: NAMES.retailer, opener: (p) => main(p).getByRole("button", { name: new RegExp(`^Edit ${NAMES.retailer} `) }).nth(1) },
    { path: "/inventory?tab=upgrades", anchor: NAMES.upgrade, opener: (p) => rowOf(p, NAMES.upgrade).getByRole("button", { name: "Apply to kit" }) },
  ];
  for (const { path, anchor, opener } of cases) {
    for (const [from, to] of [
      [portrait, landscape],
      [landscape, portrait],
    ]) {
      const label = `${path}: ${from.width} → ${to.width} px`;
      await page.setViewportSize(from);
      await openList(page, path, anchor);
      await opener(page).focus();
      await holdShellEvents(page);
      await page.setViewportSize(to);
      // The viewport is the new one — `matches` says so — and nobody has been told.
      await page.waitForFunction((phone) => matchMedia("(min-width: 48rem)").matches !== phone, isPhone(to));
      await page.keyboard.press("Enter");
      await expect(page.getByRole("dialog"), label).toBeVisible();
      await releaseShellEvents(page);
      await expect(shown(main(page).locator("table")), label).toHaveCount(isPhone(to) ? 0 : 1);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect.soft(opener(page), label).toBeFocused({ timeout: 2_000 });
    }
  }
});

test("a dialog opened onto <body> does not inherit a control that is back where it was (Codex #276, finding 1)", async ({
  page,
}) => {
  // The other half of #275's rule. A remembered place is an *unanswered loss*
  // only while its control is gone or not drawn: hide the focused pencil and
  // show it again and the keyboard is on <body>, the place is still remembered
  // (nobody left it — it went), and the pencil is back. A dialog then opened
  // without focusing its opener — a pointer in Safari, which focuses no button;
  // `click()` from script here, which focuses none in any engine — must not
  // hand the keyboard to that pencil at close: it did not open the dialog.
  await openList(page, `/kits?q=${q}`, NAMES.twin);
  const pencil = main(page).getByRole("button", { name: `Edit ${NAMES.twin}` }).filter({ visible: true }).first();
  for (const [how, hide, show] of [
    ["hidden", (el: HTMLElement) => void (el.hidden = true), (el: HTMLElement) => void (el.hidden = false)],
    ["display: none", (el: HTMLElement) => void (el.style.display = "none"), (el: HTMLElement) => void (el.style.display = "")],
  ] as const) {
    await pencil.focus();
    // By handle: the locator asks for a *visible* pencil and would wait for one.
    const node = (await pencil.elementHandle())!;
    await node.evaluate(hide);
    await page.waitForTimeout(100);
    await node.evaluate(show);
    await page.waitForTimeout(100);
    await expect(pencil, how).toBeVisible();
    expect(await page.evaluate(() => document.activeElement === document.body), `${how}: the keyboard fell to <body>`).toBe(true);
    await page.getByRole("button", { name: "Add kit", exact: true }).evaluate((add: HTMLElement) => add.click());
    await expect(page.getByRole("dialog", { name: "Add kit" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.waitForTimeout(100);
    await expect.soft(pencil, `${how}: the pencil did not open Add kit`).not.toBeFocused();
    expect.soft(await page.evaluate(() => document.activeElement === document.body), `${how}: nothing to return to`).toBe(true);
  }
});

test("a dialog opened onto <body> still answers for a control that is in the page and not drawn (Codex #276, finding 1)", async ({
  page,
}) => {
  // Why the check above asks *drawn* and not *connected*: a fold's hidden copy
  // is still in the page, and its visible twin is who should answer. The pencil
  // is hidden with nothing yet carrying its key, so nobody can answer and the
  // keyboard falls to <body>; then a control with that key appears (rows that
  // arrive after the fold), and a dialog is opened without focusing its opener.
  // Closing it owes the keyboard to the twin. No page has both a folding twin
  // and a dialog's opener today — Access tokens has the twins and no dialog —
  // so the twin is the test's own.
  await openList(page, `/kits?q=${q}`, NAMES.twin);
  const pencil = main(page).getByRole("button", { name: `Edit ${NAMES.twin}` }).filter({ visible: true }).first();
  await pencil.focus();
  const node = (await pencil.elementHandle())!;
  await node.evaluate((el: HTMLElement) => void (el.style.display = "none"));
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => document.activeElement === document.body), "the keyboard fell to <body>").toBe(true);
  await node.evaluate((el: HTMLElement) => {
    const twin = document.createElement("button");
    twin.type = "button";
    twin.textContent = "the drawn twin";
    twin.setAttribute("data-focus-key", el.getAttribute("data-focus-key")!);
    el.after(twin);
  });
  await page.getByRole("button", { name: "Add kit", exact: true }).evaluate((add: HTMLElement) => add.click());
  await expect(page.getByRole("dialog", { name: "Add kit" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "the drawn twin" })).toBeFocused({ timeout: 2_000 });
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

  // The filters: on a phone one button stands where the selects stood, so each
  // of them hands it the keyboard — Codex #266, finding 3: only Status did, and
  // Series, Retailer and both Sorts left it on <body>. The way back is one
  // control for three, and deliberately the first of them. (Kits last: what
  // follows is on that page.)
  const sheetOpener = page.getByRole("button", { name: /^Filter and sort/ });
  for (const [path, anchor, labels] of [
    [`/orders?q=${q}`, NAMES.retailer, ["Filter by status", "Filter by retailer", "Sort"]],
    [`/kits?q=${q}`, NAMES.twin, ["Filter by status", "Filter by series", "Sort"]],
  ] as const) {
    for (const label of labels) {
      await page.setViewportSize(landscape);
      await openList(page, path, anchor);
      await main(page).getByLabel(label, { exact: true }).focus();
      await page.setViewportSize(portrait);
      await expect.soft(sheetOpener, `${path} "${label}": 1133 → 744 px`).toBeFocused({ timeout: 2_000 });
    }
    // Focused here and not inherited from the step above, so this says what it
    // says whether or not that one held.
    await sheetOpener.focus();
    await page.setViewportSize(landscape);
    await expect.soft(main(page).getByLabel("Filter by status"), `${path} the sheet's opener: 744 → 1133 px`).toBeFocused({ timeout: 2_000 });
  }

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

test("a fold or a swap inside one shell hands the keyboard to where the control went", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "an iPad Air turning: 1180 px one way, 820 the other — the rail both ways");
  test.setTimeout(120_000);
  // No shell change and no render: a container query stops drawing the focused
  // control, the browser drops focus to <body>, and nothing keyed on the shell
  // can notice (Codex #266, finding 4). Two tokens, so "the same token's Revoke"
  // is a claim about the record and not about there being one button.
  const landscape = { width: 1180, height: 820 };
  const portrait = { width: 820, height: 1180 };
  const complaints = await pageComplaints(page);
  const api = await apiContext();
  const tokens: { id: string; name: string }[] = [];
  try {
    for (const name of [`${TAG} first token`, `${TAG} second token`]) {
      const minted = await api.post("/auth/tokens", { data: { name, scopes: ["collection:read"] } });
      expect(minted.ok(), await minted.text()).toBeTruthy();
      tokens.push({ id: ((await minted.json()) as { id: string }).id, name });
    }
    const revoke = (name: string) =>
      shown(page.getByTestId(/^token-(row|card)$/)).filter({ hasText: name }).getByRole("button", { name: "Revoke" });
    for (const [from, to] of [
      [landscape, portrait],
      [portrait, landscape],
    ]) {
      // Each of the two: whichever the list shows second is the one a key shared
      // by every Revoke would miss, and the list's order is not this test's to know.
      for (const { name } of tokens) {
        await page.setViewportSize(from);
        await page.goto("/settings/tokens");
        const shape = () => shown(page.getByTestId("token-table")).count();
        await expect(revoke(name)).toBeVisible();
        const before = await shape();
        await revoke(name).focus();
        await page.setViewportSize(to);
        // The precondition, said out loud: the turn did swap the table and the cards.
        expect(await shape(), `tokens ${from.width} → ${to.width} px: the list changed shape`).toBe(1 - before);
        await expect.soft(revoke(name), `tokens ${from.width} → ${to.width} px: Revoke of "${name.replace(TAG, "…")}"`).toBeFocused({ timeout: 2_000 });
      }
    }

    // Which comes first when a fold stops drawing the focused control is the
    // browser's to choose, and one Chromium was seen to choose both: the observer
    // with `activeElement` still on the hidden control, or the browser's own
    // fix-up — focus to <body>, a `focusout` to nowhere — and then the observer.
    // Three guards in `lib/focusKey.ts` exist for one order or the other, and a
    // rotation exercises whichever it gets. The box is given its width by hand,
    // as the sweep does it. Inside an animation frame the observer is delivered
    // in that same frame, before any task can run: that order is *forced*, and
    // it is the one the "is this carrier drawn?" guard needs (its mutant
    // survived one run in two before this). The other cannot be forced from
    // outside — a task with a forced layout only invites it — and the guard it
    // needs, the forgetting rule's, has been killed in every run by the tracking
    // link below, which has taken that order each time. The first token in the
    // page is the one whose hidden copy comes first.
    for (const order of ["the observer first", "the browser's fix-up first"]) {
      for (const [from, to, width] of [
        [portrait, "token-table", 640],
        [landscape, "token-cards", 400],
      ] as const) {
        await page.setViewportSize(from);
        await page.goto("/settings/tokens");
        const first = shown(page.getByTestId(/^token-(row|card)$/)).first().getByRole("button", { name: "Revoke" });
        const name = (await shown(page.getByTestId(/^token-(row|card)$/)).first().innerText()).split("\n")[0];
        await first.focus();
        await page.evaluate(
          async ([observerFirst, px]) => {
            const container = document.querySelector('[data-testid="token-table"]')?.parentElement as HTMLElement;
            const frame = () => new Promise<void>((done) => requestAnimationFrame(() => done()));
            if (observerFirst) {
              await new Promise<void>((done) =>
                requestAnimationFrame(() => {
                  container.style.width = `${px}px`;
                  done();
                }),
              );
            } else {
              container.style.width = `${px}px`;
              void container.offsetWidth;
              await new Promise((done) => setTimeout(done, 100));
            }
            await frame();
            await frame();
          },
          [order === "the observer first", width] as const,
        );
        await expect(shown(page.getByTestId(to)), `${order}: the box became the ${to}`).toHaveCount(1);
        await expect.soft(revoke(name), `${order}, to the ${to}: Revoke of "${name.replace(TAG, "…")}"`).toBeFocused({ timeout: 2_000 });
      }
    }
  } finally {
    for (const { id } of tokens) await api.delete(`/auth/tokens/${id}`);
    await api.dispose();
  }

  // Orders: the Tracking column folds into the expanded lines below 60rem of its
  // box. With the lines closed the link is nowhere, and the control that opens
  // them stands in for it; with them open it is the link in the lines.
  const link = shown(main(page).getByRole("link", { name: TRACKING }));
  const lines = rowOf(page, ORDER_NUMBER).getByRole("button", { name: /line items for/ });
  await page.setViewportSize(landscape);
  await openList(page, `/orders?q=${q}`, NAMES.retailer);
  await expect(shown(main(page).getByRole("columnheader", { name: "Tracking" }))).toHaveCount(1);
  await link.focus();
  await page.setViewportSize(portrait);
  await expect(shown(main(page).getByRole("columnheader", { name: "Tracking" })), "the column folded away").toHaveCount(0);
  await expect.soft(lines, "tracking, lines closed: 1180 → 820 px").toBeFocused({ timeout: 2_000 });
  // Clicked, not Enter on whatever has focus: where focus is was the question.
  await lines.click();
  await link.focus();
  await page.setViewportSize(landscape);
  await expect.soft(link, "tracking, lines open: 820 → 1180 px").toBeFocused({ timeout: 2_000 });
  expect(await link.evaluate((a) => a.closest("td")?.getAttribute("colspan") ?? null), "…and it is the column's link").toBeNull();
  await page.setViewportSize(portrait);
  await expect.soft(link, "tracking, lines open: 1180 → 820 px").toBeFocused({ timeout: 2_000 });
  expect.soft(complaints, "errors the page reported").toEqual([]);
});

test("no change of representation leaves the keyboard on <body>", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "one project is enough: every size is set here");
  test.setTimeout(600_000);
  // The rule the focus tests above are instances of, asked of every control there
  // is rather than of the ones somebody thought of — Codex #266 found four selects
  // and a button the instances had missed, and this sweep then found the pager,
  // a retailer's link, Export CSV, the tracking link and the whole navigation.
  // Every focusable control on the page is focused in turn and the page changed
  // under it, each of the three ways it can change: the phone's line (an iPad
  // mini turning), a fold inside the rail (an iPad Air turning), and the rail's
  // line with the sidebar. Where the keyboard ends up is the tests' above to
  // say; here it is only never nowhere.
  const TURNS: [string, number, number][] = [
    ["rail → phone", 1133, 744],
    ["phone → rail", 744, 1133],
    ["rail, folding", 1180, 820],
    ["rail, unfolding", 820, 1180],
    ["sidebar → rail", 1300, 1100],
    ["rail → sidebar", 1100, 1300],
  ];
  const api = await apiContext();
  const minted = await api.post("/auth/tokens", { data: { name: `${TAG} swept token`, scopes: ["collection:read"] } });
  expect(minted.ok(), await minted.text()).toBeTruthy();
  const token = (await minted.json()) as { id: string };
  // The page's own controls everywhere; the shell's on the first page only — it
  // is the same shell on all of them.
  const pages: [string, string, string][] = [
    [`/kits?q=${q}`, NAMES.twin, "#root"],
    [`/orders?q=${q}`, NAMES.retailer, "main"],
    [`/retailers?q=${q}`, NAMES.retailer, "main"],
    ["/inventory?tab=consumables", NAMES.consumable, "main"],
    ["/inventory?tab=upgrades", NAMES.upgrade, "main"],
    ["/settings/tokens", `${TAG} swept token`, "main"],
  ];
  const tried = new Set<string>();
  const lost: string[] = [];
  const complaints = await pageComplaints(page);
  try {
    for (const [path, anchor, scope] of pages) {
      for (const [turn, from, to] of TURNS) {
        await page.setViewportSize({ width: from, height: 900 });
        await openList(page, path, anchor);
        if (path.startsWith("/orders")) await main(page).getByRole("button", { name: /^Show line items/ }).first().click();
        const controls = `[...document.querySelectorAll('${scope} a[href], ${scope} button, ${scope} select, ${scope} input')].filter((el) => el.getClientRects().length > 0 && !el.disabled)`;
        const count = (await page.evaluate(`${controls}.length`)) as number;
        for (let index = 0; index < count; index += 1) {
          await page.setViewportSize({ width: from, height: 900 });
          // The list is read again each time: a shell change replaces the nodes.
          const name = (await page.evaluate(`(async () => {
            await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
            const control = ${controls}[${index}];
            if (!control) return null;
            control.focus();
            if (document.activeElement !== control) return null;
            return control.tagName.toLowerCase() + " " + (control.getAttribute("aria-label") ?? control.textContent ?? "").trim().slice(0, 48);
          })()`)) as string | null;
          if (name === null) continue;
          tried.add(name.replace(TAG, "…"));
          await page.setViewportSize({ width: to, height: 900 });
          const onBody = await page.evaluate(async () => {
            await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
            return document.activeElement === document.body;
          });
          if (onBody) lost.push(`${path} ${turn}: ${name}`);
        }
      }
    }
  } finally {
    await api.delete(`/auth/tokens/${token.id}`);
    await api.dispose();
  }
  // A sweep that enumerated nothing passes having looked at nothing: the controls
  // Codex #266 named, and the ones this found, by name.
  for (const expected of [
    "select Filter by series",
    "select Filter by retailer",
    "select Sort",
    "button Export CSV",
    "button Revoke",
    `a ${TRACKING}`,
    "a lists-e2e.example/a-shop-with-a-long-address",
    "a Retailers",
    "a More",
    "button Sign out",
    "button Apply to kit",
  ]) {
    expect.soft([...tried], "the sweep reached it").toContain(expected);
  }
  expect.soft(tried.size, "distinct controls swept").toBeGreaterThan(40);
  expect.soft(complaints, "errors the page reported").toEqual([]);
  expect(lost, "controls that left the keyboard on <body>").toEqual([]);
});

test("a card says who it is whatever stands beside it", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the cards are the phone shell's");
  // Codex #266, finding 1: the retailer's name could shrink and the total could
  // not, and an order in three currencies left the name 0 px — on a card that
  // fitted the screen exactly, so every bounds check passed it. The identifying
  // text is on screen with room to be read; everything the card says is said in
  // full, wrapped if it must be, never clipped to an ellipsis or squeezed out.
  for (const size of sizesFor("phone")) {
    await page.setViewportSize(size);
    const at = `at ${size.width} px`;
    await openList(page, `/orders?q=${q}`, NAMES.retailer);
    const card = rowOf(page, WIDE_ORDER_NUMBER);
    await card.getByRole("button", { name: /^Show line items/ }).click();
    const name = card.getByText(NAMES.retailer, { exact: true });
    await expect.soft(name, `${at}: the retailer`).toBeVisible();
    expect.soft((await name.boundingBox())?.width ?? 0, `${at}: the retailer's room`).toBeGreaterThanOrEqual(128);
    for (const fact of [...WIDE_TOTAL, "$153.00", WIDE_ORDER_NUMBER, WIDE_TRACKING, "3 items"]) {
      const said = card.getByText(fact).first();
      await expect.soft(said, `${at}: "${fact}"`).toBeVisible();
      expect.soft(await isCut(said), `${at}: "${fact}" is cut or outside its card`).toBe(false);
    }
    // A total that fits the card's width is on one line of its own, not folded
    // into a column beside the name: three currencies fit 390 px and not 320.
    const total = card.getByText(WIDE_TOTAL[0]).first();
    const lines = await total.evaluate((element) => Math.round(element.getBoundingClientRect().height / parseFloat(getComputedStyle(element).lineHeight)));
    expect.soft(lines, `${at}: lines the total takes`).toBe(size.width >= 390 ? 1 : 2);
    // Two currencies leave the name some room and not enough — the case a name
    // that may shrink to nothing loses quietly.
    const two = rowOf(page, TWO_CURRENCY_NUMBER).getByText(NAMES.retailer, { exact: true });
    await expect.soft(two, `${at}: the retailer beside two currencies`).toBeVisible();
    expect.soft((await two.boundingBox())?.width ?? 0, `${at}: the retailer's room beside two currencies`).toBeGreaterThanOrEqual(128);
    // And every other list's cards: the name is there, with room.
    for (const [path, anchor] of [
      [`/kits?q=${q}`, NAMES.twin],
      [`/retailers?q=${q}`, NAMES.retailer],
      ["/inventory", NAMES.tool],
      ["/inventory?tab=upgrades", NAMES.upgrade],
    ] as const) {
      await openList(page, path, anchor);
      const title = rowOf(page, anchor).first().getByText(anchor, { exact: true }).first();
      await expect.soft(title, `${path} ${at}: the name`).toBeVisible();
      expect.soft((await title.boundingBox())?.width ?? 0, `${path} ${at}: the name's room`).toBeGreaterThanOrEqual(128);
    }
  }
});

test("a card says who it is under the browser's own font-size preference", async ({ browserName }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the cards are the phone shell's");
  test.skip(browserName !== "chromium", "the preference is Chromium's launch flag");
  // Codex #266, finding 6: the room a card reserves for its name is in rem,
  // which follows the browser's default font size; the card does not. At 32 px
  // an unconditional 8rem was 256 px in a 94 px column, and `justify-end` put
  // the start of the name 57 px off the left of the screen — on a document that
  // was still exactly 320 px wide. And finding 7, the class: a row's controls
  // are in rem too — the stepper's squares, the pencil, the line-items toggle —
  // and at 32 px on a 320 px phone the stepper was past its card, at 40 px the
  // pencil and the toggle left the name 38 px. A browser of its own, because
  // the preference is a launch setting; the same session, so the same owner.
  // What must hold: every card's name starts and ends inside its card and
  // inside the screen with the room the default size gives it, the total is
  // still said in full, no list is wider than the screen, every control is
  // inside its list, and every target is still a finger. The shell around the
  // lists was not this test's until #260: the page head's action and the tab
  // bar were past 320 px (#269, pages.spec.ts holds them now), and so were a
  // card's *facts* — the status chip, the grade, the scale, "Would order
  // again: Maybe" — which are spans, not controls, on a line that could not
  // wrap (#270): so every list's document is asked for its width here too, and
  // every card for anything drawn past its edge.
  /** The stepper inside its card, its two targets no smaller than a finger
   *  (finding 7): the squares follow the font down to 44 px and no further —
   *  at 320 px under these fonts their 88 and 110 px are wider than the row,
   *  and what the row cannot hold gives way to the floor, not past the card.
   *  The count is not a target; it is read in full. */
  const stepperFits = async (card: Locator, label: string) => {
    for (const name of ["Remove one", "Add one"]) {
      const target = card.getByRole("button", { name: new RegExp(`^${name} `) });
      const box = await target.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const card = (element.closest("li") as HTMLElement).getBoundingClientRect();
        return { width: rect.width, height: rect.height, left: rect.left, right: rect.right, cardLeft: card.left, cardRight: card.right };
      });
      expect.soft(box.width, `${label}: "${name}" is a finger wide`).toBeGreaterThanOrEqual(44);
      expect.soft(box.height, `${label}: "${name}" is a finger tall`).toBeGreaterThanOrEqual(44);
      expect.soft(box.left, `${label}: "${name}" starts in its card`).toBeGreaterThanOrEqual(box.cardLeft - 0.5);
      expect.soft(box.right, `${label}: "${name}" ends in its card`).toBeLessThanOrEqual(box.cardRight + 0.5);
    }
    const count = card.getByTestId("stock-count");
    await expect.soft(count, `${label}: the count`).toBeVisible();
    expect.soft(await isCut(count), `${label}: the count is cut`).toBe(false);
    const edges = await count.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const card = (element.closest("li") as HTMLElement).getBoundingClientRect();
      return { left: rect.left, right: rect.right, cardLeft: card.left, cardRight: card.right };
    });
    expect.soft(edges.left, `${label}: the count starts in its card`).toBeGreaterThanOrEqual(edges.cardLeft - 0.5);
    expect.soft(edges.right, `${label}: the count ends in its card`).toBeLessThanOrEqual(edges.cardRight + 0.5);
  };
  /** Which of the stepper's two arrangements is drawn (#271): one line, or
   *  the count above the two squares where one line cannot hold them. */
  const arrangement = (card: Locator) =>
    // `evaluateAll`, which does not wait: a stepper that says nothing about its
    // arrangement is a named red here, not thirty seconds of looking for one.
    card.locator("[data-arrangement]").evaluateAll((found) => found[0]?.getAttribute("data-arrangement") ?? "unsaid");
  /** Nothing a card draws is past the card (#270): its facts are spans, which
   *  no check of controls sees. */
  const nothingEscapes = async (card: Locator, label: string) => {
    const escaped = await card.evaluate((li) => {
      const bounds = li.getBoundingClientRect();
      // Drawn: not inside a box that clips everything (a ruler is one — a
      // hidden copy a component measures, zero by zero with its overflow cut).
      const clipped = (element: HTMLElement) => {
        for (let box = element.parentElement; box && box !== li; box = box.parentElement) {
          const style = getComputedStyle(box);
          if (style.overflowX !== "visible" && box.clientWidth === 0) return true;
        }
        return false;
      };
      return [...li.querySelectorAll<HTMLElement>("*")]
        .filter((element) => element.getClientRects().length > 0 && !clipped(element))
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.right > bounds.right + 0.5 || rect.left < bounds.left - 0.5;
        })
        .map((element) => `${element.tagName.toLowerCase()} "${(element.textContent ?? "").trim().slice(0, 24)}" [${Math.round(element.getBoundingClientRect().left)}–${Math.round(element.getBoundingClientRect().right)}] of [${Math.round(bounds.left)}–${Math.round(bounds.right)}]`);
    });
    expect.soft(escaped, `${label}: drawn past the card`).toEqual([]);
    // And nothing says more than its own box holds: a chip whose one word is
    // wider than the chip is inside the card and out of its own ground. What
    // truncates does so by design and clips (`overflow: hidden`), so it is
    // the boxes that do not clip that are asked.
    const spilled = await card.evaluate((li) =>
      [...li.querySelectorAll<HTMLElement>("*")]
        .filter((element) => element.getClientRects().length > 0 && getComputedStyle(element).display !== "inline")
        .filter((element) => getComputedStyle(element).overflowX === "visible" && element.scrollWidth > element.clientWidth + 1)
        .filter((element) => ![...element.querySelectorAll<HTMLElement>("*")].some((inner) => getComputedStyle(inner).overflowX !== "visible" && inner.clientWidth === 0))
        .map((element) => `${element.tagName.toLowerCase()} "${(element.textContent ?? "").trim().slice(0, 24)}" ${element.scrollWidth} in ${element.clientWidth}`),
    );
    expect.soft(spilled, `${label}: said past its own box`).toEqual([]);
  };
  const wideCountName = `${TAG} Wide count`;
  const widestCountName = `${TAG} Widest count`;
  const wideFactsName = `${TAG} Wide facts`;
  // Two points on the axis: twice the default, and two and a half times it —
  // where the stepper's squares are at their floor and only the count decides.
  for (const font of [32, 40]) {
    // A four-digit count: at 32 px on a 320 px phone it and two fingers are the
    // row, to the pixel; at 40 px they are past it, and until #271 that was the
    // bound ("four digits fit at 32 px, two at 40"). Now the count goes above
    // the squares there — so it is on the page at both sizes, with the most the
    // column can store beside it, and an ordinary kit with the widest facts
    // there are (#270: Pre-ordered, MGEX, 1/100, a series).
    const api = await apiContext();
    const seeded: string[] = [];
    for (const [route, data] of [
      ["/tools", { name: wideCountName, category: "nippers", quantity_on_hand: 1234 }],
      ["/tools", { name: widestCountName, category: "nippers", quantity_on_hand: 2147483646 }],
      ["/kits", { name: wideFactsName, grade: "MGEX", scale: "1/100", status: "pre_ordered", series: SERIES }],
    ] as const) {
      const made = await api.post(route, { data });
      expect(made.ok(), await made.text()).toBeTruthy();
      seeded.push(`${route}/${((await made.json()) as { id: string }).id}`);
    }
    const browser = await chromium.launch({ args: [`--blink-settings=defaultFontSize=${font}`] });
    try {
      const context = await browser.newContext({ storageState: STORAGE_STATE, hasTouch: true, isMobile: true, baseURL: APP });
      const page = await context.newPage();
      for (const size of sizesFor("phone")) {
        await page.setViewportSize(size);
        const at = `at ${size.width} px, ${font} px font`;
        await openList(page, `/orders?q=${q}`, NAMES.retailer);
        // The precondition, said out loud: the preference is in force.
        expect(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)), "the root font size").toBe(font);
        for (const number of [WIDE_ORDER_NUMBER, TWO_CURRENCY_NUMBER, ORDER_NUMBER]) {
          const card = rowOf(page, number);
          const name = card.getByText(NAMES.retailer, { exact: true });
          await expect.soft(name, `${at}: the retailer of ${number}`).toBeVisible();
          const edges = await name.evaluate((element) => {
            const card = (element.closest("li") as HTMLElement).getBoundingClientRect();
            const rect = element.getBoundingClientRect();
            return { left: rect.left, right: rect.right, cardLeft: card.left, cardRight: card.right, width: rect.width };
          });
          expect.soft(edges.left, `${at}: the retailer of ${number} starts on screen and in its card`).toBeGreaterThanOrEqual(Math.max(0, edges.cardLeft) - 0.5);
          expect.soft(edges.right, `${at}: the retailer of ${number} ends in its card`).toBeLessThanOrEqual(edges.cardRight + 0.5);
          // With its room — the 8rem the default size gives it — because the
          // controls beside it give way first.
          expect.soft(edges.width, `${at}: the retailer of ${number} has room`).toBeGreaterThanOrEqual(128);
        }
        const total = rowOf(page, WIDE_ORDER_NUMBER).getByText(WIDE_TOTAL[2]).first();
        await expect.soft(total, `${at}: the total's last currency`).toBeVisible();
        expect.soft(await isCut(total), `${at}: the total is cut or outside its card`).toBe(false);
        /** The list itself is inside the screen, its controls inside it, and
         *  each of its targets still a finger. */
        const listFits = async (label: string) => {
          const report = await page.evaluate(() => {
            const list = document.querySelector("main ul") as HTMLElement;
            const bounds = list.getBoundingClientRect();
            const drawn = [...list.querySelectorAll<HTMLElement>("button, a[href]")].filter((control) => control.getClientRects().length > 0);
            const say = (control: HTMLElement) => control.getAttribute("aria-label") ?? control.textContent?.trim() ?? "";
            const escaped = drawn
              .filter((control) => {
                const rect = control.getBoundingClientRect();
                return rect.left < bounds.left - 0.5 || rect.right > bounds.right + 0.5;
              })
              .map((control) => {
                const rect = control.getBoundingClientRect();
                return `${say(control)} [${Math.round(rect.left)}–${Math.round(rect.right)}] outside [${Math.round(bounds.left)}–${Math.round(bounds.right)}]`;
              });
            // A row's targets — the pencil, the stepper — give way to a row
            // narrower than they are, down to a finger and no further.
            const small = drawn
              .filter((control) => /^(Edit|Add one|Remove one) /.test(say(control)))
              .filter((control) => control.getBoundingClientRect().width < 44 || control.getBoundingClientRect().height < 44)
              .map((control) => `${say(control)} ${Math.round(control.getBoundingClientRect().width)}×${Math.round(control.getBoundingClientRect().height)}`);
            return { left: bounds.left, right: bounds.right, screen: innerWidth, document: document.documentElement.scrollWidth, escaped, small };
          });
          expect.soft(report.left, `${label}: the list starts on screen`).toBeGreaterThanOrEqual(0);
          expect.soft(report.right, `${label}: the list ends on screen`).toBeLessThanOrEqual(report.screen + 0.5);
          // The screen this test set, not a layout viewport something wide has
          // stretched (#272's lesson), and a document no wider than it (#270).
          expect.soft(report.screen, `${label}: the layout viewport is the screen`).toBe(size.width);
          expect.soft(report.document, `${label}: the document's width`).toBeLessThanOrEqual(size.width);
          expect.soft(report.escaped, `${label}: controls outside their list`).toEqual([]);
          expect.soft(report.small, `${label}: targets under a finger`).toEqual([]);
        };
        await listFits(`/orders ${at}`);
        for (const [path, anchor] of [
          [`/kits?q=${q}`, NAMES.twin],
          [`/retailers?q=${q}`, NAMES.retailer],
          ["/inventory", NAMES.tool],
        ] as const) {
          await openList(page, path, anchor);
          const card = rowOf(page, anchor).first();
          const title = card.getByText(anchor, { exact: true }).first();
          await expect.soft(title, `${path} ${at}: the name`).toBeVisible();
          expect.soft((await title.boundingBox())?.x ?? -1, `${path} ${at}: the name starts on screen`).toBeGreaterThanOrEqual(0);
          expect.soft((await title.boundingBox())?.width ?? 0, `${path} ${at}: the name's room`).toBeGreaterThanOrEqual(128);
          await listFits(`${path} ${at}`);
          await nothingEscapes(card, `${path} ${at}, ${anchor}`);
          if (path.startsWith("/kits")) {
            const wide = rowOf(page, wideFactsName).first();
            for (const fact of ["Pre-ordered", "MGEX", "1/100"]) {
              await expect.soft(wide.getByText(fact, { exact: true }).first(), `${path} ${at}: ${fact}`).toBeVisible();
            }
            await nothingEscapes(wide, `${path} ${at}, the widest facts`);
          }
          if (path.startsWith("/retailers")) {
            await expect.soft(card.getByText("Would order again: Maybe"), `${path} ${at}: the widest chip`).toBeVisible();
          }
          if (path === "/inventory") {
            // The stepper on its own line, not on the facts': beside it they
            // were squeezed to an ellipsis.
            const facts = card.getByText(/nippers/).first();
            await expect.soft(facts, `${path} ${at}: the tool's category`).toBeVisible();
            expect.soft(await isCut(facts), `${path} ${at}: the tool's category is cut`).toBe(false);
            await stepperFits(card, `${path} ${at}, a two-digit count`);
            for (const [name, digits] of [
              [wideCountName, "four"],
              [widestCountName, "ten"],
            ] as const) {
              const wide = rowOf(page, name).first();
              await stepperFits(wide, `${path} ${at}, a ${digits}-digit count`);
              await nothingEscapes(wide, `${path} ${at}, a ${digits}-digit count`);
            }
            // The second arrangement where one line cannot hold the count and
            // two fingers — and only there: ten digits never fit a 320 or a
            // 390 px phone at these fonts and do fit an iPad mini; two digits
            // fit from 390 px.
            expect.soft(await arrangement(rowOf(page, widestCountName).first()), `${path} ${at}: ten digits`).toBe(size.width <= 390 ? "stacked" : "line");
            if (size.width >= 390) expect.soft(await arrangement(card), `${path} ${at}: two digits`).toBe("line");
            // And the stacked targets still work: one more, read back in full.
            if (font === 40 && size.width === 320) {
              const four = rowOf(page, wideCountName).first();
              expect.soft(await arrangement(four), `${path} ${at}: four digits`).toBe("stacked");
              await four.getByRole("button", { name: /^Add one / }).click();
              await expect.soft(four.getByTestId("stock-count"), `${path} ${at}: the count after a tap`).toHaveText("1,235");
              await stepperFits(four, `${path} ${at}, after a tap`);
            }
          }
        }
      }
      // Between the samples (Codex #274, finding 4): an arrangement read once
      // at 320, 390 and 744 px says nothing about one that changes every frame
      // at 480. A stepper that measured the *drawn* count did exactly that —
      // stacked, ten digits wrap narrower than the line needs, fit it, and do
      // not again: 59 changes in 60 frames at 480 px under a 40 px font, Add
      // 60 px past its card, and this test green at every sampled width. So:
      // the widths where the ten digits are near the row's, sixty frames each,
      // the arrangement never changing and Add never past the card.
      for (const width of font === 32 ? [420, 440, 460, 480] : [460, 480, 500, 540]) {
        await page.setViewportSize({ width, height: 844 });
        await openList(page, "/inventory", NAMES.tool);
        await page.evaluate(() => document.fonts.ready);
        const stepper = rowOf(page, widestCountName).first().locator("[data-arrangement]");
        await expect(stepper).toBeVisible();
        const frames = await stepper.evaluate(async (box) => {
          const card = (box.closest("li") as HTMLElement).getBoundingClientRect();
          const add = box.querySelectorAll("button")[1];
          let last = box.getAttribute("data-arrangement");
          let changes = 0;
          let past = 0;
          for (let frame = 0; frame < 60; frame++) {
            await new Promise(requestAnimationFrame);
            const now = box.getAttribute("data-arrangement");
            if (now !== last) changes++;
            last = now;
            past = Math.max(past, add.getBoundingClientRect().right - card.right);
          }
          return { changes, past: Math.round(past * 10) / 10 };
        });
        expect.soft(frames.changes, `/inventory at ${width} px, ${font} px font: the arrangement changed over 60 frames`).toBe(0);
        expect.soft(frames.past, `/inventory at ${width} px, ${font} px font: "Add one" past its card, at worst`).toBeLessThanOrEqual(0.5);
      }
      await context.close();
    } finally {
      await browser.close();
      for (const path of seeded) await api.delete(path);
      await api.dispose();
    }
  }
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
    // The pager is the table's foot in one shell and the card list's in the
    // other — two sets of nodes — and the phone's window is the shorter. A page
    // both offer keeps the keyboard; one only the long window offers hands it
    // to the current page, which every window has.
    const pager = page.getByRole("navigation", { name: "Pages" });
    const pageButton = (n: number) => pager.getByRole("button", { name: `Page ${n}`, exact: true });
    for (const [focused, expected] of [
      [6, 6],
      [2, 5],
    ]) {
      await page.setViewportSize({ width: 1133, height: 744 });
      await openList(page, `/kits?q=${encodeURIComponent(pagerTag)}&page=5`, pagerTag);
      await pageButton(focused).focus();
      await page.setViewportSize({ width: 744, height: 1133 });
      await expect(pageButton(2), "the phone's window at page 5 has no page 2").toHaveCount(0);
      await expect.soft(pageButton(expected), `page ${focused} focused, 1133 → 744 px`).toBeFocused({ timeout: 2_000 });
    }
    // And under the browser's own font-size preference (#260): a page is a
    // finger *in rem*, so at 40 px five of them are 550 px — the pages wrap
    // onto lines of their own rather than widen a 320 px screen. Whether a list
    // has a pager is a state no other font-size test puts on the page.
    if (testInfo.project.use.browserName === undefined || testInfo.project.use.browserName === "chromium") {
      for (const font of [32, 40]) {
        const browser = await chromium.launch({ args: [`--blink-settings=defaultFontSize=${font}`] });
        try {
          const context = await browser.newContext({ storageState: STORAGE_STATE, hasTouch: true, isMobile: true, baseURL: APP });
          const large = await context.newPage();
          for (const width of [320, 390]) {
            await large.setViewportSize({ width, height: 844 });
            await openList(large, `/kits?q=${encodeURIComponent(pagerTag)}&page=5`, pagerTag);
            const label = `page 5 of 9 at ${width} px, ${font} px font`;
            expect(await large.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)), "the root font size").toBe(font);
            const report = await large.getByRole("navigation", { name: "Pages" }).evaluate((nav) => ({
              pages: [...nav.querySelectorAll("button")].map((button) => Math.round(button.getBoundingClientRect().right)),
              small: [...nav.querySelectorAll("button")].filter((button) => Math.min(button.getBoundingClientRect().width, button.getBoundingClientRect().height) < 44).length,
              document: document.documentElement.scrollWidth,
              screen: innerWidth,
            }));
            expect.soft(report.pages.length, `${label}: pages offered`).toBeGreaterThanOrEqual(3);
            expect.soft(Math.max(...report.pages), `${label}: the last page ends on screen`).toBeLessThanOrEqual(width);
            expect.soft(report.small, `${label}: pages under a finger`).toBe(0);
            expect.soft(report.screen, `${label}: the layout viewport is the screen`).toBe(width);
            expect.soft(report.document, `${label}: the document's width`).toBeLessThanOrEqual(width);
          }
          await context.close();
        } finally {
          await browser.close();
        }
      }
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

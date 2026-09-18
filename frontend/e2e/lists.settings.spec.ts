/**
 * The list pages under every date style the Settings page offers (design §13.7,
 * #258; Codex #266, finding 2).
 *
 * lists.spec.ts measures the tables with the instance's default formatting, and
 * the fold lines were set from those rows — "27/08/2026 · 9 d". The formatting
 * locale and the date style are instance settings (AGENTS.md rule 11), and
 * `full` writes that cell "Thursday, 27 August 2026 · 9 d": held to one line,
 * the Orders table was 121 px wider than its box at 1280 px and its edit control
 * off the edge at every width. A date in words wraps now, and this holds it:
 * the same every-width sweep, the same rows and the wide ones, under each style
 * in the owner's locale and the longest one in three others.
 *
 * It flips the settings singleton, so it runs in the `settings` project — after
 * every other project, never beside one (playwright.config.ts) — and puts back
 * what it found.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext } from "./api";
import { expandEveryOrder, expectFits, isCut, main, shown, sweepBox } from "./lists";

const suffix = String(Date.now()).slice(-8);
const TAG = `E2E Styles ${suffix}`;
const q = encodeURIComponent(TAG);
const RETAILER = `${TAG} Hobby Works`;
const SHIPPED_AT = "2026-08-18T02:00:00Z";
const RECEIVED_AT = "2026-08-27T02:00:00Z";
const SHIPPED_TITLE = "Shipped by the retailer";

type Settings = { formatting_locale: string; date_style: string; hour_cycle: string; time_zone: string };
let original: Settings;
let tokenId = "";
const seeded: { route: string; id: string }[] = [];

async function post(api: APIRequestContext, route: string, data: object): Promise<string> {
  const resp = await api.post(route, { data });
  expect(resp.ok(), `${route}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const { id } = (await resp.json()) as { id: string };
  seeded.unshift({ route, id });
  return id;
}

test.beforeAll(async () => {
  const api = await apiContext();
  original = (await (await api.get("/settings")).json()) as Settings;
  const retailer = await post(api, "/retailers", { name: RETAILER });
  const line = (name: string, price: number, currency: string, aud: number) => ({
    item_type: "kit",
    quantity: 1,
    unit_price_minor: price,
    currency_code: currency,
    converted_price_minor: aud,
    converted_currency_code: "AUD",
    kit: { name, grade: "HG" },
  });
  // The ordinary widest row — shipped and received, a number, tracking, a
  // converted total — and the wide one: nowhere to break in either reference,
  // three currencies.
  await post(api, "/orders", {
    retailer_id: retailer,
    order_date: "2026-07-18",
    order_number: `LST-${suffix}-0001`,
    tracking_number: "EJ482113905JP",
    currency_code: "JPY",
    shipped_at: SHIPPED_AT,
    received: true,
    received_at: RECEIVED_AT,
    items: [line(`${TAG} Kit`, 2800, "JPY", 2900)],
  });
  await post(api, "/orders", {
    retailer_id: retailer,
    order_date: "2026-07-11",
    order_number: `8123456789${suffix}1`,
    tracking_number: "9400111899223197428490",
    currency_code: "JPY",
    shipped_at: "2026-07-13T02:00:00Z",
    received: true,
    received_at: "2026-07-22T02:00:00Z",
    items: [line(`Wide ${suffix} A`, 2800, "JPY", 2900), line(`Wide ${suffix} B`, 4500, "USD", 6800), line(`Wide ${suffix} C`, 3400, "EUR", 5600)],
  });
  // In transit: the folded line under the chip is "<date> · in transit · n d".
  await post(api, "/orders", {
    retailer_id: retailer,
    order_date: "2026-07-19",
    currency_code: "JPY",
    shipped_at: new Date(Date.now() - 4 * 86_400_000).toISOString(),
    items: [line(`${TAG} Shipped Kit`, 3300, "JPY", 3400)],
  });
  // Kits has two date columns of its own.
  const built = await post(api, "/kits", {
    name: `${TAG} Built`,
    grade: "MG",
    status: "complete",
    build_started_at: "2026-08-01T02:00:00Z",
    build_completed_at: "2026-08-13T02:00:00Z",
  });
  expect((await api.patch(`/kits/${built}`, { data: { rating: 4 } })).ok()).toBeTruthy();
  // And Access tokens three, as date-times on its cards.
  const minted = await api.post("/auth/tokens", {
    data: { name: `${TAG} token`, scopes: ["collection:read", "collection:write"], expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString() },
  });
  expect(minted.ok(), await minted.text()).toBeTruthy();
  tokenId = ((await minted.json()) as { id: string }).id;
  // A revoked one as well — "revoked <date>" under the name was the one date on
  // that table held to a line, and this spec found it. Revoked here, not left to
  // whatever the specs before this one happened to leave behind.
  const spent = await api.post("/auth/tokens", { data: { name: `${TAG} revoked token`, scopes: ["collection:read"] } });
  expect(spent.ok(), await spent.text()).toBeTruthy();
  expect((await api.delete(`/auth/tokens/${((await spent.json()) as { id: string }).id}`)).status()).toBe(204);
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  await api.patch("/settings", {
    data: { formatting_locale: original.formatting_locale, date_style: original.date_style, hour_cycle: original.hour_cycle },
  });
  for (const { route, id } of seeded) await api.delete(`${route}/${id}`);
  if (tokenId) await api.delete(`/auth/tokens/${tokenId}`);
  await api.dispose();
});

// Every style where the owner is, and the longest one where the words are
// longer, the script has no spaces, or the digits are not these.
const FORMATS: [string, string][] = [
  ["en-AU", "short"],
  ["en-AU", "medium"],
  ["en-AU", "long"],
  ["en-AU", "full"],
  ["de-DE", "full"],
  ["ja-JP", "full"],
  ["ar-EG", "full"],
];

for (const [locale, style] of FORMATS) {
  test(`no list outgrows its box with dates written ${locale} ${style}`, async ({ page }) => {
    test.setTimeout(120_000);
    const api = await apiContext();
    const patched = await api.patch("/settings", { data: { formatting_locale: locale, date_style: style, hour_cycle: "h12" } });
    expect(patched.ok(), await patched.text()).toBeTruthy();
    await api.dispose();
    // What the page must be showing for any of this to mean something: the ship
    // date as this locale and style write it, formatted here and not by the app
    // — by the *browser's* `Intl`, not Node's: their locale data differ (WebKit
    // puts a space before a Japanese weekday; Codex #266, round 2), and the
    // question is what the app rendered, not what ICU this test runner has.
    await page.goto("/");
    const written = async (iso: string) =>
      page.evaluate(
        ([l, s, tz, at]) => new Intl.DateTimeFormat(l, { dateStyle: s as Intl.DateTimeFormatOptions["dateStyle"], timeZone: tz }).format(new Date(at)),
        [locale, style, original.time_zone, iso] as const,
      );
    const expected = await written(SHIPPED_AT);
    const delivered = await written(RECEIVED_AT);

    // Every width a table's box can have, as lists.spec.ts does it.
    await page.setViewportSize({ width: 1270, height: 900 });
    for (const [path, anchor, from, to] of [
      [`/orders?q=${q}`, RETAILER, 634, 1300],
      [`/kits?q=${q}`, `${TAG} Built`, 634, 1300],
      ["/settings/tokens", `${TAG} token`, 300, 652],
    ] as const) {
      await page.goto(path);
      await expect(shown(page.locator("main").getByText(anchor)).first()).toBeVisible();
      if (path.startsWith("/orders")) {
        await expect(shown(main(page).getByTitle(SHIPPED_TITLE).filter({ hasText: expected })).first(), `the ship date reads "${expected}"`).toBeVisible();
        await expandEveryOrder(page);
      }
      const overflowing = await sweepBox(page, from, to);
      expect(overflowing, `${path}: no table box on the page`).not.toBeNull();
      expect.soft(overflowing?.measured, `${path}: every width measured`).toBe(to - from + 1);
      expect.soft(overflowing?.widths, `${path}: box widths at which the list is wider than its box`).toEqual([]);
    }

    // The real sizes, where the page and not a hand sets the box: a phone's
    // cards, both ends of the rail, and the desktop where nothing folds.
    for (const width of [320, 390, 768, 1180, 1280, 1366]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/orders?q=${q}`);
      await expect(shown(main(page).getByText(RETAILER)).first()).toBeVisible();
      await expandEveryOrder(page);
      await expectFits(page, `/orders at ${width} px`);
      if (width < 768) {
        // A card is the only place a phone says these: the name has room, and the
        // delivery date is said in full however long the style makes it.
        const card = shown(main(page).locator("li")).filter({ hasText: `LST-${suffix}-0001` });
        const name = card.getByText(RETAILER, { exact: true });
        expect.soft((await name.boundingBox())?.width ?? 0, `${width} px: a card's retailer has room`).toBeGreaterThanOrEqual(128);
        const said = card.getByText(delivered).first();
        await expect.soft(said, `${width} px: the delivery date reads "${delivered}"`).toBeVisible();
        expect.soft(await isCut(said), `${width} px: the delivery date is cut or outside its card`).toBe(false);
      }
    }
  });
}

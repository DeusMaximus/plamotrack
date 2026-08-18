/** Issue #51: every form in this application lives in a dialog, and a keyboard
 *  user could not properly enter, operate or leave one.
 *
 *  `Modal` set role="dialog" and aria-modal="true" and handled Escape, which is
 *  the half you can see. The half you cannot: focus stayed on the trigger behind
 *  the dialog, Tab walked straight out into the page underneath, the background
 *  was never inerted, and closing dropped focus at <body>.
 *
 *  Driven through Playwright rather than a unit test because every assertion here
 *  is about real focus and real Tab order, which is the browser's own behaviour
 *  and not something a mock can stand in for. Unlike the drag ordering in #50,
 *  none of it is timing-dependent: a keypress either moves focus or it does not.
 */
import { expect, request, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const API = "http://127.0.0.1:8000";

const suffix = Date.now().toString(36);
const RETAILER = `E2E Keyboard ${suffix}`;
const CONSUMABLE = `E2E Keyboard Cement ${suffix}`;

test.describe.configure({ mode: "serial" });

let retailerId: string;
let orderId: string;
let consumableId: string;

test.beforeAll(async () => {
  const api = await request.newContext({ baseURL: API });
  const retailer = await api.post("/retailers", { data: { name: RETAILER } });
  expect(retailer.status(), await retailer.text()).toBe(201);
  retailerId = ((await retailer.json()) as { id: string }).id;

  // The disclosure test needs an order of its own. An earlier version read
  // whichever order happened to be on the page, which passed against a dev
  // database with twenty of them and failed in CI, where the schema is empty —
  // the one environment that actually matches a new install.
  const order = await api.post("/orders", {
    data: {
      retailer_id: retailerId,
      order_date: "2026-08-01",
      currency_code: "AUD",
      items: [
        {
          item_type: "kit",
          quantity: 1,
          unit_price_minor: 4500,
          currency_code: "AUD",
          kit: { name: `E2E Keyboard Kit ${suffix}`, grade: "HG" },
        },
      ],
    },
  });
  expect(order.status(), await order.text()).toBe(201);
  orderId = ((await order.json()) as { id: string }).id;

  // Something for the catalog picker to find. Searching for whatever happens to
  // be in the database is how the disclosure test first failed in CI, and the
  // picker test needs a *result* to tab onto or it silently exercises nothing.
  const consumable = await api.post("/consumables", {
    data: { name: CONSUMABLE, category: "glue" },
  });
  expect(consumable.status(), await consumable.text()).toBe(201);
  consumableId = ((await consumable.json()) as { id: string }).id;
  await api.dispose();
});

test.afterAll(async () => {
  const api = await request.newContext({ baseURL: API });
  // Order first: a retailer with order history refuses deletion (409), and
  // deleting the order also removes the kit it spawned.
  await api.delete(`/orders/${orderId}`);
  await api.delete(`/retailers/${retailerId}`);
  await api.delete(`/consumables/${consumableId}`);
  await api.dispose();
});

/** What the browser currently has focused, as something readable in a failure. */
function focusDescription(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return "body";
    const label = el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 24) ?? "";
    return `${el.tagName.toLowerCase()}${label ? `[${label}]` : ""}`;
  });
}

const inDialog = (page: Page) =>
  page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'));

test("a dialog takes focus, keeps it, and gives it back", async ({ page }) => {
  await page.goto("/retailers");

  const trigger = page.getByRole("button", { name: "+ Add retailer" });
  await trigger.focus();
  await expect(await focusDescription(page)).toContain("button");

  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // The dialog *itself*, not merely something inside it. `inDialog` is satisfied
  // by the Close button, so asserting only that would pass against initial focus
  // landing on Close — which is the arrangement this deliberately avoids, since
  // it announces "Close" as the first thing a screen-reader user hears about a
  // form they just opened.
  expect(
    await page.evaluate(() => document.activeElement?.getAttribute("role")),
    `focus was on ${await focusDescription(page)}`,
  ).toBe("dialog");

  // Shift+Tab from that starting point wraps to the end rather than reversing
  // out of the dialog — the one direction a container-focused dialog can leak.
  await page.keyboard.press("Shift+Tab");
  expect(await inDialog(page), `Shift+Tab from the container left to ${await focusDescription(page)}`)
    .toBe(true);

  // Tab all the way round. Every stop must still be inside the dialog: before
  // this fix, Tab left after the last control and walked the page underneath.
  const seen: string[] = [];
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press("Tab");
    seen.push(await focusDescription(page));
    expect(await inDialog(page), `Tab #${i + 1} escaped to ${seen[i]}; path: ${seen.join(" → ")}`)
      .toBe(true);
  }

  // And backwards, which wraps the other way.
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Shift+Tab");
    expect(await inDialog(page), `Shift+Tab #${i + 1} escaped to ${await focusDescription(page)}`)
      .toBe(true);
  }

  // The page underneath is inert, so nothing there can be reached or read.
  expect(await page.evaluate(() => document.getElementById("root")?.hasAttribute("inert"))).toBe(
    true,
  );

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // Focus comes back to the control that opened it, not to <body>.
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.getElementById("root")?.hasAttribute("inert"))).toBe(
    false,
  );
});

test("the close button also returns focus to the opener", async ({ page }) => {
  await page.goto("/retailers");
  const trigger = page.getByRole("button", { name: "+ Add retailer" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).click();

  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("order line items expand from the keyboard", async ({ page }) => {
  await page.goto("/orders");

  // Scoped to this spec's own order, not `.first()` — on a populated instance
  // that is whichever row happens to sort first.
  const row = page.getByRole("row").filter({ hasText: RETAILER });
  const disclosure = row.getByRole("button", { name: /line items/ });
  await expect(disclosure).toBeVisible();
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");

  // Enter and Space both, because a <div role="button"> would answer one and not
  // the other — a real <button> is what makes them equivalent.
  await disclosure.focus();
  await page.keyboard.press("Enter");
  await expect(disclosure).toHaveAttribute("aria-expanded", "true");

  await page.keyboard.press("Space");
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
});


test("the order dialog holds focus through dynamic rows and the catalog picker", async ({
  page,
}) => {
  // The retailer dialog is ten static controls: its first and last focusable
  // never change, so it cannot tell a live trap from one that snapshotted the
  // list on open. The order form adds and removes line rows while it is open and
  // contains a picker whose result list unmounts under the focus it just took.
  await page.goto("/orders");
  const trigger = page.getByRole("button", { name: "+ New order" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // Grow the form, so anything that cached the focusable list on open is now
  // wrong about what is inside it.
  await dialog.getByRole("button", { name: "+ Add line" }).click();
  await dialog.getByRole("button", { name: "+ Add line" }).click();

  // A consumable line, whose picker is the control that unmounts under focus.
  // Identified by what it offers rather than by position: a kit line renders a
  // *second* select (Ordered / Pre-ordered) after this one, so `.last()` picks
  // the wrong control and fails with "did not find some options".
  await dialog.locator('select:has(option[value="consumable"])').last().selectOption("consumable");
  const search = dialog.getByPlaceholder(/Search consumables/).last();
  await search.fill(CONSUMABLE);

  // Wait for the results to actually render before tabbing. The search is
  // debounced, so filling and immediately tabbing lands on the unit-price input
  // instead and never reaches the control this test exists for — measured: the
  // recapture mutant survived the whole suite until this wait was added.
  const results = dialog.locator("div.absolute button");
  await expect(results.first()).toBeVisible();

  // Tab off the input. The results follow it in DOM order so focus lands on one,
  // and the list then closes 150ms after the input's blur — pulling the focused
  // node out from under it. Removing a focused node fires no blur and no
  // focusout, so nothing event-driven sees this; focus simply becomes <body>.
  await search.press("Tab");
  expect(await inDialog(page), `focus left immediately, to ${await focusDescription(page)}`).toBe(
    true,
  );
  await page.waitForTimeout(400);
  expect(await inDialog(page), `focus escaped to ${await focusDescription(page)} when the picker closed`)
    .toBe(true);

  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    expect(await inDialog(page), `Tab #${i + 1} escaped to ${await focusDescription(page)}`).toBe(
      true,
    );
  }

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

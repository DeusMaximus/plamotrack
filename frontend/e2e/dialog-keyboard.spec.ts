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
 *  and not something a mock can stand in for. A keypress either moves focus or it
 *  does not, so most of this needs no timing care at all — but two cases do have
 *  a window, and both are pinned to an event rather than a duration: the picker's
 *  own blur timer is waited out by the result list emptying, and the submit
 *  button's disabled window is held open by stalling the request.
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
  // Wait for the list to actually go, rather than for a duration that happens to
  // outlast the picker's 150ms blur timer. Same event, named.
  await expect(results).toHaveCount(0);
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


test("submitting from the keyboard does not drop focus while the request is in flight", async ({
  page,
}) => {
  // Every dialog in this app disables its submit button while submitting, and
  // disabling the focused element drops focus to <body> just as removing it
  // does — no blur, no focusout. Tab to Submit and press Enter is the most
  // ordinary keyboard path there is, and it was the one still escaping.
  //
  // The request is stalled deliberately. Locally it completes in single-digit
  // milliseconds, so the window where the button is disabled and the dialog is
  // still open closes before any assertion can see it, and the test would pass
  // against the defect for want of a chance to observe it.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/retailers", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await held;
    await route.continue();
  });

  await page.goto("/retailers");
  const trigger = page.getByRole("button", { name: "+ Add retailer" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Name").fill(`${RETAILER} submit`);

  // "Add" on a create, "Save" on an edit — this dialog is a create.
  const submit = dialog.getByRole("button", { name: "Add", exact: true });
  await submit.focus();
  await page.keyboard.press("Enter");

  // Mid-flight: the button has gone disabled under the focus it was holding.
  await expect(submit).toBeDisabled();
  expect(await inDialog(page), `focus escaped to ${await focusDescription(page)} while submitting`)
    .toBe(true);

  release();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  // Clean up the retailer this test created.
  const api = await request.newContext({ baseURL: API });
  const rows = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const created = rows.find((row) => row.name === `${RETAILER} submit`);
  if (created) await api.delete(`/retailers/${created.id}`);
  await api.dispose();
});


test("a dialog mutating around you does not take your focus", async ({ page }) => {
  // The other half of the recapture, and the half nothing asked about: the
  // observer fires on *every* matching mutation and is stopped from acting only
  // by `activeElement === document.body`. Delete that guard and focus jumps to
  // the dialog whenever anything in it changes — a form you cannot type in.
  // Every other assertion in this file is `inDialog`, which focus already inside
  // the dialog satisfies, so an unguarded observer passed the whole suite.
  //
  // The assertions here are therefore on a *named control*, not on containment.
  //
  // The mutation used is the picker's result list rendering, because it is caused
  // by the very input that holds focus and moves nothing by design. "+ Add line"
  // is not usable for this: the form deliberately focuses the new row's first
  // control, so focus moves for a good reason and the test would be measuring
  // the app's own behaviour rather than the observer's.
  await page.goto("/orders");
  const trigger = page.getByRole("button", { name: "+ New order" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator('select:has(option[value="consumable"])').last().selectOption("consumable");

  const search = dialog.getByPlaceholder(/Search consumables/).last();
  const results = dialog.locator("div.absolute button");
  await search.click();
  await expect(search).toBeFocused();

  // Type it a character at a time: each debounced query re-renders the list, so
  // the childList mutations arrive repeatedly under a cursor that must not move.
  for (const char of CONSUMABLE.slice(0, 18)) {
    await page.keyboard.type(char);
  }
  await expect(results.first()).toBeVisible();
  await expect(search).toBeFocused();
  await expect(search).toHaveValue(CONSUMABLE.slice(0, 18));

  // And typing still lands in the field after the list has rendered.
  await page.keyboard.type("!");
  await expect(search).toHaveValue(`${CONSUMABLE.slice(0, 18)}!`);
  await expect(search).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

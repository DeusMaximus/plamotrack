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
 *  does not, so most of this needs no timing care at all — but one case does have
 *  a window, pinned to an event rather than a duration: the submit button's
 *  disabled window is held open by stalling the request. (The picker's blur
 *  timer, which this file once waited out, is gone — #104 closes the list on
 *  focus genuinely leaving it, which is not a race.)
 */
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const RETAILER = `E2E Keyboard ${suffix}`;
const CONSUMABLE = `E2E Keyboard Cement ${suffix}`;

test.describe.configure({ mode: "serial" });

let retailerId: string;
let orderId: string;
let consumableId: string;

test.beforeAll(async () => {
  const api = await apiContext();
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
  const api = await apiContext();
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

  const trigger = page.getByRole("button", { name: "Add retailer" });
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
  const trigger = page.getByRole("button", { name: "Add retailer" });
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
  // that is whichever row happens to sort first. A `<tr>` from 768 px and a
  // card's `<li>` below it (#258); the control's name is the same in both.
  const row = page.locator("tr, li").filter({ hasText: RETAILER });
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
  const trigger = page.getByRole("button", { name: "New order" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // Grow the form, so anything that cached the focusable list on open is now
  // wrong about what is inside it.
  await dialog.getByRole("button", { name: "Add line" }).click();
  await dialog.getByRole("button", { name: "Add line" }).click();

  // A consumable line, whose picker is the control that unmounts under focus.
  // Identified by what it offers rather than by position — resilient to a line
  // growing other selects, which it has had before (the per-line status picker,
  // removed by #120).
  await dialog.locator('select:has(option[value="consumable"])').last().selectOption("consumable");
  const search = dialog.getByPlaceholder(/Search consumables/).last();
  await search.fill(CONSUMABLE);

  // Wait for the results to actually render before tabbing. The search is
  // debounced, so filling and immediately tabbing lands on the unit-price input
  // instead and never reaches the control this test exists for — measured: the
  // recapture mutant survived the whole suite until this wait was added.
  const results = dialog.locator("div.absolute button");
  await expect(results.first()).toHaveText(/on hand/); // a found row, not the offer to create (below)

  // Tab off the input. The results follow it in DOM order, so focus lands on
  // the first one — and since #104 the list stays open under it: the picker
  // closes only when focus genuinely leaves it, not on a timer racing the
  // keyboard. (The pre-#104 behaviour this block used to pin — the blur timer
  // unmounting the focused node, which fires no blur and no focusout — is why
  // the dialog's recapture below still exists and is still asserted.)
  await search.press("Tab");
  await expect(results.first()).toBeFocused();
  await expect(results.first()).toBeVisible(); // the list held
  expect(await inDialog(page), `focus left immediately, to ${await focusDescription(page)}`).toBe(
    true,
  );

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


test("a keyboard user can select a catalog search result (#104)", async ({ page }) => {
  // The case the focus test above deliberately stops short of: Tab onto a
  // result, press Enter, and the selection must land — driven through to the
  // stored order's catalog_ref_id, not just the form state. Rule 3 means the
  // alternative to this working is not "type the name", it is "create a
  // duplicate", which is exactly what select-or-create exists to prevent.
  await page.goto("/orders");
  await page.getByRole("button", { name: "New order" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await dialog.getByRole("combobox", { name: /^Retailer/ }).selectOption(retailerId);
  await dialog.locator('select:has(option[value="consumable"])').selectOption("consumable");
  await dialog.getByLabel("Unit price").fill("6.50");

  const search = dialog.getByPlaceholder(/Search consumables/);
  await search.fill(CONSUMABLE);
  const results = dialog.locator("div.absolute button");
  // Debounced — wait for real rows, and say *rows*: the offer to create is a
  // button in this list too, drawn while the search is still out. Waiting for
  // "a button" let a slow answer put Tab on the offer, and the test then failed
  // on whichever line noticed first — once in each engine, in full runs only,
  // never in forty runs of this file alone (#275's PR).
  await expect(results.first()).toHaveText(/on hand/);

  await search.press("Tab");
  await expect(results.first()).toBeFocused();
  await page.keyboard.press("Enter");

  // The picker collapsed to the chosen-item chip; no free text survived.
  await expect(dialog.getByText(CONSUMABLE, { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Change" })).toBeVisible();

  await dialog.getByRole("button", { name: "Record order" }).click();
  await expect(dialog).toBeHidden();

  // Driven through: the stored line carries the id of the item picked by key.
  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as {
    id: string;
    items: { item_type: string; catalog_ref_id: string | null }[];
  }[];
  const stored = orders.find((order) =>
    order.items.some((item) => item.catalog_ref_id === consumableId),
  );
  expect(stored, "the keyboard-picked line reached the API with the item's id").toBeTruthy();
  expect(stored!.items[0].item_type).toBe("consumable");
  await api.delete(`/orders/${stored!.id}`); // self-cleaning
  await api.dispose();
});


test("a date input keeps its own Tab through its parts (#267's trap)", async ({ page, browserName }) => {
  // The trap hand-drives a Tab whose next stop is something Safari would skip
  // (#267) — and the control after the order form's "Received on" is the *Add
  // line* button. Chromium's date input is three parts — day, month, year — and
  // Tab walks them before it leaves the field; a trap that drove that Tab by
  // hand would jump from the day straight to the button. So: from that date,
  // at least two Tabs stay on the input, and the Tab that leaves it lands on
  // the button, not past it. (The kit form's dates are followed by fields,
  // where the engine makes the move either way — a mutant that removed the
  // exemption survived a version of this test written there.) WebKit's date
  // input has no parts to walk, and is skipped by name.
  // Codex #272, finding 2: and the stop after the date is the *next control*,
  // in every engine — WebKit left its date for the first line's type select and
  // passed *Add line* over, inside the dialog the whole time, which containment
  // cannot see. So the stop is asserted by name, under WebKit too; only the
  // count of parts is Chromium's.
  await page.goto("/orders");
  await page.locator("tr, li").filter({ hasText: RETAILER }).getByRole("button", { name: /^Edit / }).click();
  const dialog = page.getByRole("dialog", { name: "Edit order" });
  await expect(dialog.getByRole("button", { name: "Add line" })).toBeVisible();
  const received = dialog.getByLabel("Received on");
  // `focus()`, not a click: a click lands on whichever part is under the
  // pointer, and the input's centre is the month.
  await received.focus();
  await expect(received).toBeFocused();
  let stayed = 0;
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    if (await received.evaluate((element) => document.activeElement === element)) stayed += 1;
    else break;
  }
  if (browserName === "chromium") expect(stayed, "Tabs that stayed on the date input").toBeGreaterThanOrEqual(2);
  await expect(dialog.getByRole("button", { name: "Add line" }), "then the button after it").toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // The review's own path: a new order already in hand. The pre-order box is
  // disabled then, so what follows the arrival date is *Add line*.
  await page.getByRole("button", { name: "New order" }).click();
  const fresh = page.getByRole("dialog", { name: "New order" });
  await expect(fresh.getByRole("button", { name: "Add line" })).toBeVisible();
  await fresh.getByLabel(/^Already in hand/).check();
  const arrived = fresh.locator('input[type="date"]').nth(1);
  await arrived.focus();
  await expect(arrived).toBeFocused();
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    if (!(await arrived.evaluate((element) => document.activeElement === element))) break;
  }
  await expect(fresh.getByRole("button", { name: "Add line" }), "the stop after the arrival date").toBeFocused();
  await page.keyboard.press("Escape");
});

test("a burst of Tabs through a date input settles (Codex #272, finding 3)", async ({ page, browserName }) => {
  // The landing check after a date input (finding 2's fix) removed itself on a
  // zero-delay timer, and a timer does not confine it to one key's task: under
  // native keypresses with no delay between them, several checks were pending
  // at once, each holding a different next stop, and they sent focus back and
  // forth between two fields — over 150 moves in 12 of 12 trials, and one run
  // that never came back. The invariant: a pending correction is consumed by
  // its own departure and governs no later focus change. Forty keypresses can
  // move focus forty times and be corrected a handful more; not hundreds.
  test.skip(browserName !== "chromium", "the burst is Chromium's: WebKit did not reproduce it");
  await page.goto("/orders");
  await page.getByRole("button", { name: "New order" }).click();
  const dialog = page.getByRole("dialog", { name: "New order" });
  await expect(dialog.getByRole("button", { name: "Add line" })).toBeVisible();
  await page.evaluate(() => {
    const counter = window as unknown as { __focusMoves: number };
    counter.__focusMoves = 0;
    document.addEventListener("focusin", () => {
      counter.__focusMoves += 1;
    });
  });
  await dialog.getByLabel("Order date").focus();
  for (let cycle = 0; cycle < 4; cycle++) {
    for (let i = 0; i < 5; i++) await page.keyboard.press("Tab");
    for (let i = 0; i < 5; i++) await page.keyboard.press("Shift+Tab");
  }
  const moves = await page.evaluate(() => (window as unknown as { __focusMoves: number }).__focusMoves);
  expect(moves, "focus moves for forty keypresses").toBeLessThan(80);
  expect(await inDialog(page), `focus ended on ${await focusDescription(page)}`).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
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
  const trigger = page.getByRole("button", { name: "Add retailer" });
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
  const api = await apiContext();
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
  const trigger = page.getByRole("button", { name: "New order" });
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

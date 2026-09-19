/**
 * Dialogs on a phone and a tablet (design §13.7, #259). Below 768 px every
 * dialog is a full-screen sheet — its head with the title and Close, the form
 * the one scroller, the two actions in a bar at the foot of the screen — and an
 * order line is a stacked card; from 768 px a dialog is the centred panel it
 * was. Runs in three projects (playwright.config.ts): `phone` and `tablet` with
 * a touch screen, `app` with a mouse. What it holds:
 *
 * - at 390 px and at 320 px the New order form, with a kit line and a catalog
 *   line, has no control past the screen's edge and no field squeezed under the
 *   room a field needs, and its primary action and its Close are on screen — and
 *   under a finger, not the tab bar — at every scroll position; the same of the
 *   kit, inventory, retailer and Apply-to-kit dialogs;
 * - an order with a kit line and a catalog line is recorded from a 320 × 568 px
 *   phone, and a kit is edited there, driven through to the API — the primary
 *   tapped from the top of the form, without a scroll;
 * - quantity and price carry visible labels on a phone and the desktop's row
 *   keeps its shape; a quantity raises a numeric keyboard and money a decimal
 *   one, in every shell;
 * - a checkbox row and the picker's result rows are a finger tall on a phone;
 * - Delete is in the form on a phone and in the action row on the desktop, and
 *   a turn across the line keeps the keyboard on it (`lib/focusKey.ts`);
 * - a row of fields folds to a column where its box is too narrow for the row:
 *   at 320 px, and under the browser's own font-size preference at 32 and 40 px,
 *   where a 390 px phone's dialog is narrower than three fields;
 * - from 768 px the dialog is a panel narrower than the screen, below its top,
 *   and the line's quantity and price sit on the type's row, unlabelled.
 *
 * WebKit's Tab, which skips buttons (#267), is dialog-keyboard.spec.ts's under
 * a local WebKit run; CI installs Chromium alone.
 *
 * Widths and sizes are literals from the decision record, never imported from
 * `src/`. Every row this file needs it seeds through the API and deletes.
 */
import { chromium, expect, test, type Locator, type Page } from "@playwright/test";

import { APP, STORAGE_STATE, apiContext } from "./api";

type Size = { width: number; height: number };

const SIZES: Record<string, Size[]> = {
  app: [{ width: 1280, height: 720 }],
  phone: [
    { width: 320, height: 568 },
    { width: 390, height: 844 },
    { width: 744, height: 1133 },
  ],
  tablet: [
    { width: 820, height: 1180 },
    { width: 1180, height: 820 },
  ],
};
const sizesFor = (project: string): Size[] => {
  const sizes = SIZES[project];
  if (!sizes) throw new Error(`dialogs.spec.ts has no viewports for the "${project}" project`);
  return sizes;
};
const isPhone = (size: Size) => size.width < 768;

/** A finger (§13.7), the room a field needs before its row folds (about 100 px
 *  at the default font size — 6rem here, a shade under the rule's 6.25, so it
 *  follows the browser's font-size preference as the rule does; index.css
 *  `stack-3:`/`stack-2:`), and the phone's bar buttons. */
const FINGER = 44;
const FIELD_ROOM_REM = 6;
const BAR_BUTTON = 48;

const suffix = String(Date.now()).slice(-8);
const TAG = `E2E Dialogs ${suffix}`;
const q = encodeURIComponent(TAG);
const NAMES = {
  retailer: `${TAG} Shop`,
  kit: `${TAG} Zaku`,
  consumable: `${TAG} Cement`,
  tool: `${TAG} Nippers`,
  // A long unbroken token, as a product code is: the applied-upgrade row has to
  // give Withdraw the next line where the two do not share one, and break the
  // token where no line holds it — 42 characters are wider than a 390 px phone's
  // row at the default font (a short name let the row's remedies cover for each
  // other, and a 29-character one fitted every tested line: mutants survived
  // both, Codex #272 round 1).
  upgrade: `${TAG} MSN-04-II-NIGHTINGALE-VERNIER-THRUSTER-SET`,
  // And one with nowhere to break at all — no hyphen, no space after the tag:
  // a part number run together, the name #273 was reported with, twice over.
  // 46 characters were wider than a 320 px sheet and no wider than the
  // desktop's 700 px row, where a row that wrapped at every width therefore
  // looked exactly like one that did not (the mutant survived); 92 are wider
  // than both.
  unbroken: `${TAG} MSN04IINIGHTINGALEVERNIERTHRUSTERSET1234567890MSN04IINIGHTINGALEVERNIERTHRUSTERSET1234567890`,
};

let retailerId: string;
let kitId: string;
let consumableId: string;
let toolId: string;
let upgradeId: string;
let unbrokenId: string;
let applicationId: string;

test.beforeAll(async () => {
  const api = await apiContext();
  const made = async (path: string, data: unknown): Promise<string> => {
    const response = await api.post(path, { data });
    expect(response.status(), `${path}: ${await response.text()}`).toBe(201);
    return ((await response.json()) as { id: string }).id;
  };
  retailerId = await made("/retailers", { name: NAMES.retailer });
  kitId = await made("/kits", { name: NAMES.kit, grade: "HG", status: "backlog" });
  consumableId = await made("/consumables", { name: NAMES.consumable, category: "glue", quantity_on_hand: 2 });
  toolId = await made("/tools", { name: NAMES.tool, category: "nippers", quantity_on_hand: 1 });
  upgradeId = await made("/upgrades", { name: NAMES.upgrade, manufacturer: "E2E", quantity_on_hand: 3 });
  unbrokenId = await made("/upgrades", { name: NAMES.unbroken, manufacturer: "E2E", quantity_on_hand: 0 });
  // The kit carries an applied upgrade, so its dialog draws the applied-upgrades
  // row and the withdrawal question — the state Codex #272 found unexamined:
  // under a 32 px font that row was 16 px past a 390 px sheet (finding 1).
  applicationId = await made(`/upgrades/${upgradeId}/apply`, { kit_id: kitId, quantity: 2 });
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  // First: an upgrade with an application on record refuses deletion (rule 3).
  await api.delete(`/upgrades/${upgradeId}/applications/${applicationId}?restore_stock=true`);
  await api.delete(`/kits/${kitId}`);
  await api.delete(`/consumables/${consumableId}`);
  await api.delete(`/tools/${toolId}`);
  await api.delete(`/upgrades/${upgradeId}`);
  await api.delete(`/upgrades/${unbrokenId}`);
  await api.delete(`/retailers/${retailerId}`);
  await api.dispose();
});

const dialog = (page: Page): Locator => page.getByRole("dialog");

/** The sheet's one scroller: the element inside the dialog whose overflow is
 *  its own. On the desktop the overlay scrolls instead, and this is null. */
async function scrollerOf(page: Page): Promise<Locator | null> {
  const found = await dialog(page).evaluate((element) =>
    [...element.querySelectorAll<HTMLElement>("div")].findIndex(
      (div) => getComputedStyle(div).overflowY === "auto" && div.scrollHeight > div.clientHeight,
    ),
  );
  return found === -1 ? null : dialog(page).locator("div").nth(found);
}

/** Every drawn control of the open dialog is inside the screen, no field is
 *  squeezed under the room a field needs (on a phone — the desktop's line row
 *  keeps its 80 px quantity), no scroller inside the dialog scrolls sideways
 *  (the sheet's body is one: `overflow-y: auto` makes its x `auto` too, so
 *  content wider than the screen would scroll there instead of overflowing
 *  it), and the document does not either. */
async function expectDialogFits(page: Page, label: string, phone = true, pageToo = true): Promise<void> {
  const report = await dialog(page).evaluate((element, roomRem) => {
    const room = roomRem * parseFloat(getComputedStyle(document.documentElement).fontSize);
    const drawn = (node: Element) => node.getClientRects().length > 0;
    const say = (node: Element) =>
      node.getAttribute("aria-label") ??
      node.getAttribute("placeholder") ??
      (node as HTMLElement).innerText?.trim().slice(0, 30) ??
      node.tagName;
    const controls = [...element.querySelectorAll<HTMLElement>("input, select, textarea, button, a[href]")].filter(drawn);
    const isField = (node: Element) => node.matches("input:not([type=checkbox]):not([type=radio]), select, textarea");
    const fields = controls.filter(isField).map((field) => ({ field, rect: field.getBoundingClientRect() }));
    const outside: string[] = [];
    const squeezed: string[] = [];
    const uncarded: string[] = [];
    for (const control of controls) {
      const rect = control.getBoundingClientRect();
      // Inside the screen is not inside its card: a button 15 px past the
      // bordered box it belongs to is still on a 320 px screen. Every box with
      // a border or a ground of its own between the control and the dialog.
      for (let box = control.parentElement; box && box !== element; box = box.parentElement) {
        if (!/(^|\s)(border|bg-surface-alt)(\s|$)/.test(box.className.toString())) continue;
        const bounds = box.getBoundingClientRect();
        if (rect.left < bounds.left - 0.5 || rect.right > bounds.right + 0.5) {
          uncarded.push(`${say(control)} [${Math.round(rect.left)}–${Math.round(rect.right)}] outside its box [${Math.round(bounds.left)}–${Math.round(bounds.right)}]`);
          break;
        }
      }
      if (rect.left < -0.5 || rect.right > innerWidth + 0.5) {
        outside.push(`${say(control)} [${Math.round(rect.left)}–${Math.round(rect.right)}] of ${innerWidth}`);
      }
      // Squeezed: under the room a field needs *with another field beside it*
      // — a field alone on its row has what its box has, which on a 320 px
      // phone under a 40 px font is less than the room and all there is.
      const beside = fields.some(
        ({ field, rect: other }) =>
          field !== control && Math.abs(other.top - rect.top) < rect.height / 2 && Math.abs(other.left - rect.left) > 1,
      );
      if (isField(control) && rect.width < room && beside) squeezed.push(`${say(control)} ${Math.round(rect.width)} px`);
    }
    const sideways = [...element.querySelectorAll<HTMLElement>("div")]
      .filter((node) => drawn(node) && ["auto", "scroll"].includes(getComputedStyle(node).overflowX) && node.scrollWidth > node.clientWidth + 1)
      .map((node) => `${node.tagName.toLowerCase()}.${node.className.toString().split(" ")[0]} ${node.scrollWidth} in ${node.clientWidth}`);
    // And nothing says more than its own box holds. A word 20 px past its
    // column lands in the sheet's 40 px of padding: no scroller moves, no
    // control is off the screen, and the text is over the edge of its form
    // (the order form's "Already in hand" row and its help text, under a 40 px
    // font, with the sheet's `break-words` taken out — a mutant that survived
    // every other check here). Controls clip or scroll their own text.
    const spilled = [...element.querySelectorAll<HTMLElement>("*")]
      .filter((node) => drawn(node) && !node.matches("input, select, textarea, option, svg, svg *"))
      .filter((node) => getComputedStyle(node).display !== "inline" && getComputedStyle(node).overflowX === "visible")
      .filter((node) => node.scrollWidth > node.clientWidth + 1)
      // One deliberate exception, named: under `touch:` the head's Close is a
      // 44 px target around a 16 px icon with the extra taken back as negative
      // margin (`Modal`), so the head's row is 10 px "wider" than itself.
      .filter((node) => node.querySelector(':scope > button[aria-label="Close"]') === null)
      .map((node) => `${node.tagName.toLowerCase()} "${(node.textContent ?? "").trim().slice(0, 24)}" ${node.scrollWidth} in ${node.clientWidth}`);
    return {
      controls: controls.length,
      outside,
      squeezed,
      uncarded,
      sideways,
      spilled,
      document: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
    };
  }, phone ? FIELD_ROOM_REM : 0);
  expect(report.controls, `${label}: no control in the dialog`).toBeGreaterThan(0);
  expect.soft(report.outside, `${label}: controls past the screen's edge`).toEqual([]);
  expect.soft(report.squeezed, `${label}: fields under the room a field needs`).toEqual([]);
  expect.soft(report.uncarded, `${label}: controls past the edge of their own box`).toEqual([]);
  expect.soft(report.sideways, `${label}: something in the dialog scrolls sideways`).toEqual([]);
  expect.soft(report.spilled, `${label}: said past its own box`).toEqual([]);
  if (pageToo) expect.soft(report.document[0], `${label}: the document scrolls sideways`).toBeLessThanOrEqual(report.document[1]);
}

/** The sheet's own edges are the screen's. Asked where the *page* under it is
 *  not — at 40 px on a 320 px phone the page head and the tab bar are past the
 *  screen (#269, the shell's), and the document scrolls sideways for the page's
 *  sake, not the dialog's. */
async function expectDialogInsideScreen(page: Page, label: string): Promise<void> {
  const edges = await dialog(page).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: innerWidth, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth };
  });
  expect.soft(edges.left, `${label}: the sheet starts at the screen's edge`).toBe(0);
  expect.soft(edges.right, `${label}: the sheet ends at the screen's edge`).toBe(edges.width);
  expect.soft(edges.scrollWidth, `${label}: nothing in the sheet is wider than it`).toBeLessThanOrEqual(edges.clientWidth);
}

/** Back to the top of whatever scrolls — the overlay, the sheet's body — so
 *  that "on screen without a scroll" is asked from the top and not from
 *  wherever the last click left the form (on `main`, a click on a picker
 *  result near the form's end had scrolled the actions into view, and the
 *  test passed for the wrong reason). */
async function scrollToTop(page: Page): Promise<void> {
  await page.evaluate(() => {
    for (const element of document.querySelectorAll<HTMLElement>('[role="dialog"], [role="dialog"] *, body')) {
      element.scrollTop = 0;
      if (element.parentElement) element.parentElement.scrollTop = 0;
    }
    window.scrollTo(0, 0);
  });
}

/** The applied upgrade's name in its row: never cut — a token wider than its
 *  line breaks rather than running under Withdraw — and, on a phone, with the
 *  room a field has, which is what giving Withdraw the next line is for. */
async function expectUpgradeNameReads(page: Page, label: string, phone: boolean): Promise<void> {
  const name = dialog(page).locator("li").getByText(NAMES.upgrade).first();
  await expect.soft(name, `${label}: the applied upgrade's name`).toBeVisible();
  const read = await name.evaluate((element) => ({
    cut: element.scrollWidth > element.clientWidth + 1,
    width: element.getBoundingClientRect().width,
    row: (element.closest("li") as HTMLElement).clientWidth,
    rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
  }));
  expect.soft(read.cut, `${label}: the name runs past its own box`).toBe(false);
  // A field's room, or the whole row where the row is less than that — a
  // 320 px phone under a 40 px font, where the row is all there is.
  if (phone) expect.soft(read.width, `${label}: the name has a field's room`).toBeGreaterThanOrEqual(Math.min(FIELD_ROOM_REM * read.rem, read.row - 1));
}

/** Measure the sheet against the *screen*. Under a large browser font the page
 *  behind it is wider than a phone (#269, #270 — the shell's and the cards',
 *  filed), and a page wider than the screen widens the layout viewport: a sheet
 *  measured against that has room the screen does not. It hid a button 3 px
 *  past a 320 px screen and 43 px past its own card (Codex #272, finding 4).
 *  The page is inert under the dialog and the dialog a portal beside it, so the
 *  page is taken out of layout while the sheet is measured, and the screen's
 *  width is asserted, not assumed. */
async function isolateSheet(page: Page, width: number, label: string): Promise<void> {
  await page.evaluate(() => {
    (document.getElementById("root") as HTMLElement).style.display = "none";
  });
  await expect.poll(() => page.evaluate(() => innerWidth), `${label}: the screen the sheet is measured against`).toBe(width);
}
async function restorePage(page: Page): Promise<void> {
  await page.evaluate(() => {
    (document.getElementById("root") as HTMLElement).style.display = "";
  });
}

/** On screen, inside the viewport, and what a tap at its centre lands on. */
async function expectUnderAFinger(control: Locator, label: string): Promise<void> {
  await expect(control, label).toBeVisible();
  const hit = await control.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const top = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return {
      hits: top !== null && (element === top || element.contains(top)),
      top: top ? `${top.tagName.toLowerCase()} "${(top.textContent ?? "").trim().slice(0, 30)}"` : "nothing",
      inViewport: box.top >= 0 && box.left >= 0 && box.bottom <= innerHeight + 0.5 && box.right <= innerWidth + 0.5,
      width: box.width,
      height: box.height,
    };
  });
  expect.soft(hit, `${label}: a tap at its centre lands on ${hit.top}`).toMatchObject({ hits: true, inViewport: true });
}

/** A control's label *reads*: its ink is inside the control's own box, and it
 *  breaks between its words at most. A clickable box of the right size says
 *  neither — under a 40 px font "Cancel" was six lines of one letter, the first
 *  of them above the button (Codex #274, finding 1). `maxLines` for a label
 *  whose longest word is itself wider than the room (it may break once more). */
async function expectLabelReads(control: Locator, label: string, maxLines?: number): Promise<void> {
  await expect(control, label).toBeVisible();
  const said = await control.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const ink = [...range.getClientRects()].filter((rect) => rect.width > 0);
    const box = element.getBoundingClientRect();
    return {
      words: (element.textContent ?? "").trim().split(/\s+/).length,
      lines: new Set(ink.map((rect) => Math.round(rect.top))).size,
      outside: ink.filter((rect) => rect.top < box.top - 0.5 || rect.bottom > box.bottom + 0.5 || rect.left < box.left - 0.5 || rect.right > box.right + 0.5).length,
      spill: [element.scrollWidth - element.clientWidth, element.scrollHeight - element.clientHeight],
    };
  });
  expect.soft(said.lines, `${label}: its label's lines, of ${said.words} words`).toBeLessThanOrEqual(maxLines ?? said.words);
  expect.soft(said.outside, `${label}: pieces of its label outside its box`).toBe(0);
  expect.soft(Math.max(...said.spill), `${label}: its label spills its box`).toBeLessThanOrEqual(1);
}

/** Fitting is not reading (pages.spec.ts says the same of a page's action): a
 *  thing beside another may fit by being squeezed to a letter a line. It has
 *  the width it would take on one line, or its row's. */
async function expectItsRoom(thing: Locator, label: string): Promise<void> {
  const room = await thing.evaluate((element) => {
    const copy = element.cloneNode(true) as HTMLElement;
    copy.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;max-width:none;flex:none;overflow-wrap:normal";
    element.parentElement!.appendChild(copy);
    const natural = copy.getBoundingClientRect().width;
    copy.remove();
    const row = element.parentElement as HTMLElement;
    const style = getComputedStyle(row);
    return { width: element.getBoundingClientRect().width, natural, row: row.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) };
  });
  expect.soft(room.width, `${label}: its width, of ${Math.round(room.natural)} on one line in a row of ${Math.round(room.row)}`).toBeGreaterThanOrEqual(Math.min(room.natural, room.row) - 1);
}

/** A phone's dialog: the head at the top of the screen, the bar at its foot, and
 *  the primary action and Close under a finger at the top, the middle and the
 *  end of the form's scroll. */
async function expectSheet(page: Page, primary: string, label: string): Promise<void> {
  const head = dialog(page).getByRole("heading", { level: 2 });
  const close = dialog(page).getByRole("button", { name: "Close" });
  const action = dialog(page).getByRole("button", { name: primary, exact: true });
  const scroller = await scrollerOf(page);
  const positions = scroller ? ["top", "middle", "end"] : ["top"];
  for (const position of positions) {
    if (scroller) {
      await scroller.evaluate((element, where) => {
        const max = element.scrollHeight - element.clientHeight;
        element.scrollTop = where === "top" ? 0 : where === "middle" ? max / 2 : max;
      }, position);
    }
    const at = `${label}, scrolled to the ${position}`;
    await expect.soft(head, at).toBeVisible();
    const headBox = await head.boundingBox();
    expect.soft(headBox?.y, `${at}: the head is at the top of the screen`).toBeLessThan(FINGER);
    await expectUnderAFinger(close, `${at}: Close`);
    await expectUnderAFinger(action, `${at}: "${primary}"`);
    const actionBox = await action.boundingBox();
    expect.soft(actionBox?.height, `${at}: "${primary}" is a bar button`).toBeGreaterThanOrEqual(BAR_BUTTON);
    expect.soft((actionBox?.y ?? 0) + (actionBox?.height ?? 0), `${at}: the bar is at the foot of the screen`).toBeGreaterThan(
      (await page.evaluate(() => innerHeight)) - 2 * FINGER,
    );
  }
}

/** From 768 px: the panel it was — narrower than the screen, 48 px below its
 *  top with the overlay the scroller, the actions inside it and nothing inside
 *  it scrolling on its own. */
async function expectPanel(page: Page, primary: string, label: string): Promise<void> {
  const frame = await dialog(page).evaluate((element) => {
    const overlay = element.parentElement as HTMLElement;
    overlay.scrollTop = 0;
    return {
      overlayScrolls: getComputedStyle(overlay).overflowY === "auto",
      top: element.getBoundingClientRect().top,
      width: element.getBoundingClientRect().width,
      screen: innerWidth,
    };
  });
  expect.soft(frame.width, `${label}: the panel is narrower than the screen`).toBeLessThan(frame.screen - 16);
  expect.soft(frame.top, `${label}: the panel sits 48 px below the top of the screen`).toBe(48);
  expect.soft(frame.overlayScrolls, `${label}: the overlay is the scroller`).toBe(true);
  expect.soft(await scrollerOf(page), `${label}: nothing inside the panel scrolls on its own`).toBeNull();
  const action = dialog(page).getByRole("button", { name: primary, exact: true });
  const actionBox = await action.boundingBox();
  expect.soft(actionBox?.height, `${label}: "${primary}" is a row button`).toBeLessThan(BAR_BUTTON);
}

async function openFromList(page: Page, path: string, control: string | RegExp): Promise<void> {
  await page.goto(path);
  await page.getByRole("button", { name: control }).first().click();
  await expect(dialog(page)).toBeVisible();
}

test("every dialog fits a phone's screen and is the panel it was on a tablet", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  for (const size of sizesFor(testInfo.project.name)) {
    await page.setViewportSize(size);
    const at = `at ${size.width} px`;
    const expectFrame = isPhone(size) ? expectSheet : expectPanel;

    await test.step(`New order ${at}`, async () => {
      await openFromList(page, "/orders", "New order");
      // A kit line and a catalog line, with the picker's results open, so the
      // widest line the form draws is the one measured.
      await dialog(page).getByRole("button", { name: "Add line" }).click();
      await dialog(page).locator('select:has(option[value="consumable"])').last().selectOption("consumable");
      const search = dialog(page).getByPlaceholder(/Search consumables/).last();
      await search.fill(NAMES.consumable);
      const results = dialog(page).locator("div.absolute button");
      await expect(results.first()).toBeVisible();
      await expectDialogFits(page, `New order ${at}, results open`, isPhone(size));
      if (isPhone(size)) {
        for (const result of await results.all()) {
          const box = await result.boundingBox();
          expect.soft(box?.height, `${at}: a picker row is a finger tall`).toBeGreaterThanOrEqual(FINGER);
          expect.soft(box?.width, `${at}: a picker row spans the field`).toBeGreaterThan(size.width - 80);
        }
        for (const name of [/^Already in hand/, /^Pre-order/]) {
          const row = dialog(page).locator("label").filter({ hasText: name });
          expect.soft((await row.boundingBox())?.height, `${at}: the checkbox row "${name}"`).toBeGreaterThanOrEqual(FINGER);
        }
      }
      await results.first().click();
      await expect(dialog(page).getByRole("button", { name: "Change" })).toBeVisible();
      await expectDialogFits(page, `New order ${at}, a chosen item`, isPhone(size));
      await expectFrame(page, "Record order", `New order ${at}`);
      await page.keyboard.press("Escape");
    });

    await test.step(`Edit kit ${at}`, async () => {
      await openFromList(page, `/kits?q=${q}`, `Edit ${NAMES.kit}`);
      await expectDialogFits(page, `Edit kit ${at}`, isPhone(size));
      await expectFrame(page, "Save", `Edit kit ${at}`);
      // The applied upgrade's row, and the question its Withdraw opens.
      await expectUpgradeNameReads(page, `Edit kit ${at}`, isPhone(size));
      await dialog(page).getByRole("button", { name: "Withdraw…", exact: true }).click();
      await expect(dialog(page).getByRole("button", { name: /^Withdraw — / }).first()).toBeVisible();
      await expectDialogFits(page, `Edit kit ${at}, the withdrawal question open`, isPhone(size));
      await page.keyboard.press("Escape");
    });

    await test.step(`Edit consumable ${at}`, async () => {
      await page.goto("/inventory?tab=consumables");
      await page.getByRole("button", { name: `Edit ${NAMES.consumable}` }).click();
      await expect(dialog(page)).toBeVisible();
      await expectDialogFits(page, `Edit consumable ${at}`, isPhone(size));
      await expectFrame(page, "Save", `Edit consumable ${at}`);
      await page.keyboard.press("Escape");
    });

    await test.step(`Apply to kit ${at}`, async () => {
      await page.goto("/inventory?tab=upgrades");
      await page.getByRole("button", { name: "Apply to kit" }).first().click();
      await expect(dialog(page)).toBeVisible();
      await expectDialogFits(page, `Apply to kit ${at}`, isPhone(size));
      await expectFrame(page, "Apply", `Apply to kit ${at}`);
      await page.keyboard.press("Escape");
    });

    await test.step(`Edit retailer ${at}`, async () => {
      await openFromList(page, `/retailers?q=${q}`, `Edit ${NAMES.retailer}`);
      await expectDialogFits(page, `Edit retailer ${at}`, isPhone(size));
      await expectFrame(page, "Save", `Edit retailer ${at}`);
      await page.keyboard.press("Escape");
    });
  }
});

test("an order line is a stacked card on a phone and the row it was from 768 px", async ({ page }, testInfo) => {
  for (const size of sizesFor(testInfo.project.name)) {
    await page.setViewportSize(size);
    const at = `at ${size.width} px`;
    await openFromList(page, "/orders", "New order");
    const line = dialog(page).locator('select:has(option[value="kit"])').first().locator("xpath=ancestor::div[contains(@class, 'rounded-md')][1]");
    const type = line.locator("select").first();
    const quantity = line.getByLabel("Quantity");
    const price = line.getByLabel("Unit price");
    const grade = line.getByPlaceholder("Grade *");
    const scale = line.getByPlaceholder("Scale");
    const number = line.getByPlaceholder("Kit #");
    const [typeBox, quantityBox, priceBox, gradeBox, scaleBox, numberBox] = await Promise.all(
      [type, quantity, price, grade, scale, number].map((control) => control.boundingBox()),
    );
    // The labels: drawn on a phone, not on the desktop — read by the label
    // element, since the accessible name is "Quantity" in both.
    const labelsDrawn = await line.evaluate((element) =>
      [...element.querySelectorAll("label")].filter((label) => label.getClientRects().length > 0).map((label) => label.textContent?.trim()),
    );
    // The keyboards a phone raises (every shell carries the attribute).
    await expect.soft(quantity, at).toHaveAttribute("inputmode", "numeric");
    await expect.soft(price, at).toHaveAttribute("inputmode", "decimal");
    await expect.soft(dialog(page).getByLabel("Shipping cost"), at).toHaveAttribute("inputmode", "decimal");
    // The head's fields: the retailer's row and the tracking URL's their own on a
    // phone with the pairs between; three to a row on the desktop, as it was.
    const rowOf = async (label: string | RegExp) => Math.round((await dialog(page).getByLabel(label).boundingBox())!.y);
    const rows = {
      retailer: await rowOf(/^Retailer/),
      date: await rowOf("Order date"),
      currency: await rowOf("Currency"),
      number: await rowOf("Order number"),
      shipping: await rowOf("Shipping cost"),
      service: await rowOf("Delivery service"),
      tracking: await rowOf("Tracking number"),
      url: await rowOf("Tracking URL"),
    };
    const distinct = (...values: number[]) => new Set(values).size === values.length;
    if (isPhone(size)) {
      expect.soft(rows.date, `${at}: date and currency share a row`).toBe(rows.currency);
      expect.soft(rows.number, `${at}: number and shipping cost share a row`).toBe(rows.shipping);
      expect.soft(rows.service, `${at}: delivery service and tracking number share a row`).toBe(rows.tracking);
      expect.soft(distinct(rows.retailer, rows.date, rows.number, rows.service, rows.url), `${at}: the retailer and the URL have rows of their own`).toBe(true);
    } else {
      expect.soft([rows.date, rows.currency], `${at}: retailer, date and currency share a row`).toEqual([rows.retailer, rows.retailer]);
      expect.soft([rows.shipping, rows.service], `${at}: number, shipping cost and delivery service share a row`).toEqual([rows.number, rows.number]);
      expect.soft(rows.url, `${at}: tracking number and URL share a row`).toBe(rows.tracking);
      expect.soft(distinct(rows.retailer, rows.number, rows.tracking), `${at}: three rows`).toBe(true);
    }
    if (isPhone(size)) {
      expect.soft(labelsDrawn, `${at}: the labels are drawn`).toEqual(["Quantity", "Unit price"]);
      expect.soft(quantityBox!.y, `${at}: quantity is under the type`).toBeGreaterThan(typeBox!.y + typeBox!.height - 1);
      expect.soft(Math.abs(quantityBox!.y - priceBox!.y), `${at}: quantity and price share a row`).toBeLessThan(2);
      expect.soft(gradeBox!.y, `${at}: the kit fields are under the price`).toBeGreaterThan(priceBox!.y + priceBox!.height - 1);
      // The currency code inside the price field: drawn within the field's box,
      // on both axes — a code on the line *under* the field shares its
      // horizontal span (a mutant survived the one-axis check).
      const code = line.getByText(/^[A-Z]{3}$/).first();
      const codeBox = await code.boundingBox();
      expect.soft(codeBox!.x + codeBox!.width, `${at}: the code ends inside the price field`).toBeLessThanOrEqual(priceBox!.x + priceBox!.width);
      expect.soft(codeBox!.x, `${at}: the code starts inside the price field`).toBeGreaterThanOrEqual(priceBox!.x);
      expect.soft(codeBox!.y, `${at}: the code is on the price field's line`).toBeGreaterThanOrEqual(priceBox!.y);
      expect.soft(codeBox!.y + codeBox!.height, `${at}: the code is on the price field's line`).toBeLessThanOrEqual(priceBox!.y + priceBox!.height);
      // Three across where the card has room for three, a column where not:
      // a 320 px phone's card is 262 px, under the 324 the row needs.
      if (size.width >= 390) {
        expect.soft(Math.abs(gradeBox!.y - scaleBox!.y) + Math.abs(scaleBox!.y - numberBox!.y), `${at}: grade, scale and number three across`).toBeLessThan(2);
      } else {
        expect.soft(scaleBox!.y, `${at}: scale under grade`).toBeGreaterThan(gradeBox!.y + gradeBox!.height - 1);
        expect.soft(numberBox!.y, `${at}: number under scale`).toBeGreaterThan(scaleBox!.y + scaleBox!.height - 1);
      }
      // Two lines: the remove control beside the type, a finger's size.
      await dialog(page).getByRole("button", { name: "Add line" }).click();
      const remove = dialog(page).getByRole("button", { name: "Remove line" }).first();
      const removeBox = await remove.boundingBox();
      expect.soft(removeBox!.width, `${at}: the remove control is a finger wide`).toBeGreaterThanOrEqual(FINGER);
      expect.soft(removeBox!.height, `${at}: the remove control is a finger tall`).toBeGreaterThanOrEqual(FINGER);
      const typeAgain = await type.boundingBox();
      expect.soft(Math.abs(removeBox!.y + removeBox!.height / 2 - (typeAgain!.y + typeAgain!.height / 2)), `${at}: the remove control is on the type's row`).toBeLessThan(4);
      expect.soft(removeBox!.x + removeBox!.width, `${at}: the remove control is inside the screen`).toBeLessThanOrEqual(size.width + 0.5);
    } else {
      expect.soft(labelsDrawn, `${at}: no label is drawn`).toEqual([]);
      // The desktop's quantity sits 2 px under the row's centre, as it always
      // has (an empty label's margin, kept for parity — the comment in
      // `LineEditor` says why); on the row, within that.
      expect.soft(Math.abs(quantityBox!.y + quantityBox!.height / 2 - (typeBox!.y + typeBox!.height / 2)), `${at}: quantity is on the type's row`).toBeLessThan(3);
      expect.soft(Math.abs(priceBox!.y + priceBox!.height / 2 - (typeBox!.y + typeBox!.height / 2)), `${at}: price is on the type's row`).toBeLessThan(2);
      expect.soft(Math.abs(gradeBox!.y - scaleBox!.y) + Math.abs(scaleBox!.y - numberBox!.y), `${at}: grade, scale and number three across`).toBeLessThan(2);
      expect.soft(quantityBox!.width, `${at}: the desktop's quantity is 80 px`).toBe(80);
      expect.soft(priceBox!.width, `${at}: the desktop's price is 112 px`).toBe(112);
    }
    await page.keyboard.press("Escape");
  }
});

test("an order with a kit line and a catalog line is recorded from a phone, and a kit is edited there", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the sheet is the phone shell's");
  page.on("dialog", (native) => native.accept());
  // The smallest phone there is, and a short one: on `main` the desktop-shaped
  // form with two lines fits an 844 px screen whole, so "the primary without a
  // scroll" held there for the wrong reason; at 568 px it cannot, and the
  // branch's bar is at the foot whatever the height.
  await page.setViewportSize({ width: 320, height: 568 });
  const kitName = `${TAG} Recorded`;

  await openFromList(page, "/orders", "New order");
  await dialog(page).getByRole("combobox", { name: /^Retailer/ }).selectOption(retailerId);
  await dialog(page).getByLabel("Unit price").first().fill("10");
  await dialog(page).getByPlaceholder("Kit name *").fill(kitName);
  await dialog(page).getByPlaceholder("Grade *").fill("HG");
  await dialog(page).getByRole("button", { name: "Add line" }).click();
  await dialog(page).locator('select:has(option[value="consumable"])').last().selectOption("consumable");
  await dialog(page).getByLabel("Quantity").last().fill("3");
  await dialog(page).getByLabel("Unit price").last().fill("2");
  await dialog(page).getByPlaceholder(/Search consumables/).fill(NAMES.consumable);
  const results = dialog(page).locator("div.absolute button");
  await expect(results.first()).toBeVisible();
  await results.first().click();
  // The primary is in the bar, on screen without a scroll: a tap, not a scroll
  // then a tap — asked from the top of the form, not from where the last click
  // left it.
  await scrollToTop(page);
  const record = dialog(page).getByRole("button", { name: "Record order", exact: true });
  await expectUnderAFinger(record, "Record order before any scroll");
  await record.click();
  await expect(dialog(page)).toBeHidden();

  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as {
    id: string;
    retailer_id: string;
    items: { item_type: string; quantity: number; catalog_ref_id: string | null; kits: { name: string }[] }[];
  }[];
  const stored = orders.find((order) => order.retailer_id === retailerId);
  expect(stored, "the order reached the API").toBeTruthy();
  expect(stored!.items.map((item) => [item.item_type, item.quantity, item.catalog_ref_id])).toEqual([
    ["kit", 1, null],
    ["consumable", 3, consumableId],
  ]);
  expect(stored!.items[0].kits[0].name).toBe(kitName);

  // Edit the kit the order spawned, from the phone's card.
  await openFromList(page, `/kits?q=${encodeURIComponent(kitName)}`, `Edit ${kitName}`);
  await dialog(page).getByLabel("Series").fill(`${TAG} Saga`);
  await scrollToTop(page);
  const save = dialog(page).getByRole("button", { name: "Save", exact: true });
  await expectUnderAFinger(save, "Save before any scroll");
  await save.click();
  await expect(dialog(page)).toBeHidden();
  const kits = (await (await api.get(`/kits?q=${encodeURIComponent(kitName)}`)).json()) as { name: string; series: string | null }[];
  expect(kits.find((kit) => kit.name === kitName)?.series).toBe(`${TAG} Saga`);

  await api.delete(`/orders/${stored!.id}`); // the spawned kit goes with it
  await api.dispose();
});

test("Delete is in the form on a phone and in the action row on the desktop, and a turn keeps the keyboard on it", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the two sides of the line are the phone project's sizes");
  // The wide end of the phone shell and the rail beside it: an iPad mini turning.
  await page.setViewportSize({ width: 744, height: 1133 });
  await openFromList(page, `/kits?q=${q}`, `Edit ${NAMES.kit}`);
  const del = dialog(page).getByRole("button", { name: "Delete", exact: true });
  const bar = dialog(page).getByRole("button", { name: "Save", exact: true });
  const place = async () => {
    const [delBox, barBox] = await Promise.all([del.boundingBox(), bar.boundingBox()]);
    return { deleteAboveBar: delBox!.y + delBox!.height <= barBox!.y, sameRow: Math.abs(delBox!.y - barBox!.y) < 2 };
  };
  expect(await place(), "at 744 px: Delete is in the form, above the bar").toMatchObject({ deleteAboveBar: true, sameRow: false });
  await expect(del, "one Delete is drawn").toHaveCount(1);

  await del.focus();
  await expect(del).toBeFocused();
  await page.setViewportSize({ width: 1133, height: 744 });
  await expect.poll(async () => (await dialog(page).boundingBox())!.width, "the panel").toBeLessThan(600);
  expect(await place(), "at 1133 px: Delete is on the action row").toMatchObject({ sameRow: true });
  await expect(del, "the keyboard is on the desktop's Delete").toBeFocused();

  await page.setViewportSize({ width: 744, height: 1133 });
  await expect.poll(async () => (await place()).deleteAboveBar, "back to the form").toBe(true);
  await expect(del, "the keyboard is on the phone's Delete").toBeFocused();
  await page.keyboard.press("Escape");
});

test("a dialog fits a phone under the browser's own font-size preference", async ({ browserName }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the sheet is the phone shell's");
  test.skip(browserName !== "chromium", "the preference is Chromium's launch flag");
  test.setTimeout(120_000);
  // The axis Codex #266 asked of the cards, asked of the dialogs: every size in
  // a dialog is in rem and follows the preference; the screen does not. A row
  // of fields folds by its box (`stack-3:`, `stack-2:`), so at 32 px a 390 px
  // phone's kit dialog — 358 px of body, 11.2rem — is one field to a row, and
  // the bar's buttons keep a finger's height inside the screen.
  for (const font of [32, 40]) {
    const browser = await chromium.launch({ args: [`--blink-settings=defaultFontSize=${font}`] });
    try {
      const context = await browser.newContext({ storageState: STORAGE_STATE, hasTouch: true, isMobile: true, baseURL: APP });
      const page = await context.newPage();
      for (const size of sizesFor("phone").filter(isPhone)) {
        await page.setViewportSize(size);
        const at = `at ${size.width} px, ${font} px font`;
        await openFromList(page, `/kits?q=${q}`, `Edit ${NAMES.kit}`);
        expect(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)), "the root font size").toBe(font);
        await isolateSheet(page, size.width, `Edit kit ${at}`);
        await expectDialogFits(page, `Edit kit ${at}`, true, false);
        await expectDialogInsideScreen(page, `Edit kit ${at}`);
        // Codex #272, finding 1: the applied upgrade's row — its name, its date
        // and Withdraw — and the question under it, before and after it opens.
        const withdraw = dialog(page).getByRole("button", { name: "Withdraw…", exact: true });
        await expect(withdraw, `${at}: the applied upgrade's row`).toBeVisible();
        await expectUpgradeNameReads(page, `Edit kit ${at}`, true);
        await withdraw.click();
        await expect(dialog(page).getByRole("button", { name: /^Withdraw — / }).first()).toBeVisible();
        await expectDialogFits(page, `Edit kit ${at}, the withdrawal question open`, true, false);
        await expectDialogInsideScreen(page, `Edit kit ${at}, the withdrawal question open`);
        // Three across where the body has 20.25rem for them — a 744 px phone
        // at 32 px has 21.25 — and one to a row where it has not: 390 and 320.
        const [grade, scale, body] = await Promise.all([
          dialog(page).getByLabel("Grade").boundingBox(),
          dialog(page).getByLabel("Scale").boundingBox(),
          (await scrollerOf(page))?.evaluate((element) => element.clientWidth - 2 * parseFloat(getComputedStyle(element).paddingLeft)),
        ]);
        const stacked = scale!.y > grade!.y + grade!.height - 1;
        expect.soft(stacked, `${at}: the three-across row folds by its box (${body} px)`).toBe((body ?? 0) < 20.25 * font);
        if (!stacked) expect.soft(grade!.width, `${at}: a field of the row has its room`).toBeGreaterThanOrEqual(FIELD_ROOM_REM * font);
        for (const name of ["Save", "Cancel"]) {
          // The bar's: with the withdrawal question open it has a Cancel too,
          // earlier in the form.
          const button = dialog(page).getByRole("button", { name, exact: true }).last();
          await expectUnderAFinger(button, `${at}: "${name}"`);
          expect.soft((await button.boundingBox())?.height, `${at}: "${name}" is a finger tall`).toBeGreaterThanOrEqual(FINGER);
          await expectLabelReads(button, `${at}: "${name}"`);
        }
        await restorePage(page);
        await page.keyboard.press("Escape");
        await openFromList(page, "/orders", "New order");
        // The form is gated on its queries (a cold cache in a browser of its
        // own): its loading state has no control to measure.
        await expect(dialog(page).getByRole("button", { name: "Add line" })).toBeVisible();
        await isolateSheet(page, size.width, `New order ${at}`);
        await expectDialogFits(page, `New order ${at}`, true, false);
        await expectDialogInsideScreen(page, `New order ${at}`);
        await expectUnderAFinger(dialog(page).getByRole("button", { name: "Record order", exact: true }), `${at}: "Record order"`);
        // The bar's labels read (finding 1): the secondary's column is a third
        // of the bar, and `Button`'s side padding in rem was all of it.
        for (const name of ["Record order", "Cancel"]) {
          await expectLabelReads(dialog(page).getByRole("button", { name, exact: true }).last(), `New order ${at}: "${name}"`);
        }
        await restorePage(page);

        // The picker's other states (finding 3 — the same on `main`, and the
        // third review in which the picker came back: the invariant is every
        // state's, not the chosen name's). Results: a long unbroken name
        // beside what is on hand. The offer to create: the query is free text.
        // The new item: the way back, whole and inside its row.
        await dialog(page).locator('select:has(option[value="upgrade"])').first().selectOption("upgrade");
        await dialog(page).getByPlaceholder(/Search upgrades/).fill(NAMES.unbroken.slice(0, TAG.length + 8));
        const result = dialog(page).locator("div.absolute button").filter({ hasText: NAMES.unbroken });
        await expect(result).toBeVisible();
        await isolateSheet(page, size.width, `the results ${at}`);
        const pieces = await result.evaluate((row) => {
          const bounds = row.getBoundingClientRect();
          return [...row.querySelectorAll("span")]
            .filter((span) => span.getBoundingClientRect().right > bounds.right + 0.5 || span.getBoundingClientRect().left < bounds.left - 0.5)
            .map((span) => (span.textContent ?? "").slice(0, 24));
        });
        expect.soft(pieces, `${at}: pieces of a result outside its row`).toEqual([]);
        await expect.soft(result.getByText(/on hand/), `${at}: what is on hand`).toBeVisible();
        await expectItsRoom(result.getByText(/on hand/), `${at}: what is on hand`);
        // The name's room is what it is promised — 8rem, or the row's width —
        // not its one-line width: ninety-two unbroken characters have none.
        const named = await result.locator("> span").first().evaluate((element) => {
          const row = element.parentElement as HTMLElement;
          const style = getComputedStyle(row);
          const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
          return { width: element.getBoundingClientRect().width, promised: Math.min(8 * rem, row.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)) };
        });
        expect.soft(named.width, `${at}: a result's name has its room`).toBeGreaterThanOrEqual(named.promised - 1);
        await expectDialogInsideScreen(page, `the results ${at}`);
        await restorePage(page);
        const token = "SEARCHEDFORAPARTNUMBERRUNTOGETHER1234567890";
        await dialog(page).getByPlaceholder(/Search upgrades/).fill(token);
        const create = dialog(page).getByRole("button", { name: /^Create new upgrade/ });
        await expect(create).toBeVisible();
        await isolateSheet(page, size.width, `the offer to create ${at}`);
        await expectLabelReads(create, `${at}: the offer to create`, 99); // a 43-character token: its lines say nothing, its ink does
        await expectDialogInsideScreen(page, `the offer to create ${at}`);
        await restorePage(page);
        await create.click();
        const back = dialog(page).getByRole("button", { name: /back to search/ });
        await isolateSheet(page, size.width, `a new item ${at}`);
        await expectLabelReads(back, `${at}: back to search`);
        await expectItsRoom(back, `${at}: back to search`);
        await expectDialogFits(page, `New order, a new upgrade, ${at}`, true, false);
        await expectDialogInsideScreen(page, `New order, a new upgrade, ${at}`);
        const row = await back.evaluate((element) => {
          const bounds = (element.parentElement as HTMLElement).getBoundingClientRect();
          const rect = element.getBoundingClientRect();
          return { left: rect.left, right: rect.right, rowLeft: bounds.left, rowRight: bounds.right };
        });
        expect.soft(row.left, `${at}: back to search starts in its row`).toBeGreaterThanOrEqual(row.rowLeft - 0.5);
        expect.soft(row.right, `${at}: back to search ends in its row`).toBeLessThanOrEqual(row.rowRight + 0.5);
        await restorePage(page);
        await back.click();
        await expect(dialog(page).getByPlaceholder(/Search upgrades/)).toBeVisible();
        await page.keyboard.press("Escape");

        // The filter sheet's bar is the same bar (finding 1: "Clear" was five
        // lines of a letter).
        await page.goto(`/kits?q=${q}`);
        await page.getByRole("button", { name: /^Filter and sort/ }).click();
        await expect(dialog(page)).toBeVisible();
        await isolateSheet(page, size.width, `the filter sheet ${at}`);
        for (const button of await dialog(page).locator("button").filter({ hasText: /^(Clear|Show)/ }).all()) {
          await expectLabelReads(button, `the filter sheet ${at}: "${(await button.textContent())?.trim()}"`);
        }
        await restorePage(page);
        await page.keyboard.press("Escape");
      }
      await context.close();
    } finally {
      await browser.close();
    }
  }
});

/** New order, its first line an upgrade, the unbroken-named one chosen: the
 *  picker's selected-item row — the name's chip, and Change beside it. */
async function chooseUnbroken(page: Page): Promise<{ chip: Locator; change: Locator }> {
  await openFromList(page, "/orders", "New order");
  await expect(dialog(page).getByRole("button", { name: "Add line" })).toBeVisible();
  await dialog(page).locator('select:has(option[value="upgrade"])').first().selectOption("upgrade");
  await dialog(page).getByPlaceholder(/Search upgrades/).fill(NAMES.unbroken.slice(0, TAG.length + 8));
  const result = dialog(page).locator("div.absolute button").filter({ hasText: NAMES.unbroken });
  await expect(result).toBeVisible();
  await result.click();
  const change = dialog(page).getByRole("button", { name: "Change", exact: true });
  await expect(change).toBeVisible();
  return { chip: dialog(page).getByText(NAMES.unbroken, { exact: true }), change };
}

/** The chip says the whole name inside its own box, and Change is a control of
 *  this sheet: inside it, and whole. */
async function expectChosenReads(page: Page, chip: Locator, change: Locator, label: string): Promise<void> {
  await expect.soft(chip, `${label}: the chosen name`).toBeVisible();
  const said = await chip.evaluate((element) => ({
    scroll: element.scrollWidth,
    client: element.clientWidth,
    left: element.getBoundingClientRect().left,
    right: element.getBoundingClientRect().right,
    screen: innerWidth,
  }));
  expect.soft(said.scroll, `${label}: the name is wider than its chip`).toBeLessThanOrEqual(said.client + 1);
  // Breaking is not reading: beside Change under a large font the chip could
  // shrink to a letter a line. It has the room a field has, or the row's.
  const room = await chip.evaluate((element, rem) => {
    const row = element.parentElement!.getBoundingClientRect().width;
    return Math.min(rem * parseFloat(getComputedStyle(document.documentElement).fontSize), row - 1);
  }, FIELD_ROOM_REM);
  expect.soft(said.right - said.left, `${label}: the chip's room`).toBeGreaterThanOrEqual(room);
  expect.soft(said.left, `${label}: the chip starts on screen`).toBeGreaterThanOrEqual(0);
  expect.soft(said.right, `${label}: the chip ends on screen`).toBeLessThanOrEqual(said.screen + 0.5);
  const box = (await change.boundingBox())!;
  expect.soft(box.x, `${label}: Change starts on screen`).toBeGreaterThanOrEqual(0);
  expect.soft(box.x + box.width, `${label}: Change ends on screen`).toBeLessThanOrEqual(said.screen + 0.5);
}

test("a chosen catalog item with a long unbroken name keeps Change in the dialog (#273)", async ({ page }, testInfo) => {
  // Codex #272 round 2, finding 5 — older than that PR: the chip could neither
  // shrink nor break, so at 320 px a 46-character name put Change at 447–525
  // and the sheet's body scrolled sideways, the one control that undoes the
  // choice off-screen. The name gives way now; Change does not.
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      const { chip, change } = await chooseUnbroken(page);
      const at = `at ${size.width} px`;
      await expectChosenReads(page, chip, change, at);
      await expectDialogFits(page, `New order, the unbroken name chosen, ${at}`, isPhone(size));
      const [name, button] = await Promise.all([chip.boundingBox(), change.boundingBox()]);
      if (!isPhone(size)) {
        // The desktop's row where it fits: Change beside the name, on its
        // line — a row that wrapped at every width would have sent it under
        // (#272's lesson, which a short name cannot show).
        expect.soft(button!.x, `${at}: Change is beside the name`).toBeGreaterThanOrEqual(name!.x + name!.width - 0.5);
        expect.soft(button!.y, `${at}: Change is on the name's row`).toBeLessThan(name!.y + name!.height);
      }
      // And it still undoes the choice.
      await change.click();
      await expect(dialog(page).getByPlaceholder(/Search upgrades/)).toBeVisible();
      await page.keyboard.press("Escape");
    });
  }
});

test("the chosen name and Change fit a phone under the browser's own font-size preference (#273)", async ({ browserName }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the sheet is the phone shell's");
  test.skip(browserName !== "chromium", "the preference is Chromium's launch flag");
  test.setTimeout(120_000);
  for (const font of [32, 40]) {
    const browser = await chromium.launch({ args: [`--blink-settings=defaultFontSize=${font}`] });
    try {
      const context = await browser.newContext({ storageState: STORAGE_STATE, hasTouch: true, isMobile: true, baseURL: APP });
      const page = await context.newPage();
      page.on("dialog", (native) => native.accept());
      for (const size of sizesFor("phone").filter(isPhone)) {
        await page.setViewportSize(size);
        const at = `at ${size.width} px, ${font} px font`;
        const { chip, change } = await chooseUnbroken(page);
        expect(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)), "the root font size").toBe(font);
        await isolateSheet(page, size.width, `New order ${at}`);
        await expectChosenReads(page, chip, change, at);
        await expectDialogFits(page, `New order, the unbroken name chosen, ${at}`, true, false);
        await expectDialogInsideScreen(page, `New order, the unbroken name chosen, ${at}`);
        expect.soft((await change.boundingBox())!.height, `${at}: Change is a finger tall`).toBeGreaterThanOrEqual(40);
        await restorePage(page);
        await page.keyboard.press("Escape");
      }
      await context.close();
    } finally {
      await browser.close();
    }
  }
});

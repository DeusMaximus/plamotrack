/** #260 (design §13.7): the pages the first three PRs of M6.6 did not own —
 *  Settings, Home, the sign-in screens — in the three shells.
 *
 *  - **Settings** is two shapes. On a phone the section list is a screen of
 *    its own (`/settings`, reached from More), a section opens from it, and the
 *    bar's chevron is the way back; from 768 px the list is a pane beside the
 *    section and `/settings` lands on General. One `<nav>` dressed two ways, so
 *    a turn keeps the page, a half-edited form and the keyboard.
 *  - **Data management on a phone imports too** (#304, the owner's call):
 *    Merge and Add only, never Replace everything; a button for the picker; the
 *    preview's rows the page's to scroll; Apply and Cancel in a bar held on the
 *    tab bar; the starter sheet after the import, the full template pack not
 *    rendered. From 768 px the section is as it was, and an import begun there
 *    survives a turn through the phone shell — unless it replaces everything.
 *  - **Home on a phone**: a Recently completed row is always two lines — the
 *    name, then the stars and the date — with the pencil beside both, by the
 *    strip's own box (one line again at 744 px, where it has the room); the mail
 *    is three stacked groups; every edit control and *view all* link is a
 *    finger tall.
 *  - **The sign-in, setup and OIDC screens** fit a phone, with the room an
 *    on-screen keyboard leaves too. The session is mocked for these — the
 *    suite's instance is claimed and in local mode, and a layout needs neither
 *    — so they prove the frame; the real sign-in is phone.spec.ts's.
 *  - **The browser's own font-size preference** (#269, and the class of
 *    #270/#271/#273): no page of the phone shell is wider than the screen at
 *    32 and 40 px, the head's action and the tab bar are inside it.
 *
 *  Every row this spec reads is its own and is deleted afterwards; a token is
 *  revoked (its row stays, as a record — that is the product).
 */
import { chromium, expect, test, type Locator, type Page } from "@playwright/test";

import { APP, OWNER_PASSWORD, STORAGE_STATE, apiContext } from "./api";
import { holdShellEvents, installShellEventHold, releaseShellEvents } from "./shellEvents";

type Size = { width: number; height: number };

const VIEWPORTS: Record<string, Size[]> = {
  app: [{ width: 1280, height: 720 }],
  // Both ends of the phone shell, and the narrowest phone there is.
  phone: [
    { width: 390, height: 844 },
    { width: 320, height: 568 },
    { width: 744, height: 1133 },
  ],
  tablet: [
    { width: 820, height: 1180 },
    { width: 1180, height: 820 },
  ],
};
const sizesFor = (project: string): Size[] => {
  const sizes = VIEWPORTS[project];
  if (!sizes) throw new Error(`pages.spec.ts has no viewports for the "${project}" project`);
  return sizes;
};
const isPhone = (size: Size) => size.width < 768;

const TAG = `E2E Pages ${Date.now().toString(36)}`;
const SHOP = `${TAG} Shop`;
const NAMES = {
  bench: `${TAG} Bench`,
  backlog: `${TAG} Backlog`,
  // Long enough that beside the stars and a date it was "a few letters".
  rated: `${TAG} Perfect Strike Freedom Gundam Rouge`,
  unrated: `${TAG} Unrated`,
  // One unbroken token, 42 characters: what a name pasted from a config is.
  token: `${TAG.replaceAll(" ", "_")}_claude_desktop_on_the_bench_laptop`,
};
const SECTIONS = ["General", "Language & region", "Data management", "Access tokens", "About"];

const kitIds: string[] = [];
const orderIds: string[] = [];
let retailerId: string | undefined;
let tokenId: string | undefined;

test.beforeAll(async () => {
  const api = await apiContext();
  const post = async (route: string, data: object) => {
    const resp = await api.post(route, { data });
    expect(resp.ok(), `${route}: ${await resp.text()}`).toBeTruthy();
    return (await resp.json()) as { id: string };
  };
  kitIds.push((await post("/kits", { name: NAMES.bench, grade: "MG", scale: "1/100", status: "building" })).id);
  kitIds.push((await post("/kits", { name: NAMES.backlog, grade: "HG", scale: "1/144", status: "backlog" })).id);
  // The rating's two states: stars, and the dash a kit nobody rated shows. Each
  // carries a completion date: a create never stamps one, and an undated build
  // prints no date and sorts after every dated one (#247), where the row's date
  // could not be measured and the strip of six might not hold it.
  const finished = new Date().toISOString();
  const rated = await post("/kits", {
    name: NAMES.rated,
    grade: "PG",
    scale: "1/60",
    status: "complete",
    build_completed_at: finished,
  });
  kitIds.push(rated.id);
  expect((await api.patch(`/kits/${rated.id}`, { data: { rating: 5 } })).ok()).toBeTruthy();
  kitIds.push(
    (await post("/kits", { name: NAMES.unrated, grade: "SD", status: "complete", build_completed_at: finished })).id,
  );

  retailerId = (await post("/retailers", { name: SHOP })).id;
  const line = (name: string, status?: string) => ({
    item_type: "kit",
    quantity: 1,
    unit_price_minor: 2800,
    currency_code: "JPY",
    kit: { name, grade: "HG", ...(status ? { status } : {}) },
  });
  // One order in each stage of the mail.
  for (const data of [
    { order_date: "2026-08-21", items: [line(`${TAG} Pre`, "pre_ordered")] },
    { order_date: "2026-08-30", items: [line(`${TAG} Ordered`)] },
    {
      order_date: "2026-09-01",
      shipped_at: "2026-09-04T10:00:00+00:00",
      delivery_service: "Australia Post",
      items: [line(`${TAG} Shipped`)],
    },
  ]) {
    orderIds.push((await post("/orders", { retailer_id: retailerId, currency_code: "JPY", ...data })).id);
  }
  tokenId = (await post("/auth/tokens", { name: NAMES.token, scopes: ["collection:read"] })).id;
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  for (const id of orderIds) await api.delete(`/orders/${id}`);
  for (const id of kitIds) await api.delete(`/kits/${id}`);
  if (retailerId) await api.delete(`/retailers/${retailerId}`);
  if (tokenId) await api.delete(`/auth/tokens/${tokenId}`);
  await api.dispose();
});

const rect = async (locator: Locator) => {
  const bounds = await locator.boundingBox();
  if (!bounds) throw new Error("no bounding box: the element is not rendered");
  return { ...bounds, right: bounds.x + bounds.width, bottom: bounds.y + bounds.height };
};

async function expectNoSidewaysScroll(page: Page, label: string): Promise<void> {
  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect.soft(widths.scroll, `${label}: the document's width`).toBeLessThanOrEqual(widths.client);
}

/** What has the keyboard, as a person would name it. */
const focused = (page: Page): Promise<string> =>
  page.evaluate(() => {
    const active = document.activeElement;
    if (!active || active === document.body) return "<body>";
    // A segment of the phone's import mode is a radio inside its label.
    if (active instanceof HTMLInputElement && active.labels?.length) return active.labels[0].textContent?.trim() ?? "";
    return active.getAttribute("aria-label") ?? active.textContent?.trim() ?? active.tagName;
  });

/** Whether the keyboard is on an alert or the box that holds one — and not on
 *  `<body>`, which holds every alert on the page: asked as "does the focused
 *  element contain an alert", a lost keyboard answered yes (#314, round 4). */
const keyboardOnRefusal = (page: Page): Promise<boolean> =>
  page.evaluate(() => {
    const active = document.activeElement;
    if (!active || active === document.body) return false;
    return active.getAttribute("role") === "alert" || active.querySelector('[role="alert"]') !== null;
  });

/** A date as en-AU writes it in digits — "19/09/2026" in Chromium, "19/9/2026"
 *  in WebKit, whose ICU pads nothing. */
const A_DATE = /^\d{1,2}\/\d{1,2}\/\d{4}$/;

const sectionNav = (page: Page): Locator => page.getByRole("navigation", { name: "Settings" });
const wayBack = (page: Page): Locator => page.getByRole("link", { name: "All settings" });

// ---------------------------------------------------------------- Settings

test("Settings on a phone is a list of sections, and a section opens from it", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the section list as a screen is the phone shell's");
  for (const size of sizesFor("phone")) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      // The way a phone gets there.
      await page.goto("/more");
      await page.getByRole("main").getByRole("link", { name: "Settings", exact: true }).click();
      await expect(page).toHaveURL(/\/settings$/);
      await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
      const links = sectionNav(page).getByRole("link");
      await expect(links).toHaveText(SECTIONS);
      // The list is the screen: no section is open under it, and there is
      // nowhere to go back to.
      await expect(page.getByRole("heading", { level: 2 })).toHaveCount(0);
      await expect(wayBack(page)).toHaveCount(0);
      for (const link of await links.all()) {
        const box = await rect(link);
        expect.soft(box.height, `${await link.textContent()}: a finger tall`).toBeGreaterThanOrEqual(44);
        expect.soft(box.x, "inside the screen").toBeGreaterThanOrEqual(0);
        expect.soft(box.right, "inside the screen").toBeLessThanOrEqual(size.width);
      }
      await expectNoSidewaysScroll(page, "/settings");

      for (const name of SECTIONS) {
        await sectionNav(page).getByRole("link", { name, exact: true }).click();
        await expect(page.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
        // The section has the screen: the list is not drawn beside or above it.
        await expect(sectionNav(page)).toBeHidden();
        const back = wayBack(page);
        const box = await rect(back);
        expect.soft(box.width, `${name}: the way back is a finger wide`).toBeGreaterThanOrEqual(44);
        expect.soft(box.height, `${name}: the way back is a finger tall`).toBeGreaterThanOrEqual(44);
        expect.soft(box.x, `${name}: the way back is on screen`).toBeGreaterThanOrEqual(0);
        await expectNoSidewaysScroll(page, name);
        if (size.width <= 390) {
          // One column: a field ends where its card's content does, unless
          // another field is beside it on its row (Date style | Hour cycle).
          // Not a radio: the import mode's are segments, the input inside each
          // drawn by its label (#304), and their labels share the row.
          const short = await page.getByRole("main").evaluate((main) => {
            const fields = [...main.querySelectorAll<HTMLElement>("input:not([type=file]):not([type=checkbox]):not([type=radio]), select")].filter(
              (field) => field.getClientRects().length > 0,
            );
            return fields
              .filter((field) => {
                const rect = field.getBoundingClientRect();
                const card = field.closest("section");
                if (!card) return false;
                const style = getComputedStyle(card);
                const inner = card.getBoundingClientRect().right - parseFloat(style.paddingRight) - parseFloat(style.borderRightWidth);
                const beside = fields.some((other) => {
                  const o = other.getBoundingClientRect();
                  return other !== field && Math.abs(o.top - rect.top) < rect.height / 2 && o.left > rect.right - 1;
                });
                return !beside && rect.right < inner - 1;
              })
              .map((field) => field.closest("label")?.textContent?.trim().slice(0, 24) ?? field.tagName);
          });
          expect.soft(short, `${name}: fields that stop short of their card`).toEqual([]);
        }
        await back.click();
        await expect(page).toHaveURL(/\/settings$/);
        await expect(sectionNav(page)).toBeVisible();
      }
    });
  }
});

test("from 768 px Settings is two panes, and /settings lands on General", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "the phone's shape is the test above");
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      await page.goto("/settings");
      await expect(page).toHaveURL(/\/settings\/general$/);
      const heading = page.getByRole("heading", { level: 2, name: "General" });
      await expect(heading).toBeVisible();
      await expect(sectionNav(page).getByRole("link")).toHaveText(SECTIONS);
      await expect(wayBack(page)).toHaveCount(0);
      // Beside, not above: the pane's links end where the section begins.
      expect((await rect(sectionNav(page))).right).toBeLessThanOrEqual((await rect(heading)).x);
      await expect(sectionNav(page).getByRole("link", { name: "General" })).toHaveAttribute("aria-current", "page");
    });
  }
});

test("a turn keeps Settings' page, its half-edited form and the keyboard", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "one project is enough: the test sets both sides of the line itself");
  const wide = { width: 820, height: 1180 };
  const narrow = { width: 744, height: 1133 }; // an iPad mini, turned
  await page.setViewportSize(wide);
  await page.goto("/settings/language");
  const zone = page.getByLabel("Time zone");
  await expect(zone).toBeVisible();
  const draft = "Australia/Perth";
  await zone.fill(draft); // never saved: the singleton is not this spec's to move

  // Wide to phone: the section's link is no longer drawn; the chevron stands in.
  const link = sectionNav(page).getByRole("link", { name: "Language & region" });
  await link.focus();
  await page.setViewportSize(narrow);
  await expect(wayBack(page)).toBeVisible();
  await expect.poll(() => focused(page), { message: "wide → phone" }).toBe("All settings");
  await expect(zone, "the form was not remounted").toHaveValue(draft);

  // And back: the chevron is gone; the open section's link has the keyboard.
  await page.setViewportSize(wide);
  await expect(link).toBeVisible();
  await expect.poll(() => focused(page), { message: "phone → wide" }).toBe("Language & region");
  await expect(zone).toHaveValue(draft);

  // The list screen, turned: General opens beside the very link that was
  // focused — the same node, so there is nothing to hand over.
  await page.setViewportSize(narrow);
  await page.goto("/settings");
  await sectionNav(page).getByRole("link", { name: "About" }).focus();
  await page.setViewportSize(wide);
  await expect(page).toHaveURL(/\/settings\/general$/);
  await expect.poll(() => focused(page), { message: "the list, turned" }).toBe("About");
});

// ---------------------------------------------------------- Data management

const EXPORTS = [
  "Download full archive (.zip)",
  "Kits .csv",
  "Orders .csv",
  "Order lines .csv",
  "Tools .csv",
  "Consumables .csv",
  "Upgrades .csv",
  "Display items .csv",
  "Retailers .csv",
  "Instance settings .csv",
];
/** Retailer rows as the importer reads them — the table off the file's name.
 *  Named per call, so a preview here never matches a row another test made. */
const retailerCsv = (...names: string[]) => ({
  name: "retailers.csv",
  mimeType: "text/csv",
  buffer: Buffer.from(`name\n${names.join("\n")}\n`),
});

test("Data management on a phone: the exports, an import with Merge and Add only, then the starter sheet; from 768 px it is complete", async ({
  page,
}, testInfo) => {
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      // The old route too: a bookmark opened on a phone lands on the section, not a 404.
      await page.goto(size.width === 390 ? "/data" : "/settings/data");
      await expect(page).toHaveURL(/\/settings\/data$/);
      await expect(page.getByRole("heading", { level: 2, name: "Data management" })).toBeVisible();
      const main = page.getByRole("main");
      for (const name of EXPORTS) {
        await expect.soft(main.getByRole("button", { name, exact: true }), name).toBeVisible();
      }
      const importHeading = main.getByRole("heading", { name: "Import", exact: true });
      const templatesHeading = main.getByRole("heading", { name: "Blank templates" });
      await expect(importHeading).toBeVisible();
      await expect(templatesHeading).toBeVisible();
      await expect(main.locator('input[type="file"]')).toHaveCount(1);
      await expect(main.getByRole("button", { name: "Preview changes" })).toBeDisabled();
      await expect(main.getByRole("button", { name: "Starter sheet (.csv)" })).toBeVisible();
      if (isPhone(size)) {
        // `replace_all` is not on a phone in any form: two segments, no select.
        const modes = main.getByRole("group", { name: "If something already exists" }).getByRole("radio");
        await expect(modes).toHaveCount(2);
        await expect(main.getByRole("radio", { name: "Merge" })).toBeChecked();
        await expect(main.getByRole("radio", { name: "Add only" })).not.toBeChecked();
        await expect(main.getByRole("radio", { name: "Replace everything" })).toHaveCount(0);
        await expect(main.getByRole("combobox")).toHaveCount(0);
        await expect(main.getByText("Drop a .csv or .zip here")).toHaveCount(0);
        const choose = main.getByRole("button", { name: "Choose a file" });
        await expect(choose).toBeVisible();
        // The full pack is the wider shapes'; the starter sheet comes after the import.
        await expect(main.getByRole("button", { name: "Full template pack (.zip)" })).toHaveCount(0);
        expect((await rect(templatesHeading)).y, "the starter sheet is under the import").toBeGreaterThan((await rect(importHeading)).y);
        for (const control of [choose, main.getByRole("button", { name: "Preview changes" })]) {
          expect.soft((await rect(control)).height, "a finger tall").toBeGreaterThanOrEqual(40);
        }
        for (const segment of await main.getByRole("group", { name: "If something already exists" }).locator("label").all()) {
          expect.soft((await rect(segment)).height, "a mode segment is a finger tall").toBeGreaterThanOrEqual(44);
        }
        await expectNoSidewaysScroll(page, "/settings/data");
      } else {
        await expect(main.getByText("Drop a .csv or .zip here")).toBeVisible();
        await expect(main.getByRole("button", { name: "Full template pack (.zip)" })).toBeVisible();
        // The select still offers all three.
        await expect(main.getByRole("combobox").locator("option")).toHaveText(["Merge", "Add only", "Replace everything"]);
        expect((await rect(templatesHeading)).y, "the templates are above the import").toBeLessThan((await rect(importHeading)).y);
      }
    });
  }
});

test("the archive downloads from a phone", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the desktop's exports are settings.spec.ts's and the README's");
  await page.setViewportSize(sizesFor("phone")[0]);
  await page.goto("/settings/data");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download full archive (.zip)" }).click();
  // The server names it, with the day (`Content-Disposition`).
  expect((await download).suggestedFilename()).toMatch(/^plamotrack-export.*\.zip$/);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("an import on a phone (#304): a CSV previewed and applied, Add only; an archive previewed and cancelled", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the phone shell's own shape; the wider ones are settings.spec.ts's");
  const shop = `${TAG} Phone Import`;
  const api = await apiContext();
  try {
    for (const size of sizesFor("phone").filter((s) => s.width < 744)) {
      await test.step(`${size.width} × ${size.height}`, async () => {
        await page.setViewportSize(size);
        await page.goto("/settings/data");
        const main = page.getByRole("main");
        // A file the importer refuses says so in the Import card, on screen
        // beside Preview — not at the head of the section, a screen above.
        await main.locator('input[type="file"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not a sheet\n") });
        // By the keyboard: Preview disables itself while it reads, and the
        // refusal that comes back takes the keyboard (Codex round 4: already so
        // on `main`, folded in with the same mechanism).
        await main.getByRole("button", { name: "Preview changes" }).focus();
        await page.keyboard.press("Enter");
        const refused = main.locator("section").filter({ has: page.getByRole("heading", { name: "Import", exact: true }) }).getByRole("alert");
        await expect(refused).toHaveText("Import a .csv or a .zip archive.");
        await expect(refused).toBeInViewport();
        await expect(main.getByRole("alert")).toHaveCount(1);
        await expect
          .poll(() => keyboardOnRefusal(page), {
            message: "a refused preview hands the keyboard to the refusal",
          })
          .toBe(true);
        // Thirty rows: a preview longer than the screen, which is what the bar is for.
        const names = Array.from({ length: 30 }, (_, i) => `${shop} ${size.width} ${String(i + 1).padStart(2, "0")}`);
        const name = names[0];
        await main.locator('input[type="file"]').setInputFiles(retailerCsv(...names));
        // The file row replaces the picker's button, and Change opens the picker again.
        await expect(main.getByText("retailers.csv", { exact: true })).toBeVisible();
        await expect(main.getByRole("button", { name: "Choose a file" })).toHaveCount(0);
        // Change empties the input before the picker opens, or picking the same
        // file again fires no `change` (#314 review, Codex P2) — and a pick that
        // brings no file, a cancel, keeps the file already chosen.
        const input = main.locator('input[type="file"]');
        let chooser = page.waitForEvent("filechooser");
        await main.getByRole("button", { name: "Change", exact: true }).click();
        await chooser;
        expect(await input.evaluate((element: HTMLInputElement) => element.value), "emptied before the picker opens").toBe("");
        await input.dispatchEvent("change");
        await expect(main.getByText("retailers.csv", { exact: true }), "a cancel keeps the file").toBeVisible();
        chooser = page.waitForEvent("filechooser");
        await main.getByRole("button", { name: "Change", exact: true }).click();
        await (await chooser).setFiles(retailerCsv(...names));

        await main.getByText("Add only", { exact: true }).click();
        await expect(main.getByRole("radio", { name: "Add only" })).toBeChecked();
        await expect(main.getByText("Add what's new and leave everything you already have untouched.")).toBeVisible();
        // By the keyboard again: a plan gives it back to Preview.
        await main.getByRole("button", { name: "Preview changes" }).focus();
        await page.keyboard.press("Enter");

        const section = main.getByRole("button", { name: /^Retailers \d/ });
        await expect(section).toHaveAttribute("aria-expanded", "true");
        await expect.poll(() => focused(page), { message: "a plan gives the keyboard back to Preview" }).toBe("Preview changes");
        // A new file takes the refusal away.
        await expect(main.getByRole("alert")).toHaveCount(0);
        // The row number is under the label, not a column of its own, and the
        // rows are the page's to scroll — no scroller inside it.
        const row = main.getByRole("row").filter({ hasText: name });
        await expect(row.getByText("row 2", { exact: true }), "the sheet's line, its header line 1").toBeVisible();
        await expect(row.locator("td").first(), "the number column").toBeHidden();
        const scroller = await section.evaluate((button) => getComputedStyle(button.nextElementSibling!).overflowY);
        expect(scroller, "a section's rows do not scroll on their own").toBe("visible");

        // Apply and Cancel are a bar, held on the tab bar while the import is on screen…
        const apply = page.getByRole("button", { name: "Apply import" });
        const cancel = page.getByRole("button", { name: "Cancel" });
        await expect(apply).toHaveCount(1);
        await main.getByRole("heading", { name: "Import", exact: true }).evaluate((heading) => heading.scrollIntoView({ block: "start" }));
        const tabBar = await rect(page.getByRole("navigation", { name: "Main" }));
        const [applyBox, cancelBox] = await Promise.all([rect(apply), rect(cancel)]);
        expect.soft(applyBox.bottom, "the bar ends on the tab bar").toBeLessThanOrEqual(tabBar.y + 0.5);
        expect.soft(applyBox.bottom, "the bar ends on the tab bar").toBeGreaterThanOrEqual(tabBar.y - 16);
        expect.soft(applyBox.height, "Apply is a bar button").toBeGreaterThanOrEqual(48);
        expect.soft(cancelBox.right, "Cancel first, as a dialog's bar has it").toBeLessThanOrEqual(applyBox.x);
        expect.soft(applyBox.width, "Apply has two shares").toBeGreaterThan(cancelBox.width);
        await expectNoSidewaysScroll(page, `the preview at ${size.width} px`);
        // …and at rest under the card, above the starter sheet, at the page's end.
        await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
        const [resting, starter] = await Promise.all([rect(apply), rect(main.getByRole("heading", { name: "Blank templates" }))]);
        expect.soft(resting.bottom, "at rest, the bar is above the starter sheet").toBeLessThan(starter.y);
        expect.soft(resting.bottom, "at rest, clear of the tab bar").toBeLessThanOrEqual(tabBar.y + 0.5);

        // An Apply already sent is the import's, not the draft's: it says what it
        // is doing, by mode, until it answers, and the mode cannot be changed
        // under it (#314 round 2, Codex finding 5). Held at the network so the
        // pending state is there to be read.
        let releaseApply = () => {};
        const applyHeld = new Promise<void>((resolve) => (releaseApply = resolve));
        await page.route("**/import/apply", async (route) => {
          await applyHeld;
          await route.continue();
        });
        // By the keyboard, from the bar, with the long preview scrolled to its
        // top: the pending import takes the keyboard and is brought into view,
        // clear of the sticky head and the bar (Codex round 4, finding 10).
        await main.getByRole("heading", { name: "Import", exact: true }).evaluate((heading) => heading.scrollIntoView({ block: "start" }));
        await apply.focus();
        await page.keyboard.press("Enter");
        const status = main.getByText("Importing — Add only…");
        await expect(status, "the sent import says what it is").toBeVisible();
        await expect.poll(() => focused(page), { message: "the pending import has the keyboard" }).toBe("Importing — Add only…");
        const [statusBox, barButton, head] = await Promise.all([
          rect(status),
          rect(page.getByRole("button", { name: "Importing…" })),
          rect(page.locator("header").first()),
        ]);
        expect.soft(statusBox.y, "the pending import is below the sticky head").toBeGreaterThanOrEqual(head.bottom - 0.5);
        expect.soft(statusBox.bottom, "and above the bar").toBeLessThanOrEqual(barButton.y + 0.5);
        await expect(page.getByRole("button", { name: "Importing…" })).toBeVisible();
        await expect(main.getByRole("radio", { name: "Merge" }), "the mode cannot change under it").toBeDisabled();
        await expect(main.getByRole("button", { name: "Change", exact: true })).toBeDisabled();
        // The sent phase ends on the API's answer; the data refresh that follows
        // is not part of it (Codex round 3, finding 9). With that refresh held,
        // the result is there, nothing still says "Importing…", the next file
        // can be chosen — and the keyboard is on the outcome, not <body>.
        let releaseRefresh = () => {};
        const refreshHeld = new Promise<void>((resolve) => (releaseRefresh = resolve));
        let refreshAsked = false;
        await page.route("**/api/settings", async (route) => {
          if (route.request().method() === "GET") {
            refreshAsked = true;
            await refreshHeld;
          }
          await route.continue();
        });
        releaseApply();
        await expect(main.getByText("Import complete")).toBeVisible();
        await expect.poll(() => refreshAsked, { message: "the refresh is under way" }).toBe(true);
        await expect(main.getByText("Importing — Add only…"), "the sent phase ended with the answer").toHaveCount(0);
        await expect(main.getByRole("button", { name: "Choose a file" }), "the next file can be chosen").toBeEnabled();
        await expect.poll(() => focused(page), { message: "the keyboard is on the outcome" }).toMatch(/^Import complete/);
        releaseRefresh();
        await page.unroute("**/api/settings");
        await page.unroute("**/import/apply");
        await expect(apply).toHaveCount(0);
        await expect(main.getByRole("button", { name: "Choose a file" })).toBeVisible();
        const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
        const made = retailers.filter((retailer) => names.includes(retailer.name));
        expect(made, "the import wrote the rows").toHaveLength(names.length);
        for (const retailer of made) expect((await api.delete(`/retailers/${retailer.id}`)).ok()).toBeTruthy();
      });
    }

    // A whole archive, the move plamotrack-ios makes: this instance's own
    // export, read back as no change at all. Previewed, then cancelled —
    // nothing is written.
    await page.setViewportSize(sizesFor("phone")[0]);
    await page.goto("/settings/data");
    const archive = await api.get("/export/archive");
    expect(archive.ok()).toBeTruthy();
    const main = page.getByRole("main");
    await main.locator('input[type="file"]').setInputFiles({ name: "plamotrack-export.zip", mimeType: "application/zip", buffer: await archive.body() });
    await main.getByRole("button", { name: "Preview changes" }).click();
    await expect(main.getByText(/^Read as a full archive/)).toBeVisible();
    await expect(main.getByText(/^0 new/)).toBeVisible();
    // The badge's column is the badge's width, the label beside it — asked of
    // a short label, which is where the table handed the spare width to the
    // badge's column (seen in the simulator; long names take it all).
    // Measured from the badge to the label *cell's* edge, so the allowance is
    // rounding, not the cell's padding — the first version allowed 12.5 px,
    // which the mutant that removes `w-px` alone fitted inside (Codex, round 2,
    // finding 6). At 390 px and at the phone shell's widest, 744, where the
    // spare width is largest; at 320 there is none to hand out.
    await main.getByRole("button", { name: /^Instance settings \d/ }).click();
    const settingsRow = main.getByRole("row").filter({ hasText: /row 2/ }).first();
    for (const width of [390, 744]) {
      await page.setViewportSize({ width, height: 844 });
      const [badge, label] = await Promise.all([rect(settingsRow.locator("td").nth(1).locator("span")), rect(settingsRow.locator("td").nth(2))]);
      expect.soft(label.x - badge.right, `at ${width} px, the badge's column is the badge`).toBeLessThanOrEqual(0.5);
    }
    await page.setViewportSize(sizesFor("phone")[0]);
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Apply import" })).toHaveCount(0);
    await expect(main.getByText("plamotrack-export.zip")).toHaveCount(0);
  } finally {
    const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
    for (const retailer of retailers.filter((r) => r.name.startsWith(shop))) await api.delete(`/retailers/${retailer.id}`);
    await api.dispose();
  }
});

test("an import begun on a tablet survives a turn through the phone shell, unless it replaces everything", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "one project is enough: the test sets both sides of the line itself");
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/settings/data");
  const file = "retailers.csv";
  await page.locator('input[type="file"]').setInputFiles(retailerCsv(`${TAG} Imported Shop`));
  await page.getByRole("button", { name: "Preview changes" }).click();
  const apply = page.getByRole("button", { name: "Apply import" });
  await expect(apply).toBeVisible();

  // The phone draws Apply in its bar: the keyboard goes to that one (#304).
  await apply.focus();
  await page.setViewportSize({ width: 744, height: 1133 });
  await expect(page.getByRole("radio", { name: "Merge" })).toBeChecked();
  await expect.poll(() => focused(page), { message: "Apply import had the keyboard" }).toBe("Apply import");
  await expect(page.getByText(file, { exact: true })).toBeVisible();

  await page.setViewportSize({ width: 820, height: 1180 });
  await expect(apply, "the preview is where it was left").toBeVisible();
  await expect.poll(() => focused(page), { message: "and back" }).toBe("Apply import");

  // Replacing everything is not a phone's: the turn takes the mode back to
  // Merge and the plan with it, and the keyboard to the mode.
  await page.getByRole("main").getByRole("combobox").selectOption("replace_all");
  await page.getByRole("button", { name: "Preview changes" }).click();
  await page.getByPlaceholder("REPLACE").fill("REPLACE"); // Apply is disabled until then, and takes no focus
  await expect(apply).toBeEnabled();
  await apply.focus();
  await page.setViewportSize({ width: 744, height: 1133 });
  await expect(page.getByRole("radio", { name: "Merge" })).toBeChecked();
  await expect(apply).toHaveCount(0);
  await expect(page.getByText(file, { exact: true }), "the file stays").toBeVisible();
  await expect.poll(() => focused(page), { message: "Apply import, replacing everything" }).toBe("Merge");
  await page.setViewportSize({ width: 820, height: 1180 });
  const mode = page.getByRole("main").getByRole("combobox");
  await expect(mode).toHaveValue("merge");

  // A preview still in flight when its plan is thrown away stays thrown away —
  // by the turn's fall-back, and by a mode changed on the tablet itself. Held
  // at the network, released after, and read once the page has heard it: the
  // Preview button is enabled again only after the answer is handled (#314
  // review: Greptile P1, Codex P2).
  const preview = page.getByRole("button", { name: "Preview changes" });
  for (const discard of ["the turn", "another mode"] as const) {
    await page.setViewportSize({ width: 820, height: 1180 });
    await mode.selectOption("replace_all");
    let release = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/import/preview", async (route) => {
      await held;
      await route.continue();
    });
    await preview.click();
    await expect(page.getByRole("button", { name: "Reading…" })).toBeVisible();
    if (discard === "the turn") {
      await page.setViewportSize({ width: 744, height: 1133 });
      await expect(page.getByRole("radio", { name: "Merge" })).toBeChecked();
    } else {
      await mode.selectOption("add_only");
    }
    const answered = page.waitForResponse("**/import/preview");
    release();
    await answered;
    await expect(preview, `${discard}: the answer is handled`).toBeEnabled();
    await expect(page.getByText(/^Read as/), `${discard}: no plan comes back`).toHaveCount(0);
    await expect(apply, `${discard}: nothing to apply`).toHaveCount(0);
    await page.unroute("**/import/preview");
  }

  // A refusal under Replace everything goes with the mode it was for.
  await page.setViewportSize({ width: 820, height: 1180 });
  await mode.selectOption("replace_all");
  await page.locator('input[type="file"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("x\n") });
  await preview.click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Import a .csv or a .zip archive.");
  await page.setViewportSize({ width: 744, height: 1133 });
  await expect(page.getByRole("radio", { name: "Merge" })).toBeChecked();
  await expect(page.getByRole("main").getByRole("alert"), "the refusal went with the mode").toHaveCount(0);
  await page.setViewportSize({ width: 820, height: 1180 });

  // An Apply already sent outlives the turn that throws its draft away: the
  // fall-back still takes the draft to Merge, but the page keeps saying that a
  // Replace everything is under way until it answers, in every shape (#314
  // round 2, Codex finding 5). Held, then **aborted** at the network — it
  // never reaches the server, so nothing is replaced — and the failure is said
  // in the Import card.
  await page.locator('input[type="file"]').setInputFiles(retailerCsv(`${TAG} Held Apply`));
  await mode.selectOption("replace_all");
  await preview.click();
  await page.getByPlaceholder("REPLACE").fill("REPLACE");
  let releaseApply = () => {};
  const applyHeld = new Promise<void>((resolve) => (releaseApply = resolve));
  await page.route("**/import/apply", async (route) => {
    await applyHeld;
    await route.abort();
  });
  // By the keyboard: sending it disables Apply, which takes the keyboard with
  // it unless something is given it — the pending import's status is (Codex
  // round 3, finding 8).
  await apply.focus();
  await page.keyboard.press("Enter");
  const pending = page.getByRole("main").getByText("Importing — Replace everything…");
  await expect(pending).toBeVisible();
  await expect.poll(() => focused(page), { message: "sending it hands the keyboard to the pending import" }).toBe("Importing — Replace everything…");
  await expect(mode, "the mode cannot change under it").toBeDisabled();
  // Codex's reproduction: the confirmation is still enabled, the turn removes
  // it, and the mode it named as its stand-in is disabled — the pending import
  // stands in after it.
  await page.getByPlaceholder("REPLACE").focus();
  await page.setViewportSize({ width: 744, height: 1133 });
  await expect(page.getByRole("radio", { name: "Merge" })).toBeChecked();
  await expect.poll(() => focused(page), { message: "the removed confirmation hands the keyboard to the pending import" }).toBe("Importing — Replace everything…");
  await expect(pending, "after the turn, still pending, under its own mode").toBeVisible();
  await expect(page.getByRole("button", { name: "Importing…" }), "and its bar").toBeVisible();
  await page.setViewportSize({ width: 820, height: 1180 });
  // The tablet's shape first — its select — or the phone's bar, still drawn
  // until the page hears of the turn, answers for the desktop's row.
  await expect(mode, "the tablet's shape again").toBeVisible();
  await expect(pending, "and turned back").toBeVisible();
  await expect(page.getByRole("button", { name: "Importing…" }), "with its actions, though its plan went with the draft").toBeVisible();
  releaseApply();
  await expect(page.getByRole("main").getByRole("alert"), "its failure is said in the card").toBeVisible();
  await expect(pending).toHaveCount(0);
  await expect
    .poll(() => keyboardOnRefusal(page), {
      message: "the keyboard goes from the pending import to its outcome",
    })
    .toBe(true);
  await page.unroute("**/import/apply");

  // An outcome holding the keyboard, replaced by the next file dropped onto the
  // drop zone, hands the keyboard to that file's Preview — a drop moves no
  // focus of its own (Codex round 4, finding 11). This one is applied, so it
  // cleans up after itself.
  const firstShop = `${TAG} Applied Before A Drop`;
  const api = await apiContext();
  try {
    await page.locator('input[type="file"]').setInputFiles(retailerCsv(firstShop));
    await mode.selectOption("add_only");
    await preview.click();
    await apply.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Import complete")).toBeVisible();
    await expect.poll(() => focused(page), { message: "the outcome has the keyboard" }).toMatch(/^Import complete/);
    const dataTransfer = await page.evaluateHandle((name) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([`name\n${name}\n`], "retailers.csv", { type: "text/csv" }));
      return transfer;
    }, `${TAG} Dropped Next`);
    await page.getByText("Drop a .csv or .zip here").dispatchEvent("drop", { dataTransfer });
    await expect(page.getByText("retailers.csv", { exact: true }), "the dropped file is the draft").toBeVisible();
    await expect(page.getByText("Import complete")).toHaveCount(0);
    await expect.poll(() => focused(page), { message: "the removed outcome hands the keyboard to the new draft" }).toBe("Preview changes");
  } finally {
    const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
    for (const retailer of retailers.filter((r) => r.name === firstShop)) await api.delete(`/retailers/${retailer.id}`);
    await api.dispose();
  }

  // The dropped file was never applied: nothing more to clean up.
  await page.getByText("choose a different file").click();

  // And every control the two shapes draw differently, or only one draws,
  // arriving both ways. **By the app's own link is the one that matters:** the
  // section then mounts, and subscribes to the shell's media queries, *after*
  // `Layout` has; the browser reports `Layout`'s change first; `Layout`
  // commits and runs its hand-over over a control that is still there; the
  // section removes it a commit later. With the stand-in alone that lost the
  // keyboard **eight times in eight, in both engines** — not a race at all for
  // someone who got here by tapping — and with `lib/focusKey.ts`'s recheck on
  // the next frame, none. Arriving by URL the two mount together and the order
  // is the browser's: four in eight, Chromium only. (The first version of this
  // test had only that way in, sixteen times over, and Codex measured what that
  // is worth: red in six runs of six in Chromium, two of six in WebKit — #274
  // round 2.)
  const controls = [
    ["the template pack", () => page.getByRole("button", { name: "Full template pack (.zip)" }), "Starter sheet (.csv)"],
    ["the starter sheet", () => page.getByRole("button", { name: "Starter sheet (.csv)" }), "Starter sheet (.csv)"],
    ["the import mode", () => page.getByRole("main").getByRole("combobox"), "Merge"],
    ["browse", () => page.getByRole("button", { name: "or browse for one" }), "Choose a file"],
    ["Preview changes", () => page.getByRole("button", { name: "Preview changes" }), "Preview changes"],
  ] as const;
  for (const arrive of ["by the app's link", "by URL"] as const) {
    for (const [name, control, lands] of controls) {
      const label = `${name}, arriving ${arrive}`;
      await page.setViewportSize({ width: 820, height: 1180 });
      if (arrive === "by URL") {
        await page.goto("/settings/data");
      } else {
        await page.goto("/settings/general");
        await sectionNav(page).getByRole("link", { name: "Data management" }).click();
      }
      await expect(page.getByRole("heading", { level: 2, name: "Data management" })).toBeVisible();
      if (name === "Preview changes") {
        await page.locator('input[type="file"]').setInputFiles({ name: file, mimeType: "text/csv", buffer: Buffer.from("name\nx\n") });
      }
      await control().focus();
      await expect.poll(() => focused(page), { message: `${label}: focused before the turn` }).not.toBe("<body>");
      await page.setViewportSize({ width: 744, height: 1133 });
      await expect(page.getByRole("radio", { name: "Merge" })).toBeVisible();
      await expect.poll(() => focused(page), { message: `${label}: after the turn` }).toBe(lands);
    }
  }
});

test("an import sent outlives leaving the section: back, it is still under way, then its outcome, once (#315)", async ({ page }, testInfo) => {
  // Every shape: the section is left by the shell's own navigation, and comes
  // back by the browser's Back or by the app's own links — a route change,
  // never a reload, or the tab would have nothing to remember. The two mount
  // it differently: a link's navigation renders in a transition, and an
  // outcome handed over only by the mount's effect was a commit late there,
  // where Back hid it (Codex, PR #332 round 1, the M3 mutant).
  const shop = `${TAG} Sent Then Left ${testInfo.project.name}`;
  const main = page.getByRole("main");
  /** Away to Kits — arrived, not just addressed: the router draws the next
   *  page in a transition, and a Back before it lands never left the section. */
  const leave = async () => {
    await page.getByRole("link", { name: "Kits", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Kits" })).toBeVisible();
    await expect(main.getByRole("heading", { name: "Import", exact: true }), "the section is gone").toHaveCount(0);
  };
  /** Two frames: the first has been painted, which is when the section lets
   *  the module forget the outcome it shows. */
  const painted = () => page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  /** Back by the app's links: Settings (on a phone, by More), then the section. */
  const enterByLinks = async () => {
    if (testInfo.project.name === "phone") await page.getByRole("link", { name: "More", exact: true }).click();
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await sectionNav(page).getByRole("link", { name: "Data management", exact: true }).click();
    await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
  };
  const pending = main.getByText("Importing — Add only…");
  const complete = main.getByText("Import complete");
  // The way to a file in each shape: the drop zone's link, the phone's button.
  const picker = main.getByRole("button", { name: /^(or browse for one|Choose a file)$/ });
  const api = await apiContext();
  const ours = async () =>
    ((await (await api.get("/retailers")).json()) as { id: string; name: string }[]).filter((r) => r.name === shop);

  /** A file previewed under Add only, and Apply sent with its request held at
   *  the network until `release` — then continued, or aborted. */
  async function sendHeld(then: "continue" | "abort") {
    await page.goto("/settings/data");
    await main.locator('input[type="file"]').setInputFiles(retailerCsv(shop));
    if (testInfo.project.name === "phone") await main.getByText("Add only", { exact: true }).click();
    else await main.getByRole("combobox").selectOption("add_only");
    await main.getByRole("button", { name: "Preview changes" }).click();
    const apply = page.getByRole("button", { name: "Apply import" });
    await expect(apply).toBeEnabled();
    let release = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/import/apply", async (route) => {
      await held;
      await (then === "continue" ? route.continue() : route.abort());
    });
    await apply.click();
    await expect(pending).toBeVisible();
    return release;
  }

  /** Whether the Import card's first drawing, after the next route change,
   *  already says `text` (or holds an alert) — read in a MutationObserver,
   *  which runs after React's commit and before its effects: an outcome handed
   *  over only by an effect is a frame late, an empty card painted first. */
  const firstDrawSays = async (text: string) => {
    await page.evaluate((expected) => {
      const probe = window as unknown as { __firstDraw?: boolean | null };
      probe.__firstDraw = null;
      new MutationObserver((_, observer) => {
        const main = document.querySelector("main");
        const headings = Array.from(main?.querySelectorAll("h1, h2, h3") ?? []);
        if (!headings.some((heading) => heading.textContent === "Import")) return;
        probe.__firstDraw =
          expected === "an alert" ? main!.querySelector('[role="alert"]') !== null : main!.textContent!.includes(expected);
        observer.disconnect();
      }).observe(document.body, { childList: true, subtree: true });
    }, text);
    return () => page.evaluate(() => (window as unknown as { __firstDraw?: boolean | null }).__firstDraw);
  };

  try {
    // Left while it is under way, and back before it answers: it is still
    // under way, by its mode, and there is no file to pick — nothing to send
    // a second time.
    const release = await sendHeld("continue");
    await leave();
    // With the keyboard nowhere, which is when the section would give it to
    // the import's status: it does at the moment of sending, not on arrival.
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.goBack();
    await expect(page).toHaveURL(/\/settings\/data$/);
    await expect(pending, "back while it runs: it says so").toBeVisible();
    await expect.poll(() => focused(page), { message: "arriving takes nobody's keyboard" }).toBe("<body>");
    await expect(picker, "and no file can be picked to send again").toBeDisabled();
    await expect(main.getByRole("button", { name: "Preview changes" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Importing…" }), "its actions, though its plan went with the draft").toBeDisabled();

    // A reload or a closed tab would lose it as well, and abort it besides:
    // while it is in flight, the page asks first. (The browser's own prompt
    // needs a gesture and a real unload; what decides it is this listener.)
    const asks = () =>
      page.evaluate(() => {
        const event = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(event);
        return event.defaultPrevented;
      });
    expect(await asks(), "in flight, leaving the page is asked about").toBe(true);

    // Left again, and it answers while nobody is looking.
    await leave();
    const answered = page.waitForResponse("**/import/apply");
    release();
    expect((await answered).ok()).toBeTruthy();
    await expect.poll(async () => (await ours()).length, { message: "the import wrote its row" }).toBe(1);
    expect(await asks(), "answered, the page lets go").toBe(false);
    const drawnWithResult = await firstDrawSays("Import complete");
    await enterByLinks();
    await expect(complete, "back after it answered: how it ended").toBeVisible();
    expect(await drawnWithResult(), "from the card's first frame").toBe(true);
    await expect(main.getByText(/^1 created/), "with what it did").toBeVisible();
    await expect(pending).toHaveCount(0);
    await expect(picker, "and the next file can be picked").toBeEnabled();
    await expect(page.getByRole("button", { name: "Apply import" }), "the draft is empty").toHaveCount(0);

    // Shown once: the visit after is a fresh one.
    await painted();
    await leave();
    await page.goBack();
    await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
    await expect(complete, "the outcome was seen, and is gone").toHaveCount(0);
    expect(await ours(), "one import, one row").toHaveLength(1);
    await page.unroute("**/import/apply");

    // A failure that came while it was away is said in the card on return.
    const refuse = await sendHeld("abort");
    await leave();
    const failed = page.waitForEvent("requestfailed", (request) => request.url().endsWith("/import/apply"));
    refuse();
    await failed;
    const drawnWithFailure = await firstDrawSays("an alert");
    await enterByLinks();
    const card = main.locator("section").filter({ has: page.getByRole("heading", { name: "Import", exact: true }) });
    await expect(card.getByRole("alert"), "back after it failed: the failure, in the card").toBeVisible();
    expect(await drawnWithFailure(), "from the card's first frame").toBe(true);
    await expect(pending).toHaveCount(0);
    await expect(picker).toBeEnabled();
    await page.unroute("**/import/apply");

    // Told is not shown (PR #332 review): an outcome the section was told of
    // but left before it acknowledged it — the answer landing as a navigation
    // tears it down, or committed under one that replaces it before the next
    // frame — is shown on the next visit. The acknowledgement waits on the
    // page's animation-frame callbacks, so here none is delivered while the
    // answer comes in place. (The browser still paints — the stub is the
    // callback API, not the compositor, Codex round 2 — so what this holds is
    // that acknowledging is deferred to the frames and cancelled by leaving.)
    const answerInPlace = await sendHeld("continue");
    await page.evaluate(() => {
      const w = window as unknown as { __raf: typeof requestAnimationFrame };
      w.__raf = window.requestAnimationFrame;
      window.requestAnimationFrame = () => 0;
    });
    const inPlace = page.waitForResponse("**/import/apply");
    answerInPlace();
    await inPlace;
    await expect(complete, "told in place").toBeVisible();
    await leave();
    await page.evaluate(() => {
      window.requestAnimationFrame = (window as unknown as { __raf: typeof requestAnimationFrame }).__raf;
    });
    await page.goBack();
    await expect(complete, "never acknowledged, so shown on the next visit").toBeVisible();
    await painted();
    await leave();
    await page.goBack();
    await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
    await expect(complete, "acknowledged this time, and gone").toHaveCount(0);
    await page.unroute("**/import/apply");
    expect(await ours(), "still one row: Add only skipped the shop it had").toHaveLength(1);
  } finally {
    for (const retailer of await ours()) await api.delete(`/retailers/${retailer.id}`);
    await api.dispose();
  }
});

test("a sign-out that fails keeps the import it sent: the session, and the import, go on (PR #332 review)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "a phone signs out from More, a page away from the section");
  const shop = `${TAG} Failed Sign Out ${testInfo.project.name}`;
  const main = page.getByRole("main");
  const api = await apiContext();
  try {
    await page.goto("/settings/data");
    await main.locator('input[type="file"]').setInputFiles(retailerCsv(shop));
    await main.getByRole("button", { name: "Preview changes" }).click();
    let release = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/import/apply", async (route) => {
      await held;
      await route.continue();
    });
    await page.getByRole("button", { name: "Apply import" }).click();
    await expect(main.getByText("Importing — Merge…")).toBeVisible();
    // The logout fails before the server ends anything; the session, re-read
    // for real, still says the owner.
    await page.route("**/auth/logout", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "logout failed" }) }),
    );
    const session = page.waitForResponse("**/auth/session");
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    expect(((await (await session).json()) as { state: string }).state, "still signed in").toBe("owner");
    await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
    const answered = page.waitForResponse("**/import/apply");
    release();
    expect((await answered).ok(), "the import committed").toBeTruthy();
    await expect(main.getByText("Import complete"), "and the page says so").toBeVisible();
    await expect(main.getByText("Importing — Merge…")).toHaveCount(0);
    await page.unroute("**/import/apply");
    await page.unroute("**/auth/logout");
  } finally {
    const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
    for (const retailer of retailers.filter((r) => r.name === shop)) await api.delete(`/retailers/${retailer.id}`);
    await api.dispose();
  }
});

/** An import's answer as the API words it, for a request held and then
 *  answered by the test instead of the server — so Replace everything is
 *  never run against the suite's database. */
const importAnswer = (mode: string, created = 1) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify({
    mode,
    source: "retailers.csv",
    created,
    updated: 0,
    skipped: 0,
    kits_spawned: 0,
    kits_removed: 0,
    kits_advanced: 0,
    rows_deleted: {},
    warnings: [],
  }),
});

test("an answer that lands in the turn to a phone is drawn there, then forgotten (PR #332 round 2)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "one project is enough: the test sets both sides of the line itself");
  // Codex's reproduction: Replace everything sent at 820 px; the screen turns
  // to a phone, and the answer comes before the page hears of the turn, so
  // the render that takes the answer is also the one that falls back from
  // `replace_all`. The fall-back is the draft's; the outcome is the
  // import's, and is drawn. Kept as three states, the fall-back cleared the
  // drawn result while the acknowledged copy forgot it unseen.
  await page.setViewportSize({ width: 820, height: 1180 });
  await installShellEventHold(page);
  await page.goto("/settings/data");
  const main = page.getByRole("main");
  await main.locator('input[type="file"]').setInputFiles(retailerCsv(`${TAG} Turned Mid-Answer`));
  await main.getByRole("combobox").selectOption("replace_all");
  await main.getByRole("button", { name: "Preview changes" }).click();
  await page.getByPlaceholder("REPLACE").fill("REPLACE");
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/import/apply", async (route) => {
    await held;
    await route.fulfill(importAnswer("replace_all"));
  });
  await page.getByRole("button", { name: "Apply import" }).click();
  await expect(main.getByText("Importing — Replace everything…")).toBeVisible();
  await page.evaluate(() => {
    const w = window as unknown as { __drawn?: boolean };
    w.__drawn = false;
    new MutationObserver(() => {
      if (document.querySelector("main")?.textContent?.includes("Import complete")) w.__drawn = true;
    }).observe(document.body, { childList: true, subtree: true });
  });
  await holdShellEvents(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(main.getByRole("combobox"), "the page has not heard of the turn").toHaveValue("replace_all");
  const answered = page.waitForResponse("**/import/apply");
  release();
  await answered;
  await expect(page.getByRole("radio", { name: "Merge" }), "the draft fell back").toBeChecked();
  await releaseShellEvents(page);
  await expect(main.getByText("Import complete"), "the outcome is drawn, in the phone's shape").toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __drawn: boolean }).__drawn)).toBe(true);
  await expect(main.getByText("Importing — Replace everything…")).toHaveCount(0);
  // Drawn, so acknowledged: shown once.
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await page.getByRole("link", { name: "Kits", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Kits" })).toBeVisible();
  await page.goBack();
  await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
  await expect(main.getByText("Import complete"), "seen, and gone").toHaveCount(0);
  await page.unroute("**/import/apply");
});

test("an answer that lands between a section's first render and its listener is handed over (PR #332 round 2)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "app", "one project is enough: the window is the mount's, not the shell's");
  // Codex's witness for M2: the request is a promise held in the page, and
  // a MutationObserver answers it as the returning section's heading is
  // inserted — after the mount read the import as pending, before its effect
  // hooked the listener. Only the module's hand-over at watch time tells it.
  await page.goto("/settings/data");
  const main = page.getByRole("main");
  await main.locator('input[type="file"]').setInputFiles(retailerCsv(`${TAG} Answered At Mount`));
  await main.getByRole("button", { name: "Preview changes" }).click();
  await page.evaluate((answer) => {
    const w = window as unknown as { __answer?: () => void };
    const real = window.fetch.bind(window);
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).endsWith("/import/apply")
        ? new Promise<Response>((resolve) => {
            w.__answer = () => resolve(new Response(answer.body, { status: 200, headers: { "Content-Type": answer.contentType } }));
          })
        : real(input, init)) as typeof fetch;
  }, importAnswer("merge"));
  await page.getByRole("button", { name: "Apply import" }).click();
  await expect(main.getByText("Importing — Merge…")).toBeVisible();
  await page.getByRole("link", { name: "Kits", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Kits" })).toBeVisible();
  await page.evaluate(() => {
    const w = window as unknown as { __answer: () => void; __answeredAt?: string };
    new MutationObserver((_, observer) => {
      const main = document.querySelector("main");
      if (!Array.from(main?.querySelectorAll("h2, h3") ?? []).some((heading) => heading.textContent === "Import")) return;
      observer.disconnect();
      w.__answeredAt = main!.textContent!.includes("Importing — Merge…") ? "pending" : "other";
      w.__answer();
    }).observe(document.body, { childList: true, subtree: true });
  });
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await sectionNav(page).getByRole("link", { name: "Data management", exact: true }).click();
  await expect(main.getByText("Import complete"), "handed over at watch time").toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __answeredAt?: string }).__answeredAt), "answered with the section mounted as pending").toBe("pending");
  await expect(main.getByText("Importing — Merge…")).toHaveCount(0);
});

test("a sign-out that succeeds takes the import with it, though the session could not be re-read (PR #332 round 2)", async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== "app", "one project is enough: the boundary is the session's, not the shell's");
  // Codex's reproduction, in a session of its own: the logout succeeds, both
  // re-reads of the session fail, so the page goes on believing the owner is
  // here. The import's answer must still not reach whoever signs in next —
  // the session reads `anonymous` before anyone can, and that is when it goes.
  const context = await browser.newContext({ baseURL: APP, viewport: { width: 1280, height: 720 }, storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  const main = page.getByRole("main");
  let release = () => {};
  try {
    await page.goto("/settings/data");
    await page.getByLabel("Password").fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
    await main.locator('input[type="file"]').setInputFiles(retailerCsv(`${TAG} Signed Out Under`));
    await main.getByRole("button", { name: "Preview changes" }).click();
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/import/apply", async (route) => {
      await held;
      await route.fulfill(importAnswer("merge"));
    });
    await page.getByRole("button", { name: "Apply import" }).click();
    await expect(main.getByText("Importing — Merge…")).toBeVisible();
    let reads = 0;
    await page.route("**/auth/session", (route) => {
      reads += 1;
      return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "session read failed" }) });
    });
    const logout = page.waitForResponse("**/auth/logout");
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    expect((await logout).status(), "the logout succeeded").toBe(204);
    await expect.poll(() => reads, { message: "and every re-read failed" }).toBeGreaterThanOrEqual(2);
    await page.getByRole("link", { name: "Kits", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Kits" })).toBeVisible();
    await page.unroute("**/auth/session");
    const anonymous = page.waitForResponse("**/auth/session");
    await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")));
    expect(((await (await anonymous).json()) as { state: string }).state).toBe("anonymous");
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
    const answered = page.waitForResponse("**/import/apply");
    release();
    await answered;
    await page.getByLabel("Password").fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await sectionNav(page).getByRole("link", { name: "Data management", exact: true }).click();
    await expect(main.getByRole("heading", { name: "Import", exact: true })).toBeVisible();
    await expect(main.getByText("Import complete"), "the next session is not handed the last one's import").toHaveCount(0);
    await expect(main.getByText("Importing — Merge…")).toHaveCount(0);
  } finally {
    release();
    await context.close();
  }
});

// -------------------------------------------------------------------- Home

test("Home on a phone: a completed row is two lines, the mail is three stacked groups, every control a finger", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the tablet's and the desktop's Home is the test below and home.spec.ts");
  for (const size of sizesFor("phone")) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      await page.goto("/");
      const completed = page.getByRole("region", { name: "Recently completed" });
      // Two lines by the strip's own box — under 26rem, which is every phone
      // (the widest has 408 px of strip) and not the top of the phone shell.
      const twoLines = size.width - 32 - 2 < 416;
      for (const name of [NAMES.rated, NAMES.unrated]) {
        const title = completed.getByText(name, { exact: true });
        await expect(title).toBeVisible();
        const row = title.locator("xpath=..");
        const pencil = row.getByRole("button", { name: `Edit ${name}` });
        const date = row.getByText(A_DATE);
        const [rowBox, titleBox, dateBox, pencilBox] = await Promise.all([rect(row), rect(title), rect(date), rect(pencil)]);
        expect.soft(pencilBox.width, `${name}: the pencil is a finger wide`).toBeGreaterThanOrEqual(44);
        expect.soft(pencilBox.height, `${name}: the pencil is a finger tall`).toBeGreaterThanOrEqual(44);
        if (!twoLines) {
          // An iPad mini in portrait: the strip is 712 px and holds the row on
          // one line — two left most of each row empty (seen in the simulator).
          expect.soft(dateBox.x, `${name}: the date is beside the name`).toBeGreaterThanOrEqual(titleBox.right - 0.5);
          expect.soft(Math.abs(dateBox.y + dateBox.height / 2 - (titleBox.y + titleBox.height / 2)), `${name}: on the name's line`).toBeLessThanOrEqual(3);
          continue;
        }
        expect.soft(dateBox.y, `${name}: the date is under the name`).toBeGreaterThanOrEqual(titleBox.bottom - 0.5);
        expect.soft(pencilBox.x, `${name}: the pencil is beside the name`).toBeGreaterThanOrEqual(titleBox.right - 0.5);
        expect.soft(pencilBox.x, `${name}: the pencil is beside the date`).toBeGreaterThanOrEqual(dateBox.right - 0.5);
        // Beside both lines, not down with the second.
        expect
          .soft(Math.abs(pencilBox.y + pencilBox.height / 2 - (rowBox.y + rowBox.height / 2)), `${name}: the pencil is centred on the row`)
          .toBeLessThanOrEqual(2);
        // The name has the line — everything but the pencil's column.
        expect.soft(titleBox.width, `${name}: the name's room`).toBeGreaterThanOrEqual(rowBox.width - pencilBox.width - 48);
        expect.soft(pencilBox.right, `${name}: inside the row`).toBeLessThanOrEqual(rowBox.right + 0.5);
      }
      // The rating's two states are both drawn, stars and the dash.
      await expect(completed.getByText(NAMES.rated, { exact: true }).locator("xpath=..").getByRole("img")).toBeVisible();

      // The mail: three groups, each under its chip, one under another — on
      // every phone there is. Home lays out by its box (§13.2), and at the
      // very top of the phone shell, an iPad mini in portrait, the box has
      // room for two groups abreast (42rem): there the groups only may not
      // overlap, which the sideways-scroll check and the widths below hold.
      const mail = page.getByRole("region", { name: "In the mail" });
      const stacked = size.width - 32 < 672;
      let above = 0;
      for (const stage of ["Pre-ordered", "Ordered", "In Transit"]) {
        const chip = mail.getByText(stage, { exact: true }).first();
        await expect(chip).toBeVisible();
        const group = chip.locator("xpath=../..");
        const box = await rect(group);
        if (stacked) {
          expect.soft(box.y, `${stage}: under the group before it`).toBeGreaterThanOrEqual(above - 0.5);
          expect.soft(box.width, `${stage}: the screen's width less the gutters`).toBeGreaterThanOrEqual(size.width - 32 - 1);
        } else {
          expect.soft(box.width, `${stage}: half the box or all of it`).toBeGreaterThanOrEqual((size.width - 32 - 16) / 2 - 1);
        }
        expect.soft(box.right, `${stage}: inside the screen`).toBeLessThanOrEqual(size.width - 16 + 0.5);
        above = box.bottom;
      }

      // A mail card's words end where its pencil begins: the target is 44 px
      // on a phone, and the text's room was cut for the mouse's 28.
      const under = await mail.evaluate((region, tag) =>
        [...region.querySelectorAll("article")]
          .filter((card) => card.textContent?.includes(tag))
          .flatMap((card) => {
            const pencil = card.querySelector("button")!.getBoundingClientRect();
            return [...card.querySelectorAll<HTMLElement>("span, a")]
              .filter((said) => said.children.length === 0 && said.getClientRects().length > 0)
              .filter((said) => {
                const rect = said.getBoundingClientRect();
                return rect.right > pencil.left + 0.5 && rect.left < pencil.right && rect.bottom > pencil.top + 0.5 && rect.top < pencil.bottom - 0.5;
              })
              .map((said) => `"${said.textContent?.trim()}" under the pencil of ${card.textContent?.slice(0, 30)}`);
          }),
        TAG,
      );
      expect.soft(under, "a mail card's words under its pencil").toEqual([]);

      const small = await page.getByRole("main").evaluate((main) =>
        [...main.querySelectorAll<HTMLElement>("button, a[href]")]
          .filter((control) => control.getClientRects().length > 0)
          .filter((control) => /^(Edit |View all )/.test(control.getAttribute("aria-label") ?? control.textContent?.trim() ?? ""))
          .map((control) => {
            const box = control.getBoundingClientRect();
            const edit = control.tagName === "BUTTON";
            return { name: control.getAttribute("aria-label") ?? control.textContent?.trim(), ok: box.height >= 44 && (!edit || box.width >= 44) };
          }),
      );
      expect(small.length, "Home has edit controls and view-all links to measure").toBeGreaterThanOrEqual(6);
      expect.soft(small.filter((control) => !control.ok), "controls under a finger").toEqual([]);
      await expectNoSidewaysScroll(page, "/");
    });
  }
});

test("from 768 px a completed row is the one line it was", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "the phone's row is the test above");
  // The widest size of the project: where the strip has the room, the row
  // must not have been stacked by this change. (Where it has not, it wraps by
  // need, as it always did — home.spec.ts and settings.spec.ts hold that.)
  const size = sizesFor(testInfo.project.name).at(-1)!;
  await page.setViewportSize(size);
  await page.goto("/");
  const title = page.getByRole("region", { name: "Recently completed" }).getByText(NAMES.unrated, { exact: true });
  await expect(title).toBeVisible();
  const row = title.locator("xpath=..");
  const [titleBox, dateBox] = await Promise.all([rect(title), rect(row.getByText(A_DATE))]);
  expect(dateBox.x, "the date is beside the name").toBeGreaterThanOrEqual(titleBox.right - 0.5);
  expect(Math.abs(dateBox.y + dateBox.height / 2 - (titleBox.y + titleBox.height / 2)), "on the name's line").toBeLessThanOrEqual(3);
});

// ------------------------------------------------- sign-in, setup and OIDC

const SESSIONS = {
  "first-run setup": { auth_mode: "local", state: "unclaimed" },
  "sign-in": { auth_mode: "local", state: "anonymous" },
  "OIDC setup": { auth_mode: "oidc", state: "unclaimed" },
  "OIDC sign-in": { auth_mode: "oidc", state: "anonymous" },
} as const;

test.describe("the screens in front of the app", () => {
  // Signed out, and the session answered by the test: see the file's head.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("sign-in, first-run setup and the OIDC screens fit a phone, with the room a keyboard leaves too", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "phone", "the desktop's screens are auth.spec.ts's and the README's");
    for (const [screen, session] of Object.entries(SESSIONS)) {
      await page.route("**/api/auth/session", (route) =>
        route.fulfill({
          json: {
            auth_mode: session.auth_mode,
            state: session.state,
            csrf_token: null,
            display_name: null,
            oidc_issuer: session.auth_mode === "oidc" ? "https://accounts.google.com" : null,
          },
        }),
      );
      // 390 × 420 is what an iPhone's keyboard leaves of 844 (the simulator's
      // measure, #259): the page must scroll to its button, not clip it.
      for (const size of [...sizesFor("phone").filter((s) => s.width < 744), { width: 390, height: 420 }]) {
        await test.step(`${screen} at ${size.width} × ${size.height}`, async () => {
          await page.setViewportSize(size);
          await page.goto("/");
          await expect(page.getByRole("heading", { level: 1, name: "plamotrack" })).toBeVisible();
          // The precondition: this is the screen the step names.
          const submit = page.getByRole("button").last();
          await expect(submit).toBeVisible();
          if (session.auth_mode === "oidc") await expect(submit).toHaveText(/^Continue with /);
          else await expect(page.getByLabel(/password/i).first()).toBeVisible();

          for (const input of await page.locator("input").all()) {
            const box = await rect(input);
            const font = await input.evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
            expect.soft(font, `${screen}: a field iOS will not zoom into`).toBeGreaterThanOrEqual(16);
            expect.soft(box.height, `${screen}: a field a finger tall`).toBeGreaterThanOrEqual(44);
            expect.soft(box.right, `${screen}: a field inside the screen`).toBeLessThanOrEqual(size.width - 16 + 0.5);
          }
          await expectNoSidewaysScroll(page, screen);
          // The button is reachable: scrolled to, it is inside what is left
          // of the screen, whole.
          await submit.scrollIntoViewIfNeeded();
          const box = await rect(submit);
          expect.soft(box.height, `${screen}: the button's height`).toBeGreaterThanOrEqual(40);
          expect.soft(box.y, `${screen}: the button is on screen`).toBeGreaterThanOrEqual(0);
          expect.soft(box.bottom, `${screen}: the button is on screen`).toBeLessThanOrEqual(size.height + 0.5);
        });
      }
      await page.unroute("**/api/auth/session");
    }
  });
});

// ------------------------------------- the browser's font-size preference

test("no page of the phone shell is wider than the screen under the browser's own font-size preference (#269)", async ({
  browserName,
}, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the phone shell's");
  test.skip(browserName !== "chromium", "the preference is Chromium's launch flag");
  test.setTimeout(240_000);
  // What #269 measured: the head's action (its text and padding in rem) ended
  // at 341 px on a 320 px screen, and the tab bar — fixed to a layout viewport
  // the overflow had widened — with it. A browser of its own, because the
  // preference is a launch setting; the same session, so the same owner.
  const PAGES: [string, string | null][] = [
    ["/", null],
    ["/kits", "Add kit"],
    ["/orders", "New order"],
    ["/inventory?tab=consumables", "Add consumable"],
    ["/retailers", "Add retailer"],
    ["/more", null],
    ["/settings", null],
    ["/settings/general", null],
    ["/settings/language", null],
    ["/settings/data", null],
    ["/settings/tokens", null],
    ["/settings/about", null],
  ];
  for (const font of [32, 40]) {
    const browser = await chromium.launch({ args: [`--blink-settings=defaultFontSize=${font}`] });
    try {
      const context = await browser.newContext({ storageState: STORAGE_STATE, hasTouch: true, isMobile: true, baseURL: APP });
      const page = await context.newPage();
      for (const size of sizesFor("phone").filter((s) => s.width < 744)) {
        await page.setViewportSize(size);
        for (const [path, action] of PAGES) {
          const at = `${path} at ${size.width} px, ${font} px font`;
          await page.goto(path);
          await expect(page.getByRole("heading", { level: 1 })).toBeAttached();
          if (path === "/") {
            // A strip's name keeps a floor in rem, capped at its row: uncapped,
            // 9rem was 288 px of a 254 px row and the name ran under the row's
            // clipped edge — no wider document, and the end of the name gone.
            for (const name of [NAMES.backlog, NAMES.rated]) {
              const title = page.getByText(name, { exact: true });
              await expect(title).toBeVisible();
              const [titleBox, rowBox] = await Promise.all([rect(title), rect(title.locator("xpath=.."))]);
              expect.soft(titleBox.right, `${at}: ${name} ends in its row`).toBeLessThanOrEqual(rowBox.right + 0.5);
            }
          }
          if (path === "/settings/tokens") await expect(page.getByText(NAMES.token).first()).toBeVisible();
          if (path === "/settings/data") {
            // With a preview under the import and its bar on screen (#304) —
            // previewed, never applied.
            await page.locator('input[type="file"]').setInputFiles(retailerCsv(`${TAG} Font ${font} ${size.width}`));
            await page.getByRole("button", { name: "Preview changes" }).click();
            await expect(page.getByRole("button", { name: "Apply import" })).toBeVisible();
          }
          // The precondition, said out loud: the preference is in force.
          expect(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)), "the root font size").toBe(font);
          const report = await page.evaluate(() => {
            const edge = (element: Element) => Math.round(element.getBoundingClientRect().right);
            const tabs = [...document.querySelectorAll('nav[aria-label="Main"] a')];
            return {
              scroll: document.documentElement.scrollWidth,
              client: document.documentElement.clientWidth,
              screen: innerWidth,
              tabs: tabs.length,
              lastTab: Math.max(...tabs.map(edge)),
            };
          });
          expect.soft(report.scroll, `${at}: the document's width`).toBeLessThanOrEqual(report.client);
          // A wide page widens the layout viewport, and `innerWidth` with it
          // (#272's lesson): the screen is the size this test set.
          expect.soft(report.screen, `${at}: the layout viewport is the screen`).toBe(size.width);
          expect.soft(report.tabs, `${at}: the tab bar's places`).toBe(5);
          expect.soft(report.lastTab, `${at}: the last tab ends on screen`).toBeLessThanOrEqual(size.width);
          if (action) {
            const button = page.getByRole("button", { name: action, exact: true });
            await expect.soft(button, `${at}: ${action}`).toBeVisible();
            const box = await rect(button);
            expect.soft(box.x, `${at}: ${action} starts on screen`).toBeGreaterThanOrEqual(0);
            expect.soft(box.right, `${at}: ${action} ends on screen`).toBeLessThanOrEqual(size.width + 0.5);
            // Fitting is not reading: squeezed beside the title the label fits
            // by breaking at every letter. It has the width it would take on
            // one line, or — where even a line of its own is narrower than that
            // ("consumable" at 40 px is wider than a 320 px bar) — the bar's.
            const room = await button.evaluate((element) => {
              const copy = element.cloneNode(true) as HTMLElement;
              copy.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;max-width:none;overflow-wrap:normal";
              element.parentElement!.appendChild(copy);
              const natural = copy.getBoundingClientRect().width;
              copy.remove();
              const bar = element.closest("header")!;
              const style = getComputedStyle(bar);
              return { natural, line: bar.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) };
            });
            expect.soft(box.width, `${at}: ${action} has its width or the bar's line`).toBeGreaterThanOrEqual(Math.min(room.natural, room.line) - 1);
          }
          if (path === "/settings/data") {
            for (const name of ["Cancel", "Apply import", "Merge", "Add only"]) {
              const box = await rect(page.getByRole("main").getByText(name, { exact: true }));
              expect.soft(box.x, `${at}: ${name} starts on screen`).toBeGreaterThanOrEqual(0);
              expect.soft(box.right, `${at}: ${name} ends on screen`).toBeLessThanOrEqual(size.width + 0.5);
            }
          }
          if (path.startsWith("/settings/")) {
            const back = await rect(wayBack(page));
            expect.soft(back.x, `${at}: the way back is on screen`).toBeGreaterThanOrEqual(0);
            expect.soft(Math.min(back.width, back.height), `${at}: the way back is a finger`).toBeGreaterThanOrEqual(44);
          }
          if (path === "/settings/tokens") {
            const card = page.getByTestId("token-card").filter({ hasText: NAMES.token }).filter({ visible: true });
            const [cardBox, revoke] = await Promise.all([rect(card), rect(card.getByRole("button", { name: "Revoke" }))]);
            expect.soft(revoke.right, `${at}: Revoke is inside its card`).toBeLessThanOrEqual(cardBox.right + 0.5);
            expect.soft(revoke.x, `${at}: Revoke is inside its card`).toBeGreaterThanOrEqual(cardBox.x - 0.5);
          }
        }
      }
      await context.close();

      // The screens in front of the app, under the same preference: signed
      // out, the session answered by the test. Their gutter, their card's
      // padding and the wordmark are in rem too — at 40 px on a 320 px phone
      // the wordmark alone was 311 px and the page 340.
      const out = await browser.newContext({ hasTouch: true, isMobile: true, baseURL: APP });
      const front = await out.newPage();
      for (const [screen, session] of Object.entries(SESSIONS)) {
        await front.route("**/api/auth/session", (route) =>
          route.fulfill({
            json: {
              auth_mode: session.auth_mode,
              state: session.state,
              csrf_token: null,
              display_name: null,
              oidc_issuer: session.auth_mode === "oidc" ? "https://accounts.google.com" : null,
            },
          }),
        );
        for (const size of sizesFor("phone").filter((s) => s.width < 744)) {
          const at = `${screen} at ${size.width} px, ${font} px font`;
          await front.setViewportSize(size);
          await front.goto("/");
          const wordmark = front.getByRole("heading", { level: 1, name: "plamotrack" });
          await expect(wordmark).toBeVisible();
          expect(await front.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)), "the root font size").toBe(font);
          await expectNoSidewaysScroll(front, at);
          const mark = await rect(wordmark.getByText("plamotrack"));
          expect.soft(mark.x, `${at}: the wordmark starts on screen`).toBeGreaterThanOrEqual(0);
          expect.soft(mark.right, `${at}: the wordmark ends on screen`).toBeLessThanOrEqual(size.width + 0.5);
          expect.soft(mark.height, `${at}: the wordmark is one line`).toBeLessThan(2 * 1.5 * font);
          const submit = await rect(front.getByRole("button").last());
          expect.soft(submit.right, `${at}: the button ends on screen`).toBeLessThanOrEqual(size.width + 0.5);
          // Inside the screen is not inside the card: a word wider than the
          // card's 118 px is still on a 320 px screen.
          const spilled = await front.locator("section").evaluate((card) =>
            [...card.querySelectorAll<HTMLElement>("*"), card as HTMLElement]
              .filter((element) => getComputedStyle(element).display !== "inline" && element.scrollWidth > element.clientWidth + 1)
              .map((element) => `${element.tagName.toLowerCase()} "${(element.textContent ?? "").trim().slice(0, 24)}" ${element.scrollWidth} in ${element.clientWidth}`),
          );
          expect.soft(spilled, `${at}: said past its own box`).toEqual([]);
        }
        await front.unroute("**/api/auth/session");
      }
      await out.close();
    } finally {
      await browser.close();
    }
  }
});

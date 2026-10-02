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

import { APP, STORAGE_STATE, apiContext } from "./api";

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
        await main.getByRole("button", { name: "Preview changes" }).click();
        const refused = main.locator("section").filter({ has: page.getByRole("heading", { name: "Import", exact: true }) }).getByRole("alert");
        await expect(refused).toHaveText("Import a .csv or a .zip archive.");
        await expect(refused).toBeInViewport();
        await expect(main.getByRole("alert")).toHaveCount(1);
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
        await main.getByRole("button", { name: "Preview changes" }).click();

        const section = main.getByRole("button", { name: /^Retailers \d/ });
        await expect(section).toHaveAttribute("aria-expanded", "true");
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
        await apply.click();
        await expect(main.getByText("Importing — Add only…"), "the sent import says what it is").toBeVisible();
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
    .poll(() => page.evaluate(() => Boolean(document.activeElement?.querySelector('[role="alert"]'))), {
      message: "the keyboard goes from the pending import to its outcome",
    })
    .toBe(true);
  await page.unroute("**/import/apply");

  // Never applied: nothing was written, and there is nothing to clean up.
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

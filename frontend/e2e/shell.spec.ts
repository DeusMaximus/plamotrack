/**
 * The three shells (design §13.7, #257): a bottom tab bar below 768 px, a 64 px
 * icon rail from there to 1279 px, the sidebar from 1280 px up — chosen by
 * viewport width alone. This file runs in three projects (playwright.config.ts):
 * `app` at the desktop default with a mouse, `phone` at 390 × 844 and `tablet` at
 * 820 × 1180, 1180 × 820 and 1366 × 1024, both with a touch screen. What it holds:
 *
 * - the width decides the shell, whatever the pointer is, and crossing a line
 *   re-dresses the page without remounting it;
 * - every destination, the theme control and Sign out are reachable in each
 *   shell, under the same accessible names (the rail's one theme button aside);
 * - the touch sizes (44 px targets, 16 px controls on a phone) apply where they
 *   should and the desktop's sizes are what they were;
 * - the document never scrolls sideways.
 *
 * The widths and sizes here are literals from the decision record, never
 * imported from `src/` — a test that reads its expectations from the code under
 * test moves with it. #258–#260 extend the phone and tablet projects page by page.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { OWNER_PASSWORD, apiContext } from "./api";

type Size = { width: number; height: number };
type Shell = "phone" | "rail" | "sidebar";

// `tablet`'s third size is a 13-inch iPad in landscape: the desktop's sidebar
// with a finger on it, the one place the touch sizes meet that shell.
const VIEWPORTS: Record<string, Size[]> = {
  app: [{ width: 1280, height: 720 }],
  phone: [{ width: 390, height: 844 }],
  tablet: [
    { width: 820, height: 1180 },
    { width: 1180, height: 820 },
    { width: 1366, height: 1024 },
  ],
};

/** Both sides of both lines, the devices the decision names (an iPad mini in
 *  portrait is a phone at 744; an 11-inch iPad is the rail both ways; a 13-inch
 *  one in landscape is the desktop), and the two project sizes. */
const WIDTHS: [number, Shell][] = [
  [390, "phone"],
  [744, "phone"],
  [767, "phone"],
  [768, "rail"],
  [820, "rail"],
  [1180, "rail"],
  [1279, "rail"],
  [1280, "sidebar"],
  [1366, "sidebar"],
];

const PAGES = [
  "/",
  "/kits",
  "/orders",
  "/inventory",
  "/retailers",
  "/more",
  "/settings/general",
  "/settings/language",
  "/settings/data",
  "/settings/tokens",
  "/settings/about",
];

const shellFor = (width: number): Shell => (width < 768 ? "phone" : width < 1280 ? "rail" : "sidebar");
const sizesFor = (project: string): Size[] => {
  const sizes = VIEWPORTS[project];
  if (!sizes) throw new Error(`shell.spec.ts has no viewports for the "${project}" project`);
  return sizes;
};

/** The shell on screen, read off its structure: a fixed tab bar and no `aside`
 *  is the phone's; an `aside` is the rail or the sidebar, told apart by width. */
function shellOnScreen(page: Page): Promise<{ shell: Shell | null; asideWidth: number | null }> {
  return page.evaluate(() => {
    const aside = document.querySelector("aside");
    if (aside) {
      const width = aside.getBoundingClientRect().width;
      return { shell: width < 100 ? ("rail" as const) : ("sidebar" as const), asideWidth: width };
    }
    const tabs = document.querySelector('nav[aria-label="Main"]');
    const fixed = tabs !== null && getComputedStyle(tabs).position === "fixed";
    return { shell: fixed ? ("phone" as const) : null, asideWidth: null };
  });
}

/** Polled: a resize reaches the page as a media-query event and a re-render,
 *  not within the call that made it. */
async function expectShell(page: Page, shell: Shell, label = ""): Promise<void> {
  const asideWidth = shell === "phone" ? null : shell === "rail" ? 64 : 240;
  await expect.poll(() => shellOnScreen(page), { message: label }).toEqual({ shell, asideWidth });
}

/** The shell's own navigation — not a link a page happens to carry. */
const chrome = (page: Page): Locator => page.locator("aside, nav");

/** Go to a destination the way this shell offers it: directly, or through More
 *  where the phone keeps it. The names are the same in every shell. */
async function open(page: Page, name: string): Promise<void> {
  await expect(page.locator("main")).toBeVisible();
  const link = chrome(page).getByRole("link", { name, exact: true });
  if (!(await link.isVisible())) {
    await chrome(page).getByRole("link", { name: "More", exact: true }).click();
  }
  await link.click();
}

/** Reach a control of the sidebar's lower half: on a phone it is on More. */
async function reach(page: Page, control: Locator): Promise<void> {
  await expect(page.locator("main")).toBeVisible();
  if (await control.isVisible()) return;
  await chrome(page).getByRole("link", { name: "More", exact: true }).click();
  await expect(control).toBeVisible();
}

/** On screen, inside the viewport, and the thing a tap at its centre would hit —
 *  not the tab bar, a sticky header or a browser's idea of the fold. */
async function expectTappable(control: Locator): Promise<void> {
  await control.scrollIntoViewIfNeeded();
  const hit = await control.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const top = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return {
      hitsControl: top !== null && (element === top || element.contains(top)),
      top: top ? `${top.tagName.toLowerCase()} "${(top.textContent ?? "").trim().slice(0, 40)}"` : "nothing",
      inViewport: box.top >= 0 && box.left >= 0 && box.bottom <= innerHeight && box.right <= innerWidth,
    };
  });
  expect(hit, `a tap at the control's centre lands on ${hit.top}`).toMatchObject({
    hitsControl: true,
    inViewport: true,
  });
}

const box = async (locator: Locator) => {
  const bounds = await locator.boundingBox();
  if (!bounds) throw new Error("no bounding box: the element is not rendered");
  return bounds;
};

const theme = (page: Page) => page.evaluate(() => document.documentElement.getAttribute("data-theme"));

test("the viewport's width alone chooses the shell, and crossing a line keeps the page", async ({
  page,
}) => {
  // In every project: the phone and tablet ones have a touch screen and the
  // desktop one a mouse, and the answer must be the same in all three.
  for (const [width, expected] of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    // A fresh document at each width. Resizing a live page and polling is
    // satisfied by the *previous* width's shell whenever two neighbours in the
    // list expect the same one — it passed with the sidebar's line moved to
    // 1024 px. The live switch is the rotation below, where every step changes
    // the shell.
    await page.goto("/retailers");
    await expectShell(page, expected, `${width} px`);
  }

  // A rotation across a line (an iPad mini: 1133 ↔ 744) swaps the navigation
  // around a page that stays mounted: the open dialog and what was typed into
  // it are still there. A remount would have closed it.
  await page.setViewportSize({ width: 1133, height: 744 });
  await page.getByRole("button", { name: "Add retailer" }).click();
  const dialog = page.getByRole("dialog", { name: "Add retailer" });
  await dialog.getByLabel("Name").fill("typed before the rotation");
  await page.setViewportSize({ width: 744, height: 1133 });
  await expectShell(page, "phone");
  await expect(dialog.getByLabel("Name")).toHaveValue("typed before the rotation");
  await page.setViewportSize({ width: 1366, height: 1024 });
  await expectShell(page, "sidebar");
  await expect(dialog.getByLabel("Name")).toHaveValue("typed before the rotation");
});

test("every destination is reachable, and the shell marks where you are", async ({ page }, testInfo) => {
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      await page.goto("/");
      const shell = shellFor(size.width);
      await expectShell(page, shell);

      for (const [name, path] of [
        ["Kits", "/kits"],
        ["Orders", "/orders"],
        ["Inventory", "/inventory"],
        ["Retailers", "/retailers"],
        ["Settings", "/settings/general"],
        ["Home", "/"],
      ] as const) {
        await open(page, name);
        await expect(page).toHaveURL(new RegExp(`${path}$`));
        // A list's h1 carries its count once the list has loaded ("Kits 12").
        await expect(
          page.getByRole("heading", { level: 1, name: new RegExp(`^${name}( [\\d,.]+)?$`) }),
        ).toBeAttached();
        const underMore = shell === "phone" && (name === "Retailers" || name === "Settings");
        if (underMore) {
          // The tab that holds this page is lit, but `/more` is the page it
          // names — so it is current, not the current *page*.
          await expect(chrome(page).getByRole("link", { name: "More", exact: true })).toHaveAttribute(
            "aria-current",
            "true",
          );
        } else {
          await expect(chrome(page).getByRole("link", { name, exact: true })).toHaveAttribute(
            "aria-current",
            "page",
          );
        }
      }

      // Home's bar carries the wordmark on a phone — the sidebar that held it
      // is gone — and the h1 stays for assistive tech.
      if (shell === "phone") {
        await expect(page.locator("header").getByText("plamotrack", { exact: true })).toBeVisible();
        await chrome(page).getByRole("link", { name: "More", exact: true }).click();
        await expect(page).toHaveURL(/\/more$/);
        await expect(chrome(page).getByRole("link", { name: "More", exact: true })).toHaveAttribute(
          "aria-current",
          "page",
        );
      } else {
        await expect(chrome(page).getByRole("link", { name: "More", exact: true })).toHaveCount(0);
      }
    });
  }
});

test("a list page's phone header is its title and its one action; Export CSV stays on the wider layouts", async ({
  page,
}, testInfo) => {
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      for (const [path, action] of [
        ["/kits", "Add kit"],
        ["/orders", "New order"],
        ["/inventory", "Add tool"],
        ["/retailers", "Add retailer"],
      ] as const) {
        await page.goto(path);
        await expectTappable(page.getByRole("button", { name: action, exact: true }));
        await expect(page.getByRole("button", { name: "Export CSV" })).toHaveCount(
          shellFor(size.width) === "phone" ? 0 : 1,
        );
      }
    });
  }
});

test("the theme control is reachable and works in this shell", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "light" });
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      await page.goto("/kits");
      if (shellFor(size.width) === "rail") {
        // 64 px has no room for three segments: one button that steps through
        // them, naming the choice in force.
        const name = /^Theme: /;
        await expectTappable(page.getByRole("button", { name }));
        await expect(page.getByRole("button", { name })).toHaveAccessibleName("Theme: Follow the device");
        await page.getByRole("button", { name }).click();
        await expect(page.getByRole("button", { name })).toHaveAccessibleName("Theme: Light");
        expect(await theme(page)).toBe("light");
        await page.getByRole("button", { name }).click();
        await expect(page.getByRole("button", { name })).toHaveAccessibleName("Theme: Dark");
        expect(await theme(page)).toBe("dark");
        await page.getByRole("button", { name }).click();
        await expect(page.getByRole("button", { name })).toHaveAccessibleName("Theme: Follow the device");
        expect(await theme(page)).toBe("light");
        return;
      }
      const control = page.getByRole("radiogroup", { name: "Theme" });
      await reach(page, control);
      await expectTappable(control.getByRole("radio", { name: "Dark" }));
      await control.getByRole("radio", { name: "Dark" }).click();
      expect(await theme(page)).toBe("dark");
      await control.getByRole("radio", { name: "Follow the device" }).click();
      expect(await theme(page)).toBe("light");
      await expect(control.getByRole("radio", { name: "Follow the device" })).toHaveAttribute(
        "aria-checked",
        "true",
      );
    });
  }
});

test("who the owner is bound as shows in this shell (OIDC mode)", async ({ page }, testInfo) => {
  // The suite runs in local mode, which stores no name. The session read is
  // the one thing changed: the real answer, with the three OIDC fields set.
  await page.route("**/api/auth/session", async (route) => {
    const response = await route.fetch();
    const session = (await response.json()) as Record<string, unknown>;
    await route.fulfill({
      response,
      json: {
        ...session,
        auth_mode: "oidc",
        oidc_issuer: "https://accounts.google.com",
        display_name: "Jamie Example",
      },
    });
  });
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      await page.goto("/kits");
      if (shellFor(size.width) === "rail") {
        // The initial alone, named in full for assistive tech and the tooltip.
        const initial = page.getByRole("img", { name: "Jamie Example · via accounts.google.com" });
        await expect(initial).toBeVisible();
        await expect(initial).toHaveText("J");
        return;
      }
      await reach(page, page.getByText("Jamie Example", { exact: true }));
      await expect(page.getByText("via accounts.google.com", { exact: true })).toBeVisible();
    });
  }
});

test("the document never scrolls sideways", async ({ page }, testInfo) => {
  for (const size of sizesFor(testInfo.project.name)) {
    await test.step(`${size.width} × ${size.height}`, async () => {
      await page.setViewportSize(size);
      for (const path of PAGES) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeAttached();
        const widths = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }));
        expect(widths.scroll, `${path} at ${size.width} px`).toBeLessThanOrEqual(widths.client);
      }
    });
  }
});

test("the phone's tab bar covers nothing: the page's last control scrolls clear of it", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "the tab bar is the phone shell's");
  // Short enough that More has to scroll to show its last row. Sign out is that
  // row, and without the room `main` reserves it would come to rest under the bar.
  await page.setViewportSize({ width: 390, height: 420 });
  await page.goto("/more");
  const signOut = page.getByRole("button", { name: "Sign out" });
  await expect(signOut).toBeVisible();
  // As far as the page goes — what a thumb does to reach the last row.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expectTappable(signOut);
  const bar = await box(page.getByRole("navigation", { name: "Main" }));
  const button = await box(signOut);
  expect(button.y + button.height).toBeLessThanOrEqual(bar.y);
  // …and the bar itself is on the bottom edge, all five tabs inside the screen.
  expect(bar.y + bar.height).toBe(420);
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link")).toHaveCount(5);
});

test.describe("touch sizes", () => {
  const SHOP = `E2E Shell Shop ${Date.now().toString(36)}`;
  let shopId: string | undefined;

  test.beforeAll(async () => {
    const api = await apiContext();
    const created = await api.post("/retailers", { data: { name: SHOP } });
    expect(created.ok(), await created.text()).toBeTruthy();
    shopId = ((await created.json()) as { id: string }).id;
    await api.dispose();
  });

  test.afterAll(async () => {
    if (!shopId) return;
    const api = await apiContext();
    await api.delete(`/retailers/${shopId}`);
    await api.dispose();
  });

  test("44 px targets and 16 px controls where a finger is, the desktop's sizes where a mouse is", async ({
    page,
  }, testInfo) => {
    // The touch sizes have two arms and each needs a case the other cannot
    // make: `phone` and `tablet` have a touch screen at every width, the rail's
    // and the sidebar's included; `app` has a mouse, and is sized down to a
    // phone here — a narrow desktop window — where the width alone decides.
    const project = testInfo.project.name;
    const sizes = project === "app" ? [...sizesFor(project), { width: 390, height: 844 }] : sizesFor(project);
    for (const size of sizes) {
      await test.step(`${size.width} × ${size.height}`, async () => {
        await page.setViewportSize(size);
        await page.goto("/retailers");
        const shell = shellFor(size.width);
        const touch = project !== "app" || shell === "phone";

        // IconButton: a row's edit pencil.
        const pencil = await box(page.getByRole("button", { name: `Edit ${SHOP}` }));
        expect([pencil.width, pencil.height]).toEqual(touch ? [44, 44] : [28, 28]);

        // A form control: 16 px text in the phone shell only (iOS zooms the
        // page on focus below that); 44 px tall under touch.
        const search = page.getByRole("searchbox", { name: "Search" });
        expect(await search.evaluate((input) => getComputedStyle(input).fontSize)).toBe(
          shell === "phone" ? "16px" : "14px",
        );
        const searchBox = await box(search);
        if (touch) expect(searchBox.height).toBeGreaterThanOrEqual(44);
        else expect(searchBox.height).toBeLessThan(40);

        // Every nav target of the shell.
        const links = chrome(page).getByRole("link");
        for (const link of await links.all()) {
          if (!(await link.isVisible())) continue;
          const bounds = await box(link);
          const name = (await link.getAttribute("aria-label")) ?? (await link.innerText());
          if (touch) {
            expect(bounds.height, name).toBeGreaterThanOrEqual(44);
            expect(bounds.width, name).toBeGreaterThanOrEqual(44);
          } else {
            expect(bounds.height, name).toBe(36);
          }
        }

        // The dialog's close.
        await page.getByRole("button", { name: `Edit ${SHOP}` }).click();
        const close = await box(page.getByRole("dialog").getByRole("button", { name: "Close" }));
        expect([close.width, close.height]).toEqual(touch ? [44, 44] : [24, 24]);
        await page.keyboard.press("Escape");

        // The theme control, wherever this shell keeps it.
        if (shell === "rail") {
          const button = await box(page.getByRole("button", { name: /^Theme: / }));
          expect([button.width, button.height]).toEqual([44, 44]);
        } else {
          const group = page.getByRole("radiogroup", { name: "Theme" });
          await reach(page, group);
          for (const radio of await group.getByRole("radio").all()) {
            const bounds = await box(radio);
            if (touch) {
              expect(bounds.height).toBeGreaterThanOrEqual(44);
              expect(bounds.width).toBeGreaterThanOrEqual(44);
            } else {
              expect(bounds.height).toBe(26);
            }
          }
        }
      });
    }
  });
});

test.describe("Sign out, from this shell", () => {
  // Its own signed-out browser and its own session, as auth.spec.ts does: the
  // owner session the other specs share is never the one signed out.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("ends the session", async ({ page }, testInfo) => {
    // The project's first size: the tab bar's More page on the phone, the rail
    // on the tablet, the sidebar on the desktop.
    await page.setViewportSize(sizesFor(testInfo.project.name)[0]);
    await page.goto("/");
    const signIn = page.getByRole("heading", { name: "Sign in" });
    await expect(signIn).toBeVisible();
    await page.getByLabel("Password").fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator("main")).toBeVisible();

    const signOut = page.getByRole("button", { name: "Sign out" });
    await reach(page, signOut);
    await expectTappable(signOut);
    await signOut.click();
    await expect(signIn).toBeVisible();
    await page.reload();
    await expect(signIn).toBeVisible();
  });
});

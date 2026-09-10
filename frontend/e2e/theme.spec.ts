/** The per-browser theme switch (design §13.1, #231): a choice applies without a
 *  reload, survives one, and "follow the device" follows it — the three things
 *  the sidebar control promises. Each test gets its own browser context, so a
 *  stored preference never leaks between tests or into the dev browser. */
import { expect, test, type Page } from "@playwright/test";

const theme = (page: Page) => page.evaluate(() => document.documentElement.getAttribute("data-theme"));

test("light / dark apply at once and survive a reload", async ({ page }) => {
  await page.goto("/kits");
  const control = page.getByRole("radiogroup", { name: "Theme" });
  await expect(control).toBeVisible();

  await control.getByRole("radio", { name: "Light" }).click();
  expect(await theme(page)).toBe("light");
  await expect(control.getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "true");

  await page.reload();
  await expect(page.getByRole("radiogroup", { name: "Theme" })).toBeVisible();
  expect(await theme(page)).toBe("light");

  await page.getByRole("radio", { name: "Dark" }).click();
  expect(await theme(page)).toBe("dark");
  await page.reload();
  await expect(page.getByRole("radiogroup", { name: "Theme" })).toBeVisible();
  expect(await theme(page)).toBe("dark");
});

test("follow the device means the device's scheme, live", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/kits");
  await page.getByRole("radio", { name: "Follow the device" }).click();
  expect(await theme(page)).toBe("light");
  // No reload: the media query listener is what moves it.
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(() => theme(page)).toBe("dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(() => theme(page)).toBe("light");
});

test("the theme is on <html> before the app runs", async ({ page }) => {
  // A stored choice against the device, and *when* it lands: the head script
  // runs while the parser is still in <head>, so the document is "loading" at
  // the first data-theme write; the bundle is a deferred module and would write
  // it at "interactive". Without the readyState the assertion below is also
  // satisfied by the module alone (measured: removing the script tag survived).
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => {
    localStorage.setItem("plamotrack.theme", "light");
    new MutationObserver((records, observer) => {
      if (records.some((record) => record.attributeName === "data-theme")) {
        (window as unknown as { __themeSetAt?: string }).__themeSetAt = document.readyState;
        observer.disconnect();
      }
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ["data-theme"] });
  });
  await page.goto("/kits");
  expect(await theme(page)).toBe("light");
  const setAt = () =>
    page.evaluate(() => (window as unknown as { __themeSetAt?: string }).__themeSetAt);
  expect(await setAt()).toBe("loading");
});

test("arrow keys move from the focused radio, not from a choice another tab made (#235 P3-2)", async ({
  page,
  context,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/kits");
  const dark = page.getByRole("radio", { name: "Dark" });
  await dark.click();
  await expect(dark).toBeFocused();

  // Another tab of this origin chooses Light: a real storage event reaches this
  // one, which follows the choice without taking focus from the Dark radio.
  const other = await context.newPage();
  await other.goto("/kits");
  await other.getByRole("radio", { name: "Light" }).click();
  await expect(page.getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
  await expect(dark).toBeFocused();

  // The radio pattern: the arrow moves from the focused radio (Dark → device).
  await dark.press("ArrowRight");
  const device = page.getByRole("radio", { name: "Follow the device" });
  await expect(device).toHaveAttribute("aria-checked", "true");
  await expect(device).toBeFocused();
  expect(await theme(page)).toBe("light");
  await other.close();
});

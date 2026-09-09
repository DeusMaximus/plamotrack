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
  // A stored choice against the device: what the head script does before the
  // bundle loads is what the first paint gets.
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.setItem("plamotrack.theme", "light"));
  await page.goto("/kits");
  expect(await theme(page)).toBe("light");
});

/**
 * Shared by `screenshots.spec.ts` and `auth.setup.ts`: where a capture goes and
 * whether it is wanted at all.
 *
 * Two output sets, one switch. With `SCREENSHOTS_OUT` unset the run writes only
 * the README's seven files into `docs/screenshots/` (the set README.md links);
 * with it set — the docs site's `images/screenshots/`, say — the run writes the
 * full set there, every page and dialog in both themes, and `docs/screenshots/`
 * is untouched. The README set is the one place the two lists are told apart.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Browser, type Locator, type Page } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const README_OUT = path.join(HERE, "..", "..", "docs", "screenshots");
const README_SET = new Set([
  "home.png",
  "home-light.png",
  "orders.png",
  "inventory.png",
  "retailers.png",
  "sign-in.png",
  "data.png",
]);
const OVERRIDE = process.env.SCREENSHOTS_OUT ? path.resolve(process.env.SCREENSHOTS_OUT) : null;

/** The capture runs only when asked for by name — never from `npm run test:e2e`. */
export const SCREENSHOTS = !!process.env.SCREENSHOTS;

export type Theme = "dark" | "light";
export const THEMES: readonly Theme[] = ["dark", "light"];

/** `name.png` for the dark default, `name-light.png` for the light theme. */
export function fileFor(name: string, theme: Theme): string {
  return `${name}${theme === "light" ? "-light" : ""}.png`;
}

function wanted(file: string): boolean {
  return OVERRIDE !== null || README_SET.has(file);
}

/** Screenshot `target` (a page or one element) as `name` in `theme`, if that
 *  file is part of the set this run writes. Settles layout, fonts and counters
 *  for a moment first. */
export async function save(target: Page | Locator, name: string, theme: Theme): Promise<void> {
  const file = fileFor(name, theme);
  if (!wanted(file)) return;
  const dir = OVERRIDE ?? README_OUT;
  fs.mkdirSync(dir, { recursive: true });
  const page = "page" in target && typeof target.page === "function" ? target.page() : (target as Page);
  await page.waitForTimeout(400);
  await target.screenshot({ path: path.join(dir, file) });
}

/** A context with no session, in `theme`: what a visitor sees before signing in. */
export async function anonymousContext(browser: Browser, theme: Theme, height: number) {
  // Inside a test, `browser.newContext()` starts from the project's `use`
  // options — the owner's storageState included — so the empty state is said
  // explicitly. A context with no stored theme preference follows its device.
  return browser.newContext({
    storageState: { cookies: [], origins: [] },
    colorScheme: theme,
    deviceScaleFactor: 2,
    viewport: { width: 1440, height },
  });
}

/** The unclaimed instance's first screen, both themes. Called by `auth.setup.ts`
 *  before it claims the owner — the one moment the form exists to be captured. */
export async function captureSetupScreen(browser: Browser): Promise<void> {
  for (const theme of THEMES) {
    const context = await anonymousContext(browser, theme, 720);
    const page = await context.newPage();
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Set up plamotrack" })).toBeVisible();
    await expect(page.getByLabel("Setup token")).toBeVisible();
    await save(page, "setup", theme);
    await context.close();
  }
}

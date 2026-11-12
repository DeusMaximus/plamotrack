/** Find a row on a list page that the test cannot narrow to its own rows (#317).
 *
 *  From 768 px a list draws ten rows a page. A test that opens a list and
 *  expects its own row on page 1 is right only while nothing sorts ahead of it,
 *  and the suite's other files, the other projects' runs of the same file,
 *  other workers and a reused database all put rows there: orders dated after
 *  the test's, names before it. Kits, Orders and Retailers have a search, and
 *  a test narrows them with `?q=` to what it seeded. Inventory has none — a
 *  tab and a category — and Upgrades not even a category, so there the test
 *  goes to the page its row is on, the way a person would.
 *
 *  Below 768 px every row is drawn and page 1 is the only page. */
import { expect, type Page } from "@playwright/test";

/** Open `path` on the page that shows `anchor` (a row's text), stepping
 *  `?page=` from 1 until it is drawn; fails once the last page has gone by
 *  without it. Where the last page is comes from the pager, not the range
 *  text: the range is the instance's number formatting — "1,000", or another
 *  script's digits — and the pager's last button is always the last page
 *  (Codex and Greptile on #325). No page limit: it stops at the last page. */
export async function openListAt(page: Page, path: string, anchor: string): Promise<void> {
  const join = path.includes("?") ? "&" : "?";
  const main = page.locator("main");
  const found = main.getByText(anchor).filter({ visible: true }).first();
  // A row of either shape: the rows and the pager arrive in one commit.
  const rows = main.locator("tbody tr, li").filter({ visible: true }).first();
  const pages = main.getByRole("navigation", { name: "Pages" }).filter({ visible: true });
  for (let at = 1; ; at += 1) {
    await page.goto(at === 1 ? path : `${path}${join}page=${at}`);
    await expect(found.or(rows).first(), `${path}: the list`).toBeVisible();
    if (await found.isVisible()) return;
    // One page (no pager), or the current page is the pager's last button.
    if ((await pages.count()) === 0) break;
    if ((await pages.getByRole("button").last().getAttribute("aria-current")) === "page") break;
  }
  throw new Error(`"${anchor}" is on no page of ${path}`);
}

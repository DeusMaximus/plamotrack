/**
 * What lists.spec.ts and lists.settings.spec.ts both measure with (design §13.7,
 * #258): the same questions — is a table wider than its box, is a control past
 * its list's edge — asked of the same pages, once with the instance's default
 * formatting and once with every date style the Settings page offers.
 */
import { expect, type Locator, type Page } from "@playwright/test";

export const main = (page: Page): Locator => page.locator("main");
export const shown = (locator: Locator): Locator => locator.filter({ visible: true });

export async function expandEveryOrder(page: Page): Promise<void> {
  const closed = main(page).getByRole("button", { name: /^Show line items/ });
  while ((await closed.count()) > 0) await closed.first().click();
}

/** The document does not scroll sideways, no table is wider than its box, and
 *  every control of every list is inside its list and the viewport. */
export async function expectFits(page: Page, label: string): Promise<void> {
  const report = await page.evaluate(() => {
    const onScreen = (element: Element) => element.getClientRects().length > 0;
    const root = document.querySelector("main");
    if (!root) return null;
    const boxes = [...root.querySelectorAll<HTMLElement>(".overflow-x-auto")].filter(
      (box) => box.querySelector("table") && onScreen(box),
    );
    const cardLists = [...root.querySelectorAll<HTMLElement>("ul")].filter(onScreen);
    const escaped: string[] = [];
    let controls = 0;
    for (const list of [...boxes, ...cardLists]) {
      const bounds = list.getBoundingClientRect();
      for (const control of list.querySelectorAll<HTMLElement>("button, a[href]")) {
        if (!onScreen(control)) continue;
        controls += 1;
        const rect = control.getBoundingClientRect();
        const inside =
          rect.left >= bounds.left - 0.5 &&
          rect.right <= bounds.right + 0.5 &&
          rect.left >= -0.5 &&
          rect.right <= innerWidth + 0.5;
        if (!inside) {
          escaped.push(
            `${control.getAttribute("aria-label") ?? control.textContent?.trim()} [${Math.round(rect.left)}–${Math.round(rect.right)}] outside [${Math.round(bounds.left)}–${Math.round(bounds.right)}]`,
          );
        }
      }
    }
    return {
      document: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
      boxes: boxes.map((box) => [box.scrollWidth, box.clientWidth]),
      lists: boxes.length + cardLists.length,
      controls,
      escaped,
    };
  });
  if (!report) throw new Error(`${label}: no <main> on the page`);
  // A page with no list, or a list with no control, measured nothing.
  expect(report.lists, `${label}: no list on the page`).toBeGreaterThan(0);
  expect(report.controls, `${label}: no control in any list`).toBeGreaterThan(0);
  expect.soft(report.document[0], `${label}: the document scrolls sideways`).toBeLessThanOrEqual(report.document[1]);
  for (const [scroll, client] of report.boxes) {
    expect.soft(scroll, `${label}: a table is wider than its box`).toBeLessThanOrEqual(client);
  }
  expect.soft(report.escaped, `${label}: controls outside their list`).toEqual([]);
}

/** Give the list's box every width from `first` to `last` and report the ones at
 *  which the list — the table, or the cards that replace it — is wider than the
 *  box or has a control past its edge. */
export function sweepBox(page: Page, first: number, last: number): Promise<{ widths: number[]; measured: number } | null> {
  return page.evaluate(
      ([from, to]) => {
        const onScreen = (element: Element) => element.getClientRects().length > 0;
        const root = document.querySelector("main") as HTMLElement;
        const box = [...root.querySelectorAll<HTMLElement>(".overflow-x-auto")].find((el) => el.querySelector("table"));
        if (!box) return null;
        // The element the container queries read: the box, or the wrapper round
        // it where a list swaps the table for cards (Access tokens).
        const container = (box.closest('[class*="@container"]') as HTMLElement | null) ?? box;
        const widths: number[] = [];
        let measured = 0;
        for (let width = from; width <= to; width += 1) {
          container.style.width = `${width}px`;
          const list = onScreen(box) ? box : (container.querySelector("ul") as HTMLElement);
          if (!list || !onScreen(list)) return { widths: [-width], measured };
          measured += 1;
          const controls = [...list.querySelectorAll<HTMLElement>("button, a[href]")].filter(onScreen);
          const edge = list.getBoundingClientRect().right + 0.5;
          if (list.scrollWidth > list.clientWidth || controls.some((control) => control.getBoundingClientRect().right > edge)) {
            widths.push(width);
          }
        }
        container.style.width = "";
        return { widths, measured };
      },
      [first, last],
  );
}

/** Whether what a list row says here is cut short or pushed out of its row: an
 *  element that clips its text is wider inside than out, and one a clipping
 *  ancestor cut off reaches past the row's edge. */
export function isCut(said: Locator): Promise<boolean> {
  return said.evaluate((element) => {
    const bounds = (element.closest("li, tr") as HTMLElement).getBoundingClientRect();
    const rect = element.getBoundingClientRect();
    return element.scrollWidth > element.clientWidth + 1 || rect.left < bounds.left - 0.5 || rect.right > bounds.right + 0.5;
  });
}

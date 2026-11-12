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

/** The fold stage a list's table is drawn at, and the one it should be (design
 *  §13.7, #329): the first, from the whole table up, at which the table's
 *  scrolling box is not wider inside than out — or the last, `stages`, when none
 *  is. Tried here, by hand and synchronously, so nothing of the page's own can
 *  run between a stage and its measurement: each stage's `data-fold-<n>`
 *  attributes are set on the box (cumulative: stage 2 is both), the box
 *  measured, and what was drawn put back. `floor`: the stage a box may not
 *  unfold past (Access tokens on a phone). Null when no fold box is drawn. */
export function foldState(
  page: Page,
  stages: number,
  floor = 0,
): Promise<{ drawn: number; expected: number; fits: boolean[] } | null> {
  return page.evaluate(
    ([stages, floor]) => {
      const onScreen = (element: Element) => element.getClientRects().length > 0;
      const box = [...document.querySelectorAll<HTMLElement>(".group\\/fold")].find(onScreen);
      if (!box) return null;
      const scroller = box.matches(".overflow-x-auto") ? box : (box.querySelector(".overflow-x-auto") as HTMLElement);
      const stageOf = () => [...box.attributes].filter((a) => /^data-fold-\d+$/.test(a.name)).length;
      const set = (stage: number) => {
        for (let n = 1; n <= stages; n += 1) box.toggleAttribute(`data-fold-${n}`, n <= stage);
      };
      const drawn = stageOf();
      const fits: boolean[] = [];
      for (let stage = 0; stage <= stages; stage += 1) {
        set(stage);
        fits.push(scroller.scrollWidth <= scroller.clientWidth);
      }
      set(drawn);
      const first = fits.findIndex((fit, stage) => fit && stage >= floor);
      return { drawn, expected: first === -1 ? stages : first, fits };
    },
    [stages, floor] as const,
  );
}

/** Wait until the page has had a frame to answer a change of size: its
 *  `ResizeObserver`s run before the frame is painted, the fold's first among
 *  them, and one observing a new target always reports it — so this one,
 *  started after the change, reports after the fold has chosen. It resolves in
 *  a task of its own: a caller that changed a size again from inside the
 *  observers' step would have the browser report "ResizeObserver loop completed
 *  with undelivered notifications" — the test's doing, once a width, and
 *  indistinguishable from the page's (measured: 666 in a 667-width sweep). */
export const afterResize = (page: Page): Promise<void> =>
  page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const observer = new ResizeObserver(() => {
          observer.disconnect();
          setTimeout(resolve);
        });
        observer.observe(document.documentElement);
      }),
  );

/** How many times a fold box's stage changes over `frames` frames from now —
 *  a mechanism that has settled changes nothing (Codex, on #329: a probe that
 *  folded by its current width flipped 60 times in 60 frames). */
export function stageChanges(page: Page, frames = 30): Promise<number> {
  return page.evaluate(async (frames) => {
    let changes = 0;
    const observer = new MutationObserver((records) => {
      changes += records.filter((record) => /^data-fold-\d+$/.test(record.attributeName ?? "")).length;
    });
    for (const box of document.querySelectorAll(".group\\/fold")) observer.observe(box, { attributes: true });
    for (let frame = 0; frame < frames; frame += 1) await new Promise(requestAnimationFrame);
    observer.disconnect();
    return changes;
  }, frames);
}

/** Give the list's box every width from `first` to `last` and report the ones at
 *  which the list — the table, or the cards that replace it — is wider than the
 *  box or has a control past its edge, and the ones at which the fold drawn is
 *  not the first that fits (`foldState`). A frame a width: the fold is chosen
 *  in a `ResizeObserver`, as a person's resize would have it, and the stage is
 *  read once the observers have run. `stages`: the box's fold stages. Then back
 *  down, every seventh width (reported negative): a box that narrows is the
 *  case an observer of the *table* misses — at its minimum it stops resizing
 *  while the box goes on shrinking — and a mutant that watched it survived the
 *  climb alone (#329). */
export function sweepBox(
  page: Page,
  first: number,
  last: number,
  stages: number,
  floor = 0,
): Promise<{ widths: number[]; misfolded: string[]; measured: number } | null> {
  return page.evaluate(
    async ([from, to, stages, floor]) => {
      const onScreen = (element: Element) => element.getClientRects().length > 0;
      const root = document.querySelector("main") as HTMLElement;
      const box = [...root.querySelectorAll<HTMLElement>(".overflow-x-auto")].find((el) => el.querySelector("table"));
      if (!box) return null;
      // The element the fold is chosen for and the sweep sizes: the box, or the
      // wrapper round it where a list swaps the table for cards (Access tokens).
      const container = (box.closest(".group\\/fold") as HTMLElement | null) ?? box;
      const stageOf = () => [...container.attributes].filter((a) => /^data-fold-\d+$/.test(a.name)).length;
      const set = (stage: number) => {
        for (let n = 1; n <= stages; n += 1) container.toggleAttribute(`data-fold-${n}`, n <= stage);
      };
      const answered = () =>
        new Promise<void>((resolve) => {
          const observer = new ResizeObserver(() => {
            observer.disconnect();
            setTimeout(resolve);
          });
          observer.observe(container);
        });
      const widths: number[] = [];
      const misfolded: string[] = [];
      let measured = 0;
      const down: number[] = [];
      for (let width = to - 7; width >= from; width -= 7) down.push(-width);
      for (const signed of [...Array.from({ length: to - from + 1 }, (_, n) => from + n), ...down]) {
        const width = Math.abs(signed);
        container.style.width = `${width}px`;
        await answered();
        const list = onScreen(box) ? box : (container.querySelector("ul") as HTMLElement);
        if (!list || !onScreen(list)) return { widths: [-width], misfolded, measured };
        if (signed > 0) measured += 1;
        const controls = [...list.querySelectorAll<HTMLElement>("button, a[href]")].filter(onScreen);
        const edge = list.getBoundingClientRect().right + 0.5;
        if (list.scrollWidth > list.clientWidth || controls.some((control) => control.getBoundingClientRect().right > edge)) {
          widths.push(signed);
        }
        if (stages > 0) {
          const drawn = stageOf();
          const fits: boolean[] = [];
          for (let stage = 0; stage <= stages; stage += 1) {
            set(stage);
            fits.push(box.scrollWidth <= box.clientWidth);
          }
          set(drawn);
          const firstFit = fits.findIndex((fit, stage) => fit && stage >= floor);
          const expected = firstFit === -1 ? stages : firstFit;
          if (drawn !== expected) misfolded.push(`${signed}: drawn ${drawn}, fits at ${expected}`);
        }
      }
      container.style.width = "";
      return { widths, misfolded, measured };
    },
    [first, last, stages, floor] as const,
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

/** How many lines the visible text inside `said` takes: the distinct tops of
 *  its text's boxes, skipping text that is not drawn (a fold's hidden copy, a
 *  reference's invisible sizer). */
export function linesOf(said: Locator): Promise<number> {
  return said.evaluate((element) => {
    const tops = new Set<number>();
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!parent || getComputedStyle(parent).visibility === "hidden" || parent.getClientRects().length === 0) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) if (rect.width > 1) tops.add(Math.round(rect.top));
    }
    return tops.size;
  });
}

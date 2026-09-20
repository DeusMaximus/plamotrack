/** A turn whose news has not arrived (#275).
 *
 *  A viewport that crosses a shell's line changes what `matchMedia(…).matches`
 *  says at once; the `change` event is a later step of the same frame. Whatever
 *  renders between the two reads the new shell while everything that waits for
 *  the event still holds the old one — `useSyncExternalStore` re-reads its
 *  snapshot on every render — so a key pressed in that gap opens a dialog in the
 *  same commit that swaps the rows under it. A person's window for that is a
 *  few milliseconds; Playwright's WebKit, whose `setViewportSize` resolves
 *  before the page has heard of the resize, hits it most runs and Chromium
 *  never. Holding the events makes it every run, in both.
 *
 *  `installShellEventHold` before the page loads; `hold` before the turn,
 *  `release` when the test has done what it wanted inside the gap. `matches`
 *  is never touched: what the page reads is the real viewport's. */
import type { Page } from "@playwright/test";

type Hold = { holding: boolean; held: (() => void)[] };

export async function installShellEventHold(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const state: Hold = { holding: false, held: [] };
    (window as unknown as { __shellEvents: Hold }).__shellEvents = state;
    const real = window.matchMedia.bind(window);
    window.matchMedia = (query: string) => {
      const list = real(query);
      const wrappers = new Map<unknown, EventListener>();
      const add = list.addEventListener.bind(list);
      const remove = list.removeEventListener.bind(list);
      list.addEventListener = ((type: string, listener: EventListener, options?: boolean | AddEventListenerOptions) => {
        const wrapped: EventListener = (event) => {
          if (state.holding) state.held.push(() => listener(event));
          else listener(event);
        };
        wrappers.set(listener, wrapped);
        add(type, wrapped, options);
      }) as typeof list.addEventListener;
      list.removeEventListener = ((type: string, listener: EventListener, options?: boolean | EventListenerOptions) => {
        remove(type, wrappers.get(listener) ?? listener, options);
      }) as typeof list.removeEventListener;
      return list;
    };
  });
}

export async function holdShellEvents(page: Page): Promise<void> {
  await page.evaluate(() => {
    (window as unknown as { __shellEvents: Hold }).__shellEvents.holding = true;
  });
}

/** Deliver what was held, in the order it came. */
export async function releaseShellEvents(page: Page): Promise<void> {
  await page.evaluate(() => {
    const state = (window as unknown as { __shellEvents: Hold }).__shellEvents;
    state.holding = false;
    for (const deliver of state.held.splice(0)) deliver();
  });
}

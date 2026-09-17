/** Focus by record (design §13.7, #258).
 *
 *  A list page draws a row's controls differently per shell — a `<tr>`'s pencil
 *  from 768 px, a card's below it — so when the viewport crosses the line the
 *  control the keyboard was on (or the one that opened the dialog now closing)
 *  is *gone*, and the browser drops focus to `<body>` without an event. One tree
 *  across the line is `PageHeader`'s remedy (Codex #265, finding 1); a table row
 *  and a card cannot be one element. So a control that is drawn per shell says
 *  which record it belongs to — `data-focus-key="kit:<id>"`, written out where
 *  it is used — and whoever needs to give the keyboard back finds the control
 *  that carries that key *now*.
 *
 *  The key names the record, not the words, because here the words do not: two
 *  kits from one order line share a name, three orders from one shop on one day
 *  share "Edit <shop> <date>", every upgrade's button says "Apply to kit", and
 *  the inline filters that stand where the phone's *Filter and sort* stood are
 *  not called that.
 *
 *  Two readers: `Modal`, when the control that opened it is gone at close; and
 *  `useFocusAcrossShells`, when the focused control itself was swapped away. */

import { useEffect, useLayoutEffect, useRef } from "react";

import type { Shell } from "./shell";

const FOCUS_KEY = "data-focus-key";

/** The key of the control this element is, or is inside; null for an unkeyed one. */
export function focusKeyOf(element: Element | null): string | null {
  return element?.closest(`[${FOCUS_KEY}]`)?.getAttribute(FOCUS_KEY) ?? null;
}

/** Focus the control that carries `key` now, if there is one. One at most: a
 *  page draws a record's control once per shell, never both shapes at a time. */
export function focusByKey(key: string): void {
  document.querySelector<HTMLElement>(`#root [${FOCUS_KEY}="${CSS.escape(key)}"]`)?.focus();
}

/** Keep the keyboard's place when the shell changes under it. Turning an iPad
 *  mini (744 px one way, 1133 the other) or dragging a window across 768 px
 *  swaps a list's table for cards; if the focused control was one of the rows',
 *  it is destroyed, focus falls to `<body>`, and the next Tab starts from the
 *  top of the page. After the swap, focus goes to the control carrying the same
 *  key. Called once, where the shell is chosen (`Layout`).
 *
 *  Which control the keyboard was on is remembered from `focusin`. Forgetting it
 *  is the subtle half: someone who clicked away from a row did not ask to be
 *  taken back to it at the next rotation — but the `focusout` a click-away fires
 *  is indistinguishable, when it is dispatched, from the one Chromium fires for
 *  a node being removed: both have nowhere as their related target, and in both
 *  the node is still connected. What tells them apart is the node one microtask
 *  later — measured, because the order is not the one a reading of React
 *  suggests: in a swap the `focusout` is dispatched inside the commit, the
 *  microtask runs next with the node *gone* and focus on `<body>`, and only then
 *  the layout effect below; after a click-away the microtask finds the node
 *  still in the page. So: still connected means someone left it, and the key is
 *  dropped before anything else can happen. (A version that asked only "is focus
 *  still on `<body>`?" forgot every swap, the effect not having run yet; a
 *  version with a `setTimeout` lost the race to a resize in lists.spec.ts. The
 *  mutants of this function are in #258's PR.) A deleted row keeps a key nothing
 *  carries, which finds nothing; an engine that fires nothing on removal never
 *  reaches the question. */
export function useFocusAcrossShells(shell: Shell): void {
  const lastKey = useRef<string | null>(null);

  useEffect(() => {
    const onFocusIn = (event: FocusEvent) => {
      lastKey.current = focusKeyOf(event.target as Element | null);
    };
    const onFocusOut = (event: FocusEvent) => {
      const left = event.target as Element | null;
      if (event.relatedTarget !== null || left === null) return;
      queueMicrotask(() => {
        if (left.isConnected && document.activeElement === document.body) lastKey.current = null;
      });
    };
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  // An effect of the component that chooses the shell: by the time it runs the
  // pages below have committed their side of the swap. A layout effect, so focus
  // is back before the frame is painted and the ring never misses one — which
  // no test can see; as a passive effect it would pass them all.
  useLayoutEffect(() => {
    if (lastKey.current !== null && document.activeElement === document.body) {
      focusByKey(lastKey.current);
    }
  }, [shell]);
}

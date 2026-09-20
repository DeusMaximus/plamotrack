/** Focus by record (design §13.7, #258).
 *
 *  The rule: **every change of representation accounts for the focused
 *  control.** A list page draws a row's controls differently per shell — a
 *  `<tr>`'s pencil from 768 px, a card's below it — a table folds a column away
 *  by its box's width, the navigation is a sidebar, a rail or a tab bar; when
 *  the viewport crosses a line the control the keyboard was on (or the one that
 *  opened the dialog now closing) is *gone*, or still in the page and no longer
 *  drawn, and the browser drops focus to `<body>`. One tree across the line is
 *  `PageHeader`'s remedy (Codex #265, finding 1); a table row and a card cannot
 *  be one element. So a control that is drawn per shape says which record it
 *  belongs to — `data-focus-key="kit:<id>"`, written out where it is used — and
 *  whoever needs to give the keyboard back finds the control that carries that
 *  key *now*.
 *
 *  The key names the record, not the words, because here the words do not: two
 *  kits from one order line share a name, three orders from one shop on one day
 *  share "Edit <shop> <date>", every upgrade's button says "Apply to kit".
 *
 *  A control that some shape does not draw at all names the one that stands in
 *  for it there: `data-focus-stand-in="list-filters"` on the Series and Sort
 *  selects, which a phone folds into the *Filter and sort* button that carries
 *  that key (Codex #266, finding 3). Several, in the order to try them, where
 *  the stand-in can be absent too — the sidebar's theme segments name the rail's
 *  one theme button and then the phone's More tab. The way back is not
 *  symmetric and does not pretend to be: the button stood for three selects, and
 *  what carries its key on the other side is the first of them.
 *
 *  Both shapes of a control can be in the page at once, one of them
 *  `display: none` — the Access tokens table and its cards, chosen in CSS by
 *  their box — so a key is carried by at most one control *that is drawn*, and
 *  that is the one that gets the keyboard.
 *
 *  Two readers: `Modal`, when the control that opened it is gone at close — or
 *  was gone already when it opened (`unansweredKeys`); and
 *  `useFocusAcrossShells`, when the focused control itself was swapped away. */

import { useEffect, useLayoutEffect } from "react";

import type { Shell } from "./shell";

const FOCUS_KEY = "data-focus-key";
const FOCUS_STAND_IN = "data-focus-stand-in";

/** Drawn: has a box. False for `display: none`, its own or an ancestor's, and
 *  for a node that has left the page. */
const isDrawn = (element: Element): boolean => element.getClientRects().length > 0;

/** What a `ResizeObserver` can watch on a control's behalf: the control, or —
 *  an inline box has no size to observe, and a text link is one — the nearest
 *  ancestor that has. Measured: observing the tracking link itself reported
 *  nothing when its column folded away. */
function sizedBoxOf(control: Element): Element {
  let box = control;
  while (box.parentElement && ["inline", "contents"].includes(getComputedStyle(box).display)) {
    box = box.parentElement;
  }
  return box;
}

/** Where the keyboard goes if this control stops being there: the key of the
 *  control this element is (or is inside), then its stand-ins in order. Empty
 *  for a control that carries neither. */
export function focusKeysOf(element: Element | null): string[] {
  const key = element?.closest(`[${FOCUS_KEY}]`)?.getAttribute(FOCUS_KEY);
  const standIns = element?.closest(`[${FOCUS_STAND_IN}]`)?.getAttribute(FOCUS_STAND_IN);
  return [...(key ? [key] : []), ...(standIns ? standIns.split(" ").filter(Boolean) : [])];
}

/** Focus the drawn control that carries `key`, if there is one, and say whether
 *  the keyboard is there now — a disabled control carries its key and takes no
 *  focus. Drawn is asked first and not left to `focus()`, which does nothing on
 *  a hidden control: where an engine leaves `activeElement` on the control a
 *  fold has just hidden, that control already "has" focus, and asking only
 *  where focus is would call the hidden copy the answer. */
export function focusByKey(key: string): boolean {
  // The document, not `#root`: a dialog is a portal beside the root, and its
  // Delete is drawn per shell too (#259). While a dialog is open the root is
  // inert, and an inert carrier takes no focus, so nothing under it answers.
  const carriers = document.querySelectorAll<HTMLElement>(`[${FOCUS_KEY}="${CSS.escape(key)}"]`);
  for (const carrier of carriers) {
    if (!isDrawn(carrier)) continue;
    carrier.focus();
    if (document.activeElement === carrier) return true;
  }
  return false;
}

/** The first of `keys` that something drawn carries. */
export function focusFirst(keys: readonly string[]): boolean {
  return keys.some(focusByKey);
}

/** The keyed control the keyboard was last on. The module's and not a ref of
 *  the hook's, because the hook is not its only reader (`unansweredKeys`); the
 *  hook is called once, where the shell is chosen, so there is one writer. */
let place: { control: Element; keys: string[] } | null = null;

/** The keys of the control the keyboard was on, when that control has stopped
 *  being there and nobody has answered for it yet — for a dialog opening onto
 *  exactly that (#275). `Modal` takes its opener from `document.activeElement`
 *  in an effect, after the commit that mounted it; a commit can mount a dialog
 *  *and* swap the rows its opener was one of, and then the opener it finds is
 *  `<body>`, with no key to give the keyboard back to at close. That commit
 *  exists: a viewport across a shell's line changes what `matchMedia` says at
 *  once and delivers `change` later in the frame, `useSyncExternalStore`
 *  re-reads its snapshot whenever its caller renders, so a key pressed in the
 *  gap renders the page — and the dialog — in the new shell while `Layout`,
 *  which has not rendered, still holds the old one and its effect below has not
 *  run. When it does run, the dialog has the keyboard and there is nothing left
 *  to answer. A few milliseconds for a person; most runs for Playwright's
 *  WebKit, whose `setViewportSize` resolves before the page hears of the
 *  resize (measured: 6 turns in 8; with the events held, 8 in 8 in both
 *  engines — `e2e/shellEvents.ts`).
 *
 *  For a caller that has found the keyboard on `<body>`: a place that is still
 *  remembered then is one whose control went — someone who *left* a control
 *  that is still there was forgotten a microtask after they did (below). */
export function unansweredKeys(): string[] {
  return place?.keys ?? [];
}

/** Keep the keyboard's place when the page changes shape under it. Turning an
 *  iPad mini (744 px one way, 1133 the other) or dragging a window across 768 px
 *  swaps a list's table for cards; if the focused control was one of the rows',
 *  it is destroyed, focus falls to `<body>`, and the next Tab starts from the
 *  top of the page. After the swap, focus goes to the control carrying the same
 *  key. Called once, where the shell is chosen (`Layout`).
 *
 *  Two ways a control stops being there, and one answer to each. **Removed** —
 *  React swapped the subtree because the shell changed: the layout effect on
 *  `shell` below. **No longer drawn** — a container query folded its column
 *  away or showed the cards instead of the table, with no shell change and no
 *  render at all (an iPad Air turning, 1180 to 820 px, is the rail both ways;
 *  Codex #266, finding 4): a `ResizeObserver` on the focused control, which
 *  reports a control that lost its box whatever took it, before the frame is
 *  painted (run in Chromium and WebKit; Firefox never). Where focus is at that moment is not one answer, in one
 *  Chromium: sometimes the observer runs first and `activeElement` is still the
 *  hidden control, sometimes the browser's own fix-up has already moved it to
 *  `<body>` with a `focusout` to nowhere — so the observer answers both, the
 *  forgetting rule below must not take the second for someone leaving, and
 *  `focusByKey` asks whether a carrier is drawn rather than whether it has focus
 *  (each of the three is a mutant lists.spec.ts kills). A removed node is left
 *  to the effect: it is not this observer's to report, and the effect has run
 *  by then.
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
 *  still in the page, *and still drawn* — a control a fold has just hidden is
 *  connected too, and nobody left it. So: connected and drawn means someone left
 *  it, and the place is dropped before anything else can happen. (A version that
 *  asked only "is focus still on `<body>`?" forgot every swap, the effect not
 *  having run yet; a version with a `setTimeout` lost the race to a resize in
 *  lists.spec.ts. The mutants of this function are in #258's PR.) A deleted row
 *  keeps a key nothing carries, which finds nothing; an engine that fires
 *  nothing on removal never reaches the question. */
export function useFocusAcrossShells(shell: Shell): void {
  useEffect(() => {
    let delivering = false;
    let deferred = 0;
    const hidden = new ResizeObserver(() => {
      const at = place;
      if (at === null || !at.control.isConnected || isDrawn(at.control)) return;
      const active = document.activeElement;
      if (active !== document.body && active !== at.control) return;
      delivering = true;
      try {
        focusFirst(at.keys);
      } finally {
        delivering = false;
      }
    });
    const remember = (next: typeof place) => {
      hidden.disconnect();
      cancelAnimationFrame(deferred);
      place = next;
      if (next === null) return;
      const watch = () => hidden.observe(sizedBoxOf(next.control));
      // Focus the observer moved lands here from inside its own delivery, and an
      // observation begun there is one the browser cannot deliver this frame. It
      // says so on `window` — "ResizeObserver loop completed with undelivered
      // notifications" — harmless to the person and a line in every error
      // tracker (measured: seven in one run of lists.spec.ts). A frame later is
      // soon enough for a control that was given the keyboard this instant.
      if (delivering) deferred = requestAnimationFrame(watch);
      else watch();
    };
    const onFocusIn = (event: FocusEvent) => {
      const control = event.target as Element | null;
      const keys = focusKeysOf(control);
      remember(control !== null && keys.length > 0 ? { control, keys } : null);
    };
    const onFocusOut = (event: FocusEvent) => {
      const left = event.target as Element | null;
      if (event.relatedTarget !== null || left === null) return;
      queueMicrotask(() => {
        if (left.isConnected && isDrawn(left) && document.activeElement === document.body) {
          remember(null);
        }
      });
    };
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      hidden.disconnect();
      cancelAnimationFrame(deferred);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  // An effect of the component that chooses the shell: by the time it runs the
  // pages below have committed their side of the swap. A layout effect, so focus
  // is back before the frame is painted and the ring never misses one — no test
  // here has seen the difference (a frame-by-frame sample of twenty rotations
  // found none, Codex #266), which is a limit of the measurement and not a proof.
  //
  // **And once more on the next frame**, because the premise above — the pages
  // below have committed their side of the swap — holds only when they commit
  // together, and they need not. Every `useShell()` caller subscribes media-query
  // lists of its own; the browser reports each list's change in turn, with a
  // microtask checkpoint between, and React commits each subscriber's re-render
  // there. So this component can commit first and run this effect over a control
  // that is still in the page, and the section that removes it commits after,
  // with nobody left to answer. Measured on Settings → Data management, three
  // callers deep: one turn in three left the keyboard on <body> (Codex #274,
  // finding 2 — first the stand-in was missing, then this was under it). By the
  // next frame every list has reported and every caller has committed. A frame,
  // and not the removed control's `focusout`, which was the first remedy:
  // WebKit does not reliably fire one for a node taken out of the page, and
  // there that remedy lost the same race one run in four.
  useLayoutEffect(() => {
    if (place !== null && document.activeElement === document.body) {
      focusFirst(place.keys);
    }
    const frame = requestAnimationFrame(() => {
      const at = place;
      if (at !== null && !at.control.isConnected && document.activeElement === document.body) {
        focusFirst(at.keys);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [shell]);
}

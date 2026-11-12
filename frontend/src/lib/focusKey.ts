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
    // Disabled is asked first too: WebKit leaves `activeElement` on a control
    // it has just disabled, so a disabled carrier that was focused would pass
    // for the answer — measured on − at zero, where the keyboard stayed on the
    // disabled − and never reached + (#268).
    if (!isDrawn(carrier) || carrier.matches(":disabled")) continue;
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
 *  the hook's, because the hook is not its only reader (`unansweredKeys`).
 *
 *  **One owner:** `useFocusAcrossShells`, called once, where the shell is chosen
 *  (`Layout`), is the only writer, and the store outlives it — signed out, the
 *  listeners are gone and the last place stays. That is safe only because every
 *  reader asks what the place *is now* (below) and because the first `focusin`
 *  after `Layout` mounts again replaces it; no path in the app was found that
 *  reaches a reader in between (Codex #276 looked too). A second caller of the
 *  hook would be a second writer of one store: decide who owns it, and when it
 *  ends, before adding one — clearing it in each caller's cleanup is not that. */
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
 *  **An unanswered loss, not the last keyed `focusin`:** nothing, while the
 *  remembered control is in the page and drawn. "Still remembered" does not
 *  mean "gone" — a control hidden and shown again, or taken out and put back,
 *  was never *left*, so the forgetting rule below kept it, and no event marks
 *  its return; a dialog opened onto `<body>` after that (a pointer in Safari,
 *  which focuses no button) was handed at close to a control that had not
 *  opened it (Codex #276, finding 1 — this check was in the first draft and
 *  came out as "nothing can make it differ"; three things could). Drawn, which
 *  a node out of the page is not either — and not merely connected: a fold's
 *  hidden copy is connected, and its visible twin is exactly who should answer. */
export function unansweredKeys(): string[] {
  if (place === null || isDrawn(place.control)) return [];
  return place.keys;
}

/** The keys of the controls that opened the dialogs now open, outermost
 *  first. `Modal` holds its opener's here while it is open (`holdOpener`): the
 *  focused control is then inside the dialog and carries no key, and the record
 *  the keyboard will go back to is the opener's. */
const openers: (readonly string[])[] = [];

/** Hold an open dialog's opener keys; the return releases them at close. */
export function holdOpener(keys: readonly string[]): () => void {
  openers.push(keys);
  return () => {
    const at = openers.indexOf(keys);
    if (at >= 0) openers.splice(at, 1);
  };
}

/** The records the keyboard is on or will come back to — the open dialogs'
 *  openers, then the focused control — for a list that changes which rows it
 *  draws in a turn and must keep that record's row among them (#321,
 *  `usePaging`). Read at the render that crosses the line, before the commit
 *  that swaps the rows: the focused control is still the one that was. */
export function focusedRecordKeys(): string[] {
  return [...openers.flat(), ...(place?.keys ?? [])];
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
 *  `shell` below. **No longer drawn** — a table folded its column away or
 *  showed the cards instead of the table (`FoldToFit`, #329), with no shell
 *  change and no render of the control at all (an iPad Air turning, 1180 to 820 px, is the rail both ways;
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
 *  nothing on removal never reaches the question.
 *
 *  **And a control that can no longer act** (#268) — `disabled` under the
 *  keyboard, or taken out of the page by a commit that is not a shell change:
 *  **−** at zero, a Save with nothing left to save, a revoked token's Revoke,
 *  Create replaced by the token it made. Disabling the focused control drops
 *  the keyboard to `<body>` exactly as removing it does, and outside a dialog
 *  nobody answered (`Modal` answers inside one; a dialog's keyed controls are
 *  its Delete's twins, in one state, so there this finds nothing to give the
 *  keyboard to and `Modal` is the one that does). A `MutationObserver` on
 *  `disabled` and on the tree hands the keyboard to the first of the control's
 *  keys something drawn can take — its own, for a twin, then the stand-ins it
 *  names (−'s is +, a Save's the field before it). A control that is only *waiting* is not this: it keeps the
 *  keyboard (`Button`'s `pending`, `aria-disabled`), because the person is
 *  still there and it will act again. The observer acts while focus is on
 *  `<body>`, or still on the disabled control: it runs in the mutation's own
 *  microtask, before either engine has moved the keyboard (WebKit moves it
 *  late, #259) — so the forgetting rule's `focusout` comes after the answer
 *  and needs no exception for a disabled control (measured: one was written,
 *  and no test in either engine could tell it was there). */
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
    // Once per loss: a control nothing could answer for is not answered later,
    // by whatever renders next with its key while the keyboard happens to be
    // on `<body>` — that would be a jump nobody asked for. A disabled one is
    // then forgotten. A removed one is kept for the shell effect below, whose
    // frame-later answer exists for a twin that mounts in a later commit — and
    // only that long: two frames, so that answer has run whichever of the two
    // commits came first, and then it is forgotten too, or the next shell
    // change would answer it (Codex #336: a phone turned to the rail raised
    // the on-screen keyboard for a token's name).
    let answered: Element | null = null;
    let expiry = 0;
    const stranded = new MutationObserver(() => {
      const at = place;
      if (at === null || at.control === answered) return;
      // The keys as the control says them *now*: its stand-ins can change
      // while it has the keyboard — a Revoke's neighbours, when the list is
      // refetched under it — and the loss is answered with the last ones it
      // carried (Greptile #336).
      if (at.control.isConnected) {
        const keys = focusKeysOf(at.control);
        if (keys.length > 0) at.keys = keys;
      }
      const active = document.activeElement;
      const disabled = at.control.isConnected && at.control.matches(":disabled");
      const lost = disabled
        ? active === document.body || active === at.control
        : !at.control.isConnected && active === document.body;
      if (!lost) return;
      answered = at.control;
      if (focusFirst(at.keys)) return;
      if (disabled) {
        remember(null);
        return;
      }
      cancelAnimationFrame(expiry);
      expiry = requestAnimationFrame(() => {
        expiry = requestAnimationFrame(() => {
          if (place?.control === at.control) remember(null);
        });
      });
    });
    const onFocusIn = (event: FocusEvent) => {
      const control = event.target as Element | null;
      const keys = focusKeysOf(control);
      // A control the keyboard comes back to can be lost again (a second Save).
      answered = null;
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
    // `disabled` alone of the attributes: it is the one that drops focus and
    // that a control here changes on itself (`Modal` measured `hidden` and
    // `inert` too; neither is set on a focused control outside a dialog). Not
    // the key attributes: a change of the list that changes a control's
    // stand-ins changes the tree too, and any mutation refreshes the keys
    // (measured: watching them as well changed nothing a test could see).
    stranded.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["disabled"],
    });
    return () => {
      stranded.disconnect();
      cancelAnimationFrame(expiry);
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

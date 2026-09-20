import type { ReactNode, RefObject } from "react";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { focusFirst, focusKeysOf, unansweredKeys } from "../lib/focusKey";
import { useShell } from "../lib/shell";
import { Button } from "./ui";

/** What a keyboard can land on, in DOM order. Deliberately not a library: this
 *  list plus the trap below is the whole of what five dialogs need, and adopting
 *  Radix or Headless UI mid-alpha is a dependency decision that deserves its own
 *  discussion rather than arriving inside an accessibility fix (#51). */
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/** What every engine's Tab stops on of its own accord: a field you type in, a
 *  select, a textarea. Safari's default Tab does not stop on a button, a link, a
 *  checkbox or a radio (Option-Tab does, as does its "Press Tab to highlight
 *  each item" setting), so a trap that only guards the ends of its own list
 *  let one Shift+Tab out of a dialog whose first control is its Close button:
 *  from the first field, WebKit found no earlier *field* inside and left for
 *  `<body>` (#267). So the trap hand-drives a Tab whose next stop is anything
 *  an engine might skip, and lets the engine make the moves every engine makes
 *  alike — which keeps a date input's own Tab, the one that walks its day,
 *  month and year, out of the trap's hands (`SEGMENTED`). */
const ENGINE_TABS_TO =
  "input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]):not([type=file]):not([type=button]):not([type=submit]):not([type=reset]), select, textarea";
/** A field the engine steps through in parts: a Tab that is not from its last
 *  part is the field's own, and only the engine knows which part has focus. */
const SEGMENTED =
  "input[type=date], input[type=time], input[type=datetime-local], input[type=month], input[type=week]";

function focusableWithin(dialog: HTMLElement): HTMLElement[] {
  // `offsetParent` is null for anything `display: none`, which is how a
  // conditionally rendered field that is still mounted drops out of the cycle.
  return [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) => element.offsetParent !== null,
  );
}

/** Open dialogs, so the *last* one out restores the page rather than the first.
 *  Nothing stacks dialogs today; this costs three lines and removes the class. */
let openDialogs = 0;

/** Give the keyboard back to whatever opened the dialog — or, when that node is
 *  gone, to the control standing where it stood. It can be gone without the
 *  record going anywhere: a dialog stays open while a tablet is turned (§13.7 —
 *  `main` never remounts), and a list page is card rows on one side of the
 *  768 px line and a table on the other, so the pencil that opened the dialog is
 *  not the pencil on the page when it closes. The stand-in is found by the
 *  opener's `data-focus-key`, then its `data-focus-stand-in` (`lib/focusKey.ts`
 *  says why a key and not the name). An opener with no key is left as it always was — focused if it is
 *  still there, and otherwise wherever the browser puts focus; a control that
 *  is drawn differently per shell and opens a dialog owes itself a key, and
 *  lists.spec.ts's rotation test is where a missing one shows. */
function restoreFocus(opener: HTMLElement | null, keys: readonly string[]): void {
  opener?.focus();
  // Gone, or in the page and not drawn (a fold's hidden copy): `focus()` did
  // nothing either way, and asking where focus is covers both.
  if (document.activeElement !== opener) focusFirst(keys);
}

/** iOS Safari does not resize the layout viewport for the on-screen keyboard:
 *  the *visual* viewport shrinks and pans over a page that is still full
 *  height, so the bar at the foot of a full-screen sheet sits under the
 *  keyboard for as long as a field is focused (Chrome for Android does the
 *  same unless the viewport meta asks otherwise). So the phone's sheet follows
 *  the visual viewport — its height and its offset, while the two differ — and
 *  the bar stays above the keyboard. Measured on the iOS Simulator (iPhone 17,
 *  iOS 27, #259), which found what the first version got wrong:
 *
 *  - it is the **panel** that follows, not the overlay: a shrunken overlay
 *    uncovered the page between the bar and the keyboard, so the overlay keeps
 *    the screen (and on a phone has the sheet's own ground, not the backdrop);
 *  - **the focused field is scrolled back into the sheet's scroller** when the
 *    viewport changes and when focus moves while it is shrunk: iOS scrolls a
 *    field into view against the viewport as it was *before* the sheet
 *    shrank, and left the tapped field under the bar.
 *
 *  Set through the CSSOM, which the packaged stack's `style-src 'self'`
 *  permits where an inline `style` attribute is refused. The full-screen frame
 *  only: the bottom sheet holds no field that raises a keyboard, and on a
 *  desktop the two viewports differ under pinch-zoom alone. */
function useFollowVisualViewport(panel: RefObject<HTMLDivElement | null>, follow: boolean): void {
  useEffect(() => {
    const viewport = window.visualViewport;
    const element = panel.current;
    if (!follow || !viewport || !element) return;
    let shrunk = false;
    const reveal = () => {
      const active = document.activeElement;
      if (shrunk && active instanceof HTMLElement && active !== element && element.contains(active)) {
        active.scrollIntoView({ block: "nearest" });
      }
    };
    const place = () => {
      shrunk = window.innerHeight - viewport.height >= 1 || viewport.offsetTop >= 1;
      if (!shrunk) {
        element.style.removeProperty("margin-top");
        element.style.removeProperty("height");
        return;
      }
      element.style.setProperty("margin-top", `${viewport.offsetTop}px`);
      element.style.setProperty("height", `${viewport.height}px`);
      requestAnimationFrame(reveal);
    };
    const onFocusIn = () => requestAnimationFrame(reveal);
    viewport.addEventListener("resize", place);
    viewport.addEventListener("scroll", place);
    element.addEventListener("focusin", onFocusIn);
    place();
    return () => {
      viewport.removeEventListener("resize", place);
      viewport.removeEventListener("scroll", place);
      element.removeEventListener("focusin", onFocusIn);
      element.style.removeProperty("margin-top");
      element.style.removeProperty("height");
    };
  }, [panel, follow]);
}

/** One of a dialog's actions, described rather than rendered: the frame draws
 *  it where the shell wants it (§13.7, #259) — at the end of the panel on the
 *  desktop, in a bar at the foot of the screen on a phone — and dresses it for
 *  that place. A `form` makes it the submit of that form, which it stands
 *  outside of; an `onClick` alone is a plain button. */
export interface DialogAction {
  label: string;
  onClick?: () => void | Promise<void>;
  disabled?: boolean;
  form?: string;
}

/** The phone's action bar: a share for the secondary action, two for the
 *  primary, both 48 px, above the home indicator. The filter sheet's (#258),
 *  now every dialog's. Spelled twice — bare for the bottom sheet, which is the
 *  phone's alone, and under `max-md:` for the frame the desktop shares —
 *  because Tailwind reads class names from the source as written. */
const BAR_CLASS =
  "grid shrink-0 grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2.5 border-t border-rule bg-surface px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]";
const PHONE_BAR_CLASS =
  "max-md:grid max-md:shrink-0 max-md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] max-md:gap-2.5 max-md:border-t max-md:border-rule max-md:bg-surface max-md:px-4 max-md:pt-3 max-md:pb-[calc(0.75rem+env(safe-area-inset-bottom))]";
/** A bar's button is as wide as its column and its label is centred, so its
 *  own side padding buys nothing — and costs the label its room: `Button`'s
 *  0.75rem a side is 60 px of Cancel's 71 px column under a 40 px browser font
 *  on a 320 px phone, and once a label may break inside a word there (#270)
 *  the six letters of "Cancel" took six lines and left the button (Codex #274,
 *  finding 1). 4 px a side, in px like the label; a label still wider than its
 *  column — a long translation — breaks, and the button grows to hold it
 *  (`min-h`, not `h`; important, because `Button` has a `touch:min-h-10` of
 *  its own that the stylesheet happens to emit later — dialogs.spec.ts's
 *  "is a bar button" is what said so). */
const BAR_BUTTON_CLASS = "min-h-12! justify-center px-[4px] text-center text-[15px]";
const PHONE_BAR_BUTTON_CLASS =
  "max-md:min-h-12! max-md:justify-center max-md:px-[4px] max-md:text-center max-md:text-[15px]";

function ActionButton({
  action,
  variant,
  className = "",
  focusKey,
}: {
  action: DialogAction;
  variant: "primary" | "secondary" | "danger";
  className?: string;
  focusKey?: string;
}) {
  return (
    <Button
      type={action.form ? "submit" : "button"}
      form={action.form}
      variant={variant}
      disabled={action.disabled}
      onClick={action.onClick}
      data-focus-key={focusKey}
      className={className}
    >
      {action.label}
    </Button>
  );
}

/** The focus key of a dialog's Delete (`lib/focusKey.ts`): drawn twice, in the
 *  body for a phone and in the action row for the desktop, one of them
 *  `display: none`, so a turn across the 768 px line with the keyboard on it
 *  hands the keyboard to the twin. */
const DELETE_FOCUS = "dialog-delete";

export function Modal({
  title,
  onClose,
  children,
  wide = false,
  sheet = false,
  actions,
  destructive,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  /** A bottom sheet (§13.7): the same dialog — focus trap, Escape, inert page —
   *  risen from the foot of the screen, where a thumb is. The filter sheet's. */
  sheet?: boolean;
  /** The dialog's secondary and primary actions. With them the dialog owns its
   *  action row; a form hands the primary its id and renders no buttons of its
   *  own. Without them the dialog has no foot (a loading state). */
  actions?: { secondary: DialogAction; primary: DialogAction };
  /** Delete, next to the fields it destroys (§13.4): at the end of the form on a
   *  phone and at the start of the action row on the desktop — never in the
   *  phone's fixed bar, where it would be one tap away at every scroll
   *  position (owner's call, 2026-09-17). */
  destructive?: DialogAction;
}) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const phone = useShell() === "phone";
  useFollowVisualViewport(dialogRef, phone && !sheet);

  useEffect(() => {
    // Captured before focus moves, so closing returns the user to the control
    // they opened this from rather than to the top of the document.
    //
    // `<body>` is not an opener, it is where focus falls when one is lost: a
    // pointer in Safari, which focuses no button (nothing to return to, as
    // ever), or — #275 — the commit that mounted this dialog also swapped the
    // rows its opener was one of. For the second the opener's keys are still
    // known (`unansweredKeys` says how that commit comes about), and closing
    // gives the keyboard to whatever carries them, as it does for an opener
    // that went while the dialog was open.
    const active = document.activeElement as HTMLElement | null;
    const opener = active === document.body ? null : active;
    const openerKeys = opener === null ? unansweredKeys() : focusKeysOf(opener);
    const appRoot = document.getElementById("root");

    openDialogs += 1;
    // `inert` and not just a focus trap: a trap governs Tab, while inert also
    // takes the background out of the accessibility tree, so a screen reader
    // cannot browse the page underneath a dialog that is covering it.
    if (appRoot) appRoot.inert = true;

    // The dialog itself rather than its first control, so its accessible name is
    // announced on open; Tab then moves to the first field. Focusing the close
    // button instead would announce "Close" as the first thing a screen-reader
    // user hears about a form they just opened.
    dialogRef.current?.focus();

    return () => {
      openDialogs -= 1;
      // Un-inert *before* restoring focus — focus() on a node inside an inert
      // subtree silently does nothing, which would strand the user at <body>.
      if (appRoot && openDialogs === 0) appRoot.inert = false;
      restoreFocus(opener, openerKeys);
    };
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    // Focus can leave the dialog without any key being pressed: remove the node
    // that has it and the browser drops focus to <body>, firing no blur and no
    // focusout (measured in Chromium when this was written, #51 — by #258 the
    // same measurement found Chromium firing both, which `lib/focusKey.ts`
    // depends on; an observer holds either way, and in an engine that fires
    // neither). The Tab handler recaptures on the *next* press, which leaves a
    // keyboard user nowhere in between and a screen reader announcing the
    // document.
    //
    // Reachable from the order form: `CatalogItemPicker` opens its result list
    // on focus and closes it 150ms after the input blurs, and the results follow
    // the input in DOM order — so tabbing off the input lands on a result button
    // that then unmounts underneath. Filed separately as the picker's own defect;
    // this is the dialog holding its end of the bargain regardless of why a node
    // went away.
    // WebKit takes the keyboard off a control it has just disabled *later* than
    // the attribute changes — after this observer has looked and found focus
    // still on the button — and then drops it to <body> with no one watching
    // (measured under Playwright's WebKit, #259). So the observer also acts on
    // a focused control that is disabled or hidden now, before the engine
    // decides, and a `focusout` to nowhere is checked a microtask later. That
    // check gives the keyboard first to whatever carries the lost control's
    // focus key (`lib/focusKey.ts`) — Delete is drawn twice, one twin per
    // shell, and a turn across the 768 px line hides the focused one — and to
    // the dialog itself only when nothing does; handing it to the dialog
    // outright pre-empted the twin (measured: the rotation test in
    // dialogs.spec.ts).
    const lost = () => {
      const active = document.activeElement as HTMLElement | null;
      return (
        active === document.body ||
        (active !== null && dialog.contains(active) && (active.matches(":disabled") || active.hidden))
      );
    };
    const observer = new MutationObserver(() => {
      if (lost()) dialog.focus();
    });
    const onFocusOut = (event: FocusEvent) => {
      if (event.relatedTarget !== null) return;
      const keys = focusKeysOf(event.target as Element | null);
      queueMicrotask(() => {
        if (document.activeElement !== document.body) return;
        if (!focusFirst(keys)) dialog.focus();
      });
    };
    dialog.addEventListener("focusout", onFocusOut);
    // Attributes as well as children, and this is not belt-and-braces: every
    // dialog here disables its submit button while the request is in flight, and
    // *disabling the focused element* drops focus to <body> exactly as removing
    // it does — measured in Chromium, where a childList-only observer sees
    // nothing. Tab to Submit and press Enter is the most ordinary keyboard path
    // through this application, and it was the one still escaping.
    //
    // Filtered rather than `attributes: true`, which would wake this on every
    // hover class change for nothing. The filter is exactly the attributes that
    // drop focus to <body>, which is measured rather than assumed: `disabled`
    // and `hidden` do, and `inert` does not — an inert node keeps `activeElement`
    // pointing at it, so the guard above is never satisfied and watching it woke
    // the observer for a case it could not act on. (`display: none` is the same
    // story and is also absent for the same reason.)
    observer.observe(dialog, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["disabled", "hidden"],
    });
    return () => {
      observer.disconnect();
      dialog.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = focusableWithin(dialog);
      if (focusable.length === 0) {
        // A dialog with nothing to focus still must not leak Tab to the page.
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      const backwards = event.shiftKey;

      // From outside, or from the container itself: where the engine would go
      // next is anyone's guess — re-enter at the end the direction names.
      if (!active || !dialog.contains(active) || active === dialog) {
        event.preventDefault();
        (backwards ? last : first).focus();
        return;
      }
      const index = focusable.indexOf(active);
      // Inside but not in the list (nothing here does that): the engine's own move.
      if (index === -1) return;
      const wraps = backwards ? index === 0 : index === focusable.length - 1;
      const next = wraps
        ? backwards
          ? last
          : first
        : focusable[backwards ? index - 1 : index + 1];
      // A segmented field keeps its own Tab until its last part, and only the
      // engine knows which part has focus — so the move is the engine's. But
      // where it lands when it *leaves* the field is the trap's to check: WebKit
      // left the order form's arrival date for the first line's type select and
      // passed *Add line* over, inside the dialog the whole time (Codex #272,
      // finding 2). A move between parts fires no `focusin` out here (both ends
      // retarget to the one input); the move that leaves does.
      //
      // The invariant (finding 3): **a pending correction is consumed by its
      // own departure and governs no later focus change.** The first version
      // removed itself on a zero-delay timer alone, and a timer does not
      // confine it to one key's task: under a burst of native Tabs several
      // were pending at once, each holding a different next stop, and they
      // sent focus back and forth between two fields until the page stalled.
      // So the listener removes itself *before* it sends focus anywhere, on the
      // first arrival that is not the field itself; the timer only clears one
      // whose Tab stayed inside the field. Wrapping from the last control stays
      // the trap's, as it always was.
      if (!wraps && active.matches(SEGMENTED)) {
        const reconcile = (arrived: FocusEvent) => {
          if (arrived.target === active) return;
          dialog.removeEventListener("focusin", reconcile);
          if (arrived.target !== next) next.focus();
        };
        dialog.addEventListener("focusin", reconcile);
        setTimeout(() => dialog.removeEventListener("focusin", reconcile), 0);
        return;
      }
      // Hand-driven where an engine might not stop (#267); the engine's own
      // move where every engine makes the same one.
      if (wraps || !next.matches(ENGINE_TABS_TO)) {
        event.preventDefault();
        next.focus();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const deleteAction = destructive && (
    <ActionButton action={destructive} variant="danger" focusKey={DELETE_FOCUS} />
  );

  // Portalled to <body> so the dialog sits outside the subtree it inerts —
  // rendered in place, marking the page inert would disable the dialog too.
  //
  // Three frames from one tree (§13.7, #259). The desktop's: a centred panel in
  // an overlay that scrolls, the actions the panel's last row. The phone's, by
  // `max-md:` alone so that a turn across the line keeps every node — the Close
  // that opened, the field being typed in, the primary action: the overlay is
  // the screen, the panel a column filling it, its head and its action bar
  // fixed by the column and its body the one scroller. And the bottom sheet,
  // the phone's too, risen from the foot instead. Nothing inside the panel is
  // `position: fixed`, so the trap's `offsetParent` filter sees every control.
  const frame = sheet
    ? {
        overlay: "items-end",
        // `break-words`, here and on the phone's full-screen frame: a dialog is
        // a portal beside `#root`, so it inherits nothing from the phone shell's
        // `main`, which says why (Codex #274, finding 3).
        panel: `flex max-h-[calc(100dvh-3rem)] w-full max-w-xl flex-col rounded-t-lg border border-b-0 border-border-strong bg-surface break-words focus:outline-none ${actions ? "" : "pb-safe"}`,
        head: "mb-3 px-4 pt-3",
        body: "min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-4 pb-5",
        foot: BAR_CLASS,
        button: BAR_BUTTON_CLASS,
      }
    : {
        overlay:
          "items-start overflow-y-auto p-4 pt-12 max-md:items-stretch max-md:overflow-hidden max-md:bg-surface max-md:p-0",
        panel: `w-full bg-surface focus:outline-none md:rounded-lg md:border md:border-border-strong md:p-5 ${
          wide ? "md:max-w-3xl" : "md:max-w-md"
        } max-md:flex max-md:min-h-0 max-md:flex-col max-md:break-words ${actions ? "" : "max-md:pb-safe"}`,
        head: "md:mb-4 max-md:h-14 max-md:border-b max-md:border-rule max-md:px-4",
        // `scroll-py`: a field scrolled back into view under a raised keyboard
        // keeps a line's breath from the head and the bar.
        body: "max-md:min-h-0 max-md:flex-1 max-md:scroll-py-4 max-md:overflow-y-auto max-md:overscroll-y-contain max-md:px-4 max-md:py-4",
        // The desktop's row is what every form drew at its end: 16 px under the
        // last field, Delete at the start, Cancel and the primary at the end.
        foot: `md:mt-4 md:flex md:items-center md:gap-2 ${PHONE_BAR_CLASS}`,
        button: PHONE_BAR_BUTTON_CLASS,
      };

  return createPortal(
    <div
      className={`fixed inset-0 z-40 flex justify-center bg-backdrop ${frame.overlay}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={frame.panel}
      >
        <div className={`flex shrink-0 items-center justify-between ${frame.head}`}>
          <h2 className="text-lg font-semibold text-text max-md:min-w-0 max-md:truncate">{title}</h2>
          {/* 24 px for a mouse; under `touch:` a 44 px target around the same
              icon (§13.7), its extra 10 px a side taken back as margin so the
              title row keeps its height. */}
          <button
            onClick={onClose}
            aria-label={t("common.close")}
            className="shrink-0 rounded-sm p-1 text-faint hover:bg-chip hover:text-text touch:-m-2.5 touch:p-3.5"
          >
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className={`@container ${frame.body}`}>
          {children}
          {/* The phone's Delete: the last thing in the form, under the fields
              it destroys, and never in the bar below. */}
          {deleteAction && <div className="mt-4 md:hidden">{deleteAction}</div>}
        </div>
        {actions && (
          <div className={frame.foot}>
            {destructive && (
              <ActionButton
                action={destructive}
                variant="danger"
                focusKey={DELETE_FOCUS}
                className="me-auto max-md:hidden"
              />
            )}
            <ActionButton
              action={actions.secondary}
              variant="secondary"
              className={`ms-auto max-md:ms-0 ${frame.button}`}
            />
            <ActionButton action={actions.primary} variant="primary" className={frame.button} />
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

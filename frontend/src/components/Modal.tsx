import type { ReactNode } from "react";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { focusByKey, focusKeyOf } from "../lib/focusKey";

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
 *  opener's `data-focus-key` (`lib/focusKey.ts` says why a key and not the
 *  name). An opener with no key is left as it always was — focused if it is
 *  still there, and otherwise wherever the browser puts focus; a control that
 *  is drawn differently per shell and opens a dialog owes itself a key, and
 *  lists.spec.ts's rotation test is where a missing one shows. */
function restoreFocus(opener: HTMLElement | null, key: string | null): void {
  if (opener?.isConnected) opener.focus();
  else if (key !== null) focusByKey(key);
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
  sheet = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  /** A bottom sheet (§13.7): the same dialog — focus trap, Escape, inert page —
   *  risen from the foot of the screen, where a thumb is. The filter sheet's. */
  sheet?: boolean;
}) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Captured before focus moves, so closing returns the user to the control
    // they opened this from rather than to the top of the document.
    const opener = document.activeElement as HTMLElement | null;
    const openerKey = focusKeyOf(opener);
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
      restoreFocus(opener, openerKey);
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
    const observer = new MutationObserver(() => {
      if (document.activeElement === document.body) dialog.focus();
    });
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
    return () => observer.disconnect();
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
      const active = document.activeElement;
      const inside = dialog.contains(active);

      if (event.shiftKey) {
        // From the container, backwards leaves the dialog — wrap to the end.
        if (!inside || active === first || active === dialog) {
          event.preventDefault();
          last.focus();
        }
      } else if (!inside || active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Portalled to <body> so the dialog sits outside the subtree it inerts —
  // rendered in place, marking the page inert would disable the dialog too.
  return createPortal(
    <div
      className={`fixed inset-0 z-40 flex justify-center bg-backdrop ${
        sheet ? "items-end" : "items-start overflow-y-auto p-4 pt-12"
      }`}
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
        className={
          sheet
            ? // Never taller than the screen less a strip of the page above it;
              // the sheet scrolls inside itself. Its foot clears the home
              // indicator (`pb-safe`), as the tab bar it covers does.
              "pb-safe max-h-[calc(100dvh-3rem)] w-full max-w-xl overflow-y-auto rounded-t-lg border border-b-0 border-border-strong bg-surface px-4 pt-3 focus:outline-none"
            : `w-full ${wide ? "max-w-3xl" : "max-w-md"} rounded-lg border border-border-strong bg-surface p-5 focus:outline-none`
        }
      >
        <div className={`flex items-center justify-between ${sheet ? "mb-3" : "mb-4"}`}>
          <h2 className="text-lg font-semibold text-text">{title}</h2>
          {/* 24 px for a mouse; under `touch:` a 44 px target around the same
              icon (§13.7), its extra 10 px a side taken back as margin so the
              title row keeps its height. */}
          <button
            onClick={onClose}
            aria-label={t("common.close")}
            className="rounded-sm p-1 text-faint hover:bg-chip hover:text-text touch:-m-2.5 touch:p-3.5"
          >
            <X size={16} aria-hidden />
          </button>
        </div>
        {sheet ? <div className="pb-5">{children}</div> : children}
      </div>
    </div>,
    document.body,
  );
}

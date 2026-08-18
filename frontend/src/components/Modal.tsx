import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

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

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Captured before focus moves, so closing returns the user to the control
    // they opened this from rather than to the top of the document.
    const opener = document.activeElement as HTMLElement | null;
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
      opener?.focus?.();
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
      className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-12"
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
        className={`w-full ${wide ? "max-w-3xl" : "max-w-md"} rounded-xl bg-white p-5 shadow-xl focus:outline-none`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

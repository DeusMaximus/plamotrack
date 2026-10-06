import { useCallback, useLayoutEffect, useRef, type ReactNode } from "react";

import { focusFirst, focusKeysOf } from "../lib/focusKey";
import { RefitContext } from "../lib/refit";

/** Fold to fit (design §13.7, #329). A list table from 768 px folds a column
 *  away — to a second line under the name, under a chip, into the expanded
 *  lines — when its box is too narrow for it. The line it folded at used to be
 *  a container query in rem, measured once with one set of rows; a line is a
 *  guess about rows nobody has typed yet, and words that each stay plain under
 *  their budgets (`Measured`) still add up past one (Codex #328, round 2). So
 *  the table folds by measurement: at stage 0 it is whole, each stage folds
 *  more, and the stage drawn is the first one at which nothing is wider than
 *  the box — or the last, past which the box scrolls.
 *
 *  **How a stage is chosen.** From stage 0 up, every time: set the stage on the
 *  box, ask whether it overflows (a synchronous layout), stop at the first that
 *  fits. Never from the stage that is drawn, never "fold if over, unfold if
 *  under": that oscillates, a stage that fits deciding it can unfold and the
 *  unfolded one deciding it must fold (Codex, on #329: 60 flips in 60 frames).
 *  This way the answer depends on the box's width and the rows, never on
 *  history, so the same inputs choose the same stage — and since a wider box
 *  never needs more folding, a fold that changes the page's height, and with it
 *  a classic scrollbar and the box's width, settles on the next pass instead of
 *  bouncing. At most `stages + 1` layouts a pass.
 *
 *  **The stage is an attribute, not React state**: `data-fold-1`, `data-fold-2`
 *  on the box, cumulative, read by `group-data-fold-1/fold:hidden` and its
 *  kin. A state would re-render the page to try a stage; this is a few
 *  attributes and a layout, inside one task, before the frame is painted.
 *
 *  **When a pass runs** — the inputs, each of which can change on its own:
 *  - the box's width: a `ResizeObserver` on a sentinel, a zero-height block that
 *    is as wide as the box and nothing else. Not on the box: a fold changes the
 *    box's height, and an observation changed by its own callback is one the
 *    browser cannot deliver this frame ("ResizeObserver loop completed with
 *    undelivered notifications"). Not on the table: a `w-full` table that
 *    folded keeps the box's width when its content shrinks, so it reports
 *    nothing when unfolding becomes possible (Codex, on #329: zero callbacks
 *    over 30 frames);
 *  - the rows: every commit of this component — a page, a filter, a tab, an
 *    order's lines opened — renders it, its children being new;
 *  - a value deciding to break (`Measured`, which commits alone): it calls
 *    `useRefit()`'s function when its decision changes;
 *  - a web font arriving: each face's `loaded` promise. Not the font set's
 *    `loadingdone` event, which WebKit does not fire for a stylesheet's faces
 *    (measured: no `loading`, no `loadingdone`, the table left folded where
 *    Inter fit it whole); a face's promise settles in both engines.
 *  Each schedules one pass in a microtask, so a commit that touches a hundred
 *  cells measures once — after React's synchronous re-renders, before paint.
 *
 *  **Focus: the pass hands the keyboard on itself.** A pass that ends with the
 *  focused control hidden gives the keyboard to whatever carries its key now
 *  (`lib/focusKey.ts`), before the frame is painted. The focus hook's observer
 *  would hear the control lose its box too — but not always in time: a turn
 *  across the sidebar's line folds the table for one frame at the sidebar's
 *  box, before the shell changes, and unfolds it the next. The hook moves the
 *  keyboard to the folded copy from inside its own delivery and can only start
 *  watching that copy a frame later — by when the copy is hidden already, and a
 *  hidden box reports nothing to a new observation. The keyboard sat on
 *  `<body>` for a frame or more (CI caught it one run in five, on #330). The
 *  fold knows when it hides the focused control; it says so. */

/** Whether the box is wider inside than out — the question the e2e asks too. */
const boxOverflows = (box: HTMLElement): boolean => box.scrollWidth > box.clientWidth;

function setStage(box: HTMLElement, stages: number, stage: number): void {
  for (let n = 1; n <= stages; n += 1) box.toggleAttribute(`data-fold-${n}`, n <= stage);
}

function chooseStage(
  box: HTMLElement,
  stages: number,
  floor: number,
  overflows: (box: HTMLElement) => boolean,
): void {
  // Not drawn — a hidden tab, a page leaving — has no width to fit; it is
  // measured when it is drawn again, which its sentinel reports.
  if (box.getClientRects().length === 0) return;
  let stage = floor;
  for (; stage < stages; stage += 1) {
    setStage(box, stages, stage);
    if (!overflows(box)) return;
  }
  setStage(box, stages, stage);
}

type FoldToFitProps = {
  /** How many stages the table can fold to; stage 0 is the whole table. */
  stages: number;
  /** The stage it may not unfold past here — Access tokens' cards on a phone. */
  floor?: number;
  /** What must fit: by default the box itself. */
  overflows?: (box: HTMLElement) => boolean;
  className?: string;
  children: ReactNode;
};

/** The box a folding table is drawn in: it carries the stage, and the
 *  `group/fold` the table's cells read it by. */
export function FoldToFit({ stages, floor = 0, overflows = boxOverflows, className, children }: FoldToFitProps) {
  const box = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const inputs = useRef({ stages, floor, overflows });
  const queued = useRef(false);
  useLayoutEffect(() => {
    inputs.current = { stages, floor, overflows };
  });
  const refit = useCallback(() => {
    if (queued.current) return;
    queued.current = true;
    queueMicrotask(() => {
      queued.current = false;
      const element = box.current;
      if (!element) return;
      chooseStage(element, inputs.current.stages, inputs.current.floor, inputs.current.overflows);
      const active = document.activeElement;
      if (active && element.contains(active) && active.getClientRects().length === 0) focusFirst(focusKeysOf(active));
    });
  }, []);
  // Every commit: the rows this was given may be different ones.
  useLayoutEffect(() => refit());
  useLayoutEffect(() => {
    const observer = new ResizeObserver(refit);
    if (sentinel.current) observer.observe(sentinel.current);
    let live = true;
    for (const face of document.fonts ?? []) {
      if (face.status !== "loaded") face.loaded.then(() => live && refit(), () => undefined);
    }
    return () => {
      live = false;
      observer.disconnect();
    };
  }, [refit]);
  return (
    <RefitContext.Provider value={refit}>
      <div ref={box} className={`group/fold ${className ?? ""}`}>
        <div ref={sentinel} aria-hidden className="h-0" />
        {children}
      </div>
    </RefitContext.Provider>
  );
}

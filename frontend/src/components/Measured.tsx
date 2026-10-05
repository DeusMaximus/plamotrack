import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

/** What a table cell cannot know gives way by its value (design §13.7, "What a
 *  line cannot know gives way instead"; #258, #323). A table sizes a column to
 *  the widest piece of text in it the browser will not break, so one word wider
 *  than the box — a USPS tracking number, a product code run together as a name
 *  — holds the whole table past its box, and the row's edit control with it.
 *
 *  So a value whose widest unbroken piece is wider than its **budget** may break
 *  anywhere, down to lines as wide as its **floor** and no narrower; one within
 *  the budget is left exactly as it was, a plain word, and the table's ordinary
 *  rows lay out as they always did. Budgets are in em of the text's own font:
 *
 *  - `orderNumber`, `tracking`: what the Orders fold lines were measured with
 *    (#266) — a tracking number of thirteen characters with nowhere to break
 *    (Japan Post's, 8.2em), an order number that breaks at its hyphens into
 *    pieces no wider than "12345678-" (5.9em). The floor is the budget.
 *  - `name`: the widest word an ordinary name has, with room — "(Unidentified"
 *    is the widest of 116 real kit names (#323), 6.2em in Inter's medium.
 *  - `text`: every other free-text field a cell says — a category, a
 *    manufacturer, a grade, a scale, a note, an address, a delivery service —
 *    with room over "Workstation", the widest word of a real catalog's
 *    categories (5.7em). A shop's address is past it — a real one, thirty-five
 *    characters with nowhere to break, is 18em at the address's 12 px —
 *    and breaks, which is the point: it held its column open at that width.
 *
 *  A name's and a text's floor is lower than its budget: a row of a table has
 *  as many of them as it has columns, and one unbroken value in each — in
 *  different rows, which is the same thing to the table — has to fit the
 *  narrowest box a table is drawn in (638 px, beside the rail at 768): with a
 *  4em floor for every one, Display's seven columns, five of them free text,
 *  were 4 px past it (before it folded).
 *
 *  **A budget bounds one value, never a row** (Codex #328, finding 1). Words
 *  that each stay plain still add up: a table's minimum is the sum of its
 *  columns' widest words, and one ordinary Display row overflowed at 768. So a
 *  table with several free-text columns owes a fold line measured with a word
 *  just under its budget in every one of them at once — above it any mix of
 *  values fits — as Inventory's Tools and Display have (`InventoryPage.tsx`).
 *
 *  **Measured, not counted** (Codex #266, finding 5): the width of the widest
 *  piece the browser will not break, from a copy laid out at `min-content` in a
 *  `TableRuler` — one box per table, out of flow, no size, clipped — in the
 *  drawn text's own font, copied from it when measured, with the text as a
 *  pseudo-element's content rather than text of its own. Every one of those is
 *  a lesson. A copy laid out inside the cell was scrollable overflow; inside a
 *  fold's `display: none` half it had no width to measure; as DOM text it was
 *  the deepest match for `getByText`, which prefers it to the visible text; and
 *  a canvas's `measureText` cannot be told the table's `tabular-nums`, so its
 *  digits are narrower than the cell's. The font is the drawn text's because a
 *  name is medium and a grade chip semibold and tracked, where the ruler is the
 *  table's.
 *
 *  By the value and not for every row, for two reasons: `overflow-wrap:
 *  anywhere` lowers a column's minimum width and a table squeezes every column
 *  that has give; and in Chromium it also changes the text's shaping — kerning
 *  stops at a break opportunity, and there is one after every character — so
 *  "EJ482113905JP" is 105 px as a plain word and 110 px under `anywhere`, and
 *  wrapped at the cell's edge with nothing squeezed at all. */
const BUDGETS = {
  orderNumber: { em: 6, wide: "inline-block min-w-[6em] whitespace-normal wrap-anywhere" }, // "12345678-" is 5.9em
  tracking: { em: 8.3, wide: "inline-block min-w-[8.3em] whitespace-normal wrap-anywhere" }, // Japan Post's 13 are 8.2em
  name: { em: 10, wide: "inline-block min-w-[4em] whitespace-normal wrap-anywhere" }, // "(Unidentified" is 6.2em
  text: { em: 8, wide: "inline-block min-w-[3em] whitespace-normal wrap-anywhere" }, // "Workstation" is 5.7em
} as const;

export type Budget = keyof typeof BUDGETS;

/** What the copy takes from the drawn text: everything that sets a glyph's width. */
const FONT_PROPERTIES = [
  "fontFamily",
  "fontSize",
  "fontStyle",
  "fontWeight",
  "fontStretch",
  "fontKerning",
  "fontVariantNumeric",
  "fontFeatureSettings",
  "letterSpacing",
  "wordSpacing",
  "textTransform",
] as const;

const RulerContext = createContext<HTMLElement | null>(null);

/** Where a table's values are measured: rendered once inside the table's box.
 *  `Measured` puts its copy here through a portal. A `Measured` with no ruler
 *  above it — a card's lines — measures nothing and stays a plain word, which
 *  there is inside the phone shell's `break-words`. */
export function TableRuler({ children }: { children: ReactNode }) {
  const [ruler, setRuler] = useState<HTMLElement | null>(null);
  return (
    <RulerContext.Provider value={ruler}>
      {children}
      <div ref={setRuler} aria-hidden className="absolute h-0 w-0 overflow-hidden" />
    </RulerContext.Provider>
  );
}

export function Measured({ text, kind }: { text: string; kind: Budget }) {
  const ruler = useContext(RulerContext);
  const drawn = useRef<HTMLSpanElement>(null);
  const sizer = useRef<HTMLSpanElement>(null);
  const [wide, setWide] = useState(false);
  useLayoutEffect(() => {
    const element = sizer.current;
    const source = drawn.current;
    if (!element || !source) return;
    const measure = () => {
      const style = getComputedStyle(source);
      for (const property of FONT_PROPERTIES) element.style[property] = style[property];
      const em = parseFloat(getComputedStyle(element).fontSize);
      setWide(element.getBoundingClientRect().width / em > BUDGETS[kind].em);
    };
    measure();
    // And when its size changes — the web font arriving after the first paint.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, kind, ruler]);
  return (
    <>
      <span ref={drawn} className={wide ? BUDGETS[kind].wide : undefined}>
        {text}
      </span>
      {ruler &&
        createPortal(
          <span
            ref={sizer}
            data-text={text}
            className="invisible block w-min whitespace-normal before:content-[attr(data-text)]"
          />,
          ruler,
        )}
    </>
  );
}

/** The shell's two lines are drawn in two languages — `shell.ts` asks
 *  `matchMedia`, the stylesheet's `max-md:` and `touch:` utilities ask CSS —
 *  and neither can import the other. This file is what holds them to one
 *  answer (design §13.7): the widths as literals from the decision record, the
 *  queries `shell.ts` hands `matchMedia`, and the stylesheet read as text. */

/// <reference types="node" />
// Node's fs, in this file alone, as tokens.test.ts does: vitest replaces every
// CSS id with an empty module, so `?raw` cannot read the stylesheet.
import { readFileSync, readdirSync } from "node:fs";

import { afterEach, describe, expect, it, vi } from "vitest";

import { RAIL_QUERY, SIDEBAR_QUERY, currentShell, resolveShell } from "./shell";

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8");

/** `matchMedia` for a viewport this many px wide, at the default 16 px rem —
 *  min-width queries in rem or px, which is all the shell asks. */
function viewport(width: number) {
  return vi.fn((query: string) => {
    const parsed = /^\(min-width: ([\d.]+)(rem|px)\)$/.exec(query);
    if (!parsed) throw new Error(`unexpected media query: ${query}`);
    const min = Number(parsed[1]) * (parsed[2] === "rem" ? 16 : 1);
    return { matches: width >= min, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("the three shells", () => {
  it("is decided by the two lines alone", () => {
    expect(resolveShell(false, false)).toBe("phone");
    expect(resolveShell(true, false)).toBe("rail");
    expect(resolveShell(true, true)).toBe("sidebar");
  });

  // Both sides of both lines, and the devices the decision names: an iPad mini
  // in portrait is a phone, an 11-inch iPad is the rail both ways, a 13-inch
  // one in landscape is the desktop.
  it.each([
    [320, "phone"],
    [390, "phone"],
    [744, "phone"],
    [767, "phone"],
    [768, "rail"],
    [820, "rail"],
    [1180, "rail"],
    [1279, "rail"],
    [1280, "sidebar"],
    [1366, "sidebar"],
    [2560, "sidebar"],
  ] as const)("%i px is the %s shell", (width, shell) => {
    vi.stubGlobal("matchMedia", viewport(width));
    expect(currentShell()).toBe(shell);
  });

  it("reads a missing matchMedia as the layout that predates the shells", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(currentShell()).toBe("sidebar");
  });
});

describe("the stylesheet draws the same lines", () => {
  it("asks for Tailwind's md and xl, which the stylesheet leaves at their defaults", () => {
    // 48rem and 80rem are Tailwind's stock `md` and `xl`. A `--breakpoint-*`
    // override would move `max-md:` away from the hook without touching it.
    expect(RAIL_QUERY).toBe("(min-width: 48rem)");
    expect(SIDEBAR_QUERY).toBe("(min-width: 80rem)");
    expect(stylesheet).not.toMatch(/--breakpoint-/);
  });

  it("defines `touch:` as the phone shell or a coarse pointer", () => {
    const variant = /@custom-variant touch \{\s*@media ([^{]+?)\s*\{\s*@slot;\s*\}\s*\}/.exec(stylesheet);
    expect(variant?.[1]).toBe("(width < 48rem), (pointer: coarse)");
  });

  it("keeps the tab bar clear of the home indicator", () => {
    // The inset is only ever non-zero with `viewport-fit=cover`, which
    // install.test.ts holds index.html to.
    expect(stylesheet).toMatch(/@utility pb-safe \{\s*padding-bottom: env\(safe-area-inset-bottom\);/);
    expect(stylesheet).toMatch(
      /@utility pb-tab-bar \{\s*padding-bottom: calc\(5rem \+ env\(safe-area-inset-bottom\)\);/,
    );
  });
});

describe("a row of fields folds by its box", () => {
  // About 100 px a field — 6.25rem — and the row's 0.75rem gaps (#259): three
  // across needs 20.25rem, two 13.25rem. A container query, so the box asked
  // is the dialog's body or the order line's card, whatever the viewport.
  it.each([
    ["stack-3", 3, 20.25],
    ["stack-2", 2, 13.25],
  ] as const)("`%s:` is a container under %i fields' room", (variant, fields, rem) => {
    expect(rem).toBe(fields * 6.25 + (fields - 1) * 0.75);
    const block = new RegExp(`@custom-variant ${variant} \\{\\s*@container \\(width < ([\\d.]+)rem\\) \\{\\s*@slot;\\s*\\}\\s*\\}`).exec(stylesheet);
    expect(block?.[1]).toBe(String(rem));
  });
});

describe("viewport height", () => {
  it("is never `vh`: on iOS that is the large viewport, behind Safari's toolbar", () => {
    // `h-dvh` / `min-h-dvh` are the spellings (§13.7). This is the guard that
    // keeps the sidebar's foot and the sign-in card from going back under it.
    const src = new URL("../", import.meta.url);
    const offenders: string[] = [];
    for (const entry of readdirSync(src, { recursive: true, withFileTypes: true })) {
      if (!entry.isFile() || !/\.(tsx|css)$/.test(entry.name)) continue;
      const path = `${entry.parentPath}/${entry.name}`;
      readFileSync(path, "utf8")
        .split("\n")
        .forEach((line, index) => {
          // Code, not the comments that explain the rule.
          if (/^\s*(?:\/\/|\/?\*|\{\/\*)/.test(line)) return;
          if (/(?<![\w-])(?:min-|max-)?h-screen(?![\w-])|\b100vh\b/.test(line)) {
            offenders.push(`${path.slice(src.pathname.length)}:${index + 1}`);
          }
        });
    }
    expect(offenders).toEqual([]);
  });
});

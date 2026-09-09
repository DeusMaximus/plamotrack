/** The Workbench tokens (design §13.1) as a contract, not a palette: every pair
 *  the components put together has to read. Parsed from `index.css` itself, in
 *  both themes, with translucent grounds composited the way the browser does
 *  (a chip is 5% black over the surface; an error banner 10% danger over it).
 *  WCAG 2.2's floors: 4.5:1 for text, 3:1 for UI components and inactive or
 *  decorative content, which is `--faint`'s documented role. Codex found the
 *  light status text at 3.45–4.36:1 on #235 (P3-1) — this is the assertion that
 *  fails on that, and on the next token someone tunes by eye. */

/// <reference types="node" />
// Node's fs, in this file alone: vitest replaces every CSS id with an empty
// module whatever the query, so `?raw` cannot read the stylesheet the way
// theme.test.ts reads the head script. The app tsconfig keeps Node's types out
// of app code on purpose; the reference above scopes them to this test.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8");

type Rgb = [number, number, number];
type Colour = { rgb: Rgb; alpha: number };
type Tokens = Record<string, Colour>;

function parseColour(value: string): Colour | null {
  const hex = /^#([0-9a-f]{6})$/i.exec(value.trim());
  if (hex) {
    const n = parseInt(hex[1], 16);
    return { rgb: [(n >> 16) & 255, (n >> 8) & 255, n & 255], alpha: 1 };
  }
  const rgb = /^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+))?\s*\)$/i.exec(value.trim());
  if (rgb) {
    return {
      rgb: [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])],
      alpha: rgb[4] === undefined ? 1 : Number(rgb[4]),
    };
  }
  return null;
}

/** The custom properties of one selector block, colours only. */
function block(selector: string): Tokens {
  const start = stylesheet.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`no ${selector} block in index.css`);
  const body = stylesheet.slice(start, stylesheet.indexOf("}", start));
  const tokens: Tokens = {};
  for (const match of body.matchAll(/--([a-z][a-z0-9-]*):\s*([^;]+);/g)) {
    const colour = parseColour(match[2]);
    if (colour) tokens[match[1]] = colour;
  }
  return tokens;
}

function over(top: Colour, ground: Rgb): Rgb {
  return top.rgb.map((c, i) => c * top.alpha + ground[i] * (1 - top.alpha)) as Rgb;
}

function luminance([r, g, b]: Rgb): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const STATUSES = ["pre-ordered", "ordered", "in-transit", "backlog", "building", "complete"];

/** Every (foreground, ground, floor) the components compose, named. */
function pairs(t: Tokens): { name: string; fg: Rgb; ground: Rgb; floor: number }[] {
  const solid = (name: string): Rgb => {
    if (!t[name]) throw new Error(`token --${name} missing`);
    return t[name].rgb;
  };
  const surface = solid("surface");
  const surfaceAlt = solid("surface-alt");
  const bg = solid("bg");
  const chipOnSurface = over(t.chip, surface);
  const chipOnAlt = over(t.chip, surfaceAlt);
  const out: { name: string; fg: Rgb; ground: Rgb; floor: number }[] = [];
  const text = (name: string, fg: Rgb, ground: Rgb) => out.push({ name, fg, ground, floor: 4.5 });
  const ui = (name: string, fg: Rgb, ground: Rgb) => out.push({ name, fg, ground, floor: 3 });

  out.push({ name: "text on surface", fg: solid("text"), ground: surface, floor: 7 });
  for (const ground of [["surface", surface], ["surface-alt", surfaceAlt], ["bg", bg]] as const) {
    text(`muted on ${ground[0]}`, solid("muted"), ground[1]);
    ui(`faint on ${ground[0]}`, solid("faint"), ground[1]);
    text(`danger on ${ground[0]}`, solid("danger"), ground[1]);
  }
  for (const status of STATUSES) {
    const fg = solid(`status-${status}`);
    text(`status-${status} on the chip`, fg, chipOnSurface);
    text(`status-${status} on the chip over surface-alt`, fg, chipOnAlt);
    text(`status-${status} on surface`, fg, surface);
    text(`status-${status} on surface-alt`, fg, surfaceAlt);
  }
  text("accent-ink on accent (the primary button)", solid("accent-ink"), solid("accent"));
  text("accent on surface (links)", solid("accent"), surface);
  text("accent on bg", solid("accent"), bg);
  text("accent on accent-soft over bg (the active nav row)", solid("accent"), over(t["accent-soft"], bg));
  text("accent on accent-soft over surface (a picked catalog item)", solid("accent"), over(t["accent-soft"], surface));
  text("danger on 10% danger over surface (the error banner)", solid("danger"), over({ rgb: solid("danger"), alpha: 0.1 }, surface));
  text("muted on the chip", solid("muted"), chipOnSurface);
  return out;
}

describe.each([
  ["dark", ":root"],
  ["light", '[data-theme="light"]'],
])("%s theme", (_theme, selector) => {
  const tokens = block(selector);

  it("declares the six status colours", () => {
    for (const status of STATUSES) expect(tokens[`status-${status}`], status).toBeDefined();
  });

  it("every composed pair meets its WCAG floor", () => {
    const failures = pairs(tokens)
      .map((pair) => ({ ...pair, ratio: contrast(pair.fg, pair.ground) }))
      .filter((pair) => pair.ratio < pair.floor)
      .map((pair) => `${pair.name}: ${pair.ratio.toFixed(2)} < ${pair.floor}`);
    expect(failures).toEqual([]);
  });
});

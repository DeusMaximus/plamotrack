/** The URL readers are total (#232): every value a link, a bookmark or a hand-
 *  typed address can carry reads as something the page can show. Value axis:
 *  missing, empty, garbage, a valid value; for the page also 0, negative,
 *  huge, non-numeric; and the slice a clamped page yields. */

import { describe, expect, it } from "vitest";

import { pageWindow, paginate, readEnum, readPage } from "./listState";

const SORTS = ["created", "recent", "name"] as const;

describe("readEnum", () => {
  it.each([
    [null, "created"],
    ["", "created"],
    ["RECENT", "created"],
    ["recent ", "created"],
    ["garbage", "created"],
    ["recent", "recent"],
    ["name", "name"],
  ])("%j → %s", (raw, expected) => {
    expect(readEnum(raw, SORTS, "created")).toBe(expected);
  });
});

describe("readPage", () => {
  it.each([
    [null, 1],
    ["", 1],
    ["0", 1],
    ["-2", 1],
    ["abc", 1],
    ["2.5", 1],
    ["3", 3],
    ["1000000", 1],
    ["999999", 999999],
  ])("%j → %d", (raw, expected) => {
    expect(readPage(raw)).toBe(expected);
  });
});

describe("paginate", () => {
  const rows = Array.from({ length: 23 }, (_, index) => index + 1);

  it("slices the requested page", () => {
    expect(paginate(rows, 2, 10)).toEqual({
      rows: [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
      total: 23,
      page: 2,
      pages: 3,
      from: 11,
      to: 20,
    });
  });

  it("clamps a page past the end onto the last page", () => {
    expect(paginate(rows, 9, 10)).toMatchObject({ rows: [21, 22, 23], page: 3, from: 21, to: 23 });
  });

  it("clamps a page before the start onto the first", () => {
    expect(paginate(rows, 0, 10)).toMatchObject({ page: 1, from: 1, to: 10 });
  });

  it("an empty list is one empty page", () => {
    expect(paginate([], 4, 10)).toEqual({ rows: [], total: 0, page: 1, pages: 1, from: 0, to: 0 });
  });
});

describe("pageWindow", () => {
  it("lists every page when there are few", () => {
    expect(pageWindow(3, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });
  it("shows the ends and a window with gaps", () => {
    expect(pageWindow(1, 11)).toEqual([1, 2, 3, 4, 5, null, 10, 11]);
    expect(pageWindow(6, 11)).toEqual([1, 2, null, 5, 6, 7, null, 10, 11]);
    expect(pageWindow(11, 11)).toEqual([1, 2, null, 7, 8, 9, 10, 11]);
  });
});

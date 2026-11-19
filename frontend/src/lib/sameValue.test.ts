import { describe, expect, it } from "vitest";

import { sameValue } from "./sameValue";

describe("sameValue", () => {
  it.each([
    ["", ""],
    [null, null],
    [0, 0],
    [NaN, NaN],
    [[], []],
    [{}, {}],
    [{ a: 1, b: [1, { c: "x" }] }, { b: [1, { c: "x" }], a: 1 }],
  ])("%j equals %j", (a, b) => {
    expect(sameValue(a, b)).toBe(true);
  });

  it.each([
    ["1", 1],
    ["", null],
    [null, undefined],
    [null, {}],
    [[], {}],
    [[1, 2], [2, 1]],
    [[1], [1, 1]],
    [{ a: 1 }, { a: 1, b: 2 }],
    [{ a: undefined }, { b: undefined }],
    [{ a: { b: "x" } }, { a: { b: "y" } }],
  ])("%j differs from %j", (a, b) => {
    expect(sameValue(a, b)).toBe(false);
    expect(sameValue(b, a)).toBe(false);
  });
});

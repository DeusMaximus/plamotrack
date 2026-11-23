import { describe, expect, it } from "vitest";

import { asTextareaValue, oneLine } from "./oneLine";

describe("oneLine", () => {
  it.each([
    ["", ""],
    ["Probe kit", "Probe kit"],
    ["Probe kit\nsecond line", "Probe kit second line"],
    ["Probe kit\r\nsecond line", "Probe kit second line"],
    ["Probe kit\rsecond line", "Probe kit second line"],
    ["a\n\nb", "a  b"],
    ["a\r\n\r\nb", "a  b"],
    ["\nlead and trail\r\n", " lead and trail "],
    ["tab\tstays", "tab\tstays"],
  ])("%j shows as %j", (stored, shown) => {
    expect(oneLine(stored)).toBe(shown);
  });
});

describe("asTextareaValue", () => {
  it.each([
    ["", ""],
    ["Blade chipped", "Blade chipped"],
    ["Blade chipped\nstill cuts", "Blade chipped\nstill cuts"],
    ["Blade chipped\r\nstill cuts", "Blade chipped\nstill cuts"],
    ["Blade chipped\rstill cuts", "Blade chipped\nstill cuts"],
    ["a\r\n\r\nb", "a\n\nb"],
    ["a\n\r\nb", "a\n\nb"],
    ["\r\nlead and trail\r\n", "\nlead and trail\n"],
    ["tab\tstays", "tab\tstays"],
  ])("%j is held as %j", (stored, held) => {
    expect(asTextareaValue(stored)).toBe(held);
  });
});

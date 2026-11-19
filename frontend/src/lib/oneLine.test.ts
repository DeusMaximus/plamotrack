import { describe, expect, it } from "vitest";

import { oneLine } from "./oneLine";

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

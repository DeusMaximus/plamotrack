/** Instance-wide presentation (#27): the language fallback rule, the document
 * direction metadata, and the format helpers under contrasting locales, zones,
 * date styles and hour cycles. Everything here is the pure half — the DOM and
 * i18next side effects of `applyInstanceSettings` are e2e's to observe (the
 * no-jsdom decision, #22).
 *
 * Byte-exact assertions only where ICU output is stable across Node versions
 * (dates, grouped numbers); time-of-day strings are asserted by their
 * load-bearing parts, because newer ICU swaps the space before am/pm for
 * U+202F and a byte pin would break on a Node upgrade for no behavioural
 * reason.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  formatDateTimeWith,
  formatDateWith,
  formatMoneyWith,
  formatNumberWith,
  formatDate,
} from "./format";
import {
  documentDirection,
  enabledLanguages,
  resetFormatPreferences,
  resolveLanguage,
  setFormatPreferences,
} from "./presentation";

afterEach(resetFormatPreferences);

const AU_DEFAULTS = { locale: "en-AU", timeZone: "UTC", dateStyle: "locale", hourCycle: "locale" };

describe("resolveLanguage (#27's fallback rule)", () => {
  it("resolves a shipped, enabled language as itself", () => {
    const resolved = resolveLanguage("en-AU");
    expect(resolved.fallback).toBe(false);
    expect(resolved.entry.tag).toBe("en-AU");
    expect(resolved.entry.nativeName).toBe("English (Australia)");
  });

  it("falls back to en-AU for a language this build doesn't ship, and says so", () => {
    const resolved = resolveLanguage("ja-JP");
    expect(resolved.fallback).toBe(true);
    expect(resolved.entry.tag).toBe("en-AU");
  });

  it("offers exactly the manifest's enabled languages", () => {
    expect(enabledLanguages().map((entry) => entry.tag)).toEqual(["en-AU"]);
  });
});

describe("document direction metadata", () => {
  it("maps rtl to rtl and everything else to ltr", () => {
    expect(documentDirection("rtl")).toBe("rtl");
    expect(documentDirection("ltr")).toBe("ltr");
    expect(documentDirection("")).toBe("ltr");
    expect(documentDirection("sideways")).toBe("ltr");
  });

  it("the fallback language is ltr", () => {
    expect(documentDirection(resolveLanguage("nonsense").entry.direction)).toBe("ltr");
  });
});

describe("dates and times under instance settings", () => {
  it("a plain calendar date renders as that day in every zone — the #114 rule's presentation twin", () => {
    for (const timeZone of ["UTC", "Australia/Sydney", "America/New_York"]) {
      expect(formatDateWith({ ...AU_DEFAULTS, timeZone }, "2026-03-14")).toBe("14/03/2026");
    }
  });

  it("an instant renders in the instance zone — the same moment is two calendar days", () => {
    const instant = "2026-03-14T02:00:00+00:00";
    expect(formatDateWith({ ...AU_DEFAULTS, timeZone: "Australia/Sydney" }, instant)).toBe(
      "14/03/2026",
    );
    expect(formatDateWith({ ...AU_DEFAULTS, timeZone: "America/New_York" }, instant)).toBe(
      "13/03/2026",
    );
  });

  it("the formatting locale changes punctuation, not the day", () => {
    expect(formatDateWith({ ...AU_DEFAULTS, locale: "de-DE" }, "2026-03-14")).toBe("14.3.2026");
  });

  it("an explicit date style renders through Intl's named styles", () => {
    expect(formatDateWith({ ...AU_DEFAULTS, dateStyle: "long" }, "2026-03-14")).toBe(
      "14 March 2026",
    );
  });

  it("the hour cycle decides 12- vs 24-hour output", () => {
    const prefs = { ...AU_DEFAULTS, timeZone: "Australia/Sydney" };
    const instant = "2026-03-14T04:00:00+00:00"; // 15:00 in Sydney
    const h23 = formatDateTimeWith({ ...prefs, hourCycle: "h23" }, instant);
    expect(h23).toContain("15:00");
    const h12 = formatDateTimeWith({ ...prefs, hourCycle: "h12" }, instant);
    expect(h12).toContain("3:00");
    expect(h12.toLowerCase()).toContain("pm");
  });

  it("an unservable zone degrades to the browser default instead of throwing", () => {
    expect(() =>
      formatDateWith({ ...AU_DEFAULTS, timeZone: "Not/A_Zone" }, "2026-03-14T02:00:00+00:00"),
    ).not.toThrow();
  });

  it("the degrade keeps a calendar date on the day it names (#174 review, P3-2)", () => {
    // West of UTC, where the unfixed degrade rendered the previous day — set
    // for this test only via vitest's typed stub (the suite has no node types);
    // Node re-reads TZ per formatter, so the degrade's default-zone rendering
    // observes it. Restored in the finally.
    vi.stubEnv("TZ", "America/New_York");
    try {
      const rendered = formatDateWith({ ...AU_DEFAULTS, locale: "not a locale!!" }, "2026-03-14");
      expect(rendered).toContain("14");
      expect(rendered).not.toContain("13");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("the module-level helpers read the applied preferences", () => {
    setFormatPreferences({
      formatting_locale: "de-DE",
      time_zone: "UTC",
      date_style: "locale",
      hour_cycle: "locale",
    });
    expect(formatDate("2026-03-14")).toBe("14.3.2026");
  });
});

describe("numbers and money under instance settings", () => {
  it("grouping follows the formatting locale", () => {
    expect(formatNumberWith("en-AU", 1234567)).toBe("1,234,567");
    expect(formatNumberWith("de-DE", 1234567)).toBe("1.234.567");
  });

  it("the locale styles money; the ISO 4217 exponent stays plamotrack's (§6)", () => {
    // The same stored minor amount, digit-for-digit, under every locale — only
    // the punctuation, symbol and placement may move.
    for (const locale of ["en-AU", "de-DE", "ja-JP"]) {
      const rendered = formatMoneyWith(locale, 499900, "AUD");
      expect(rendered.replace(/\D/g, "")).toBe("499900");
    }
    // Zero- and three-digit exponents survive locales whose defaults differ.
    expect(formatMoneyWith("de-DE", 1234, "JPY").replace(/\D/g, "")).toBe("1234");
    expect(formatMoneyWith("de-DE", 1234, "IQD").replace(/\D/g, "")).toBe("1234");
  });

  it("an unknown currency degrades to the plain-suffix fallback", () => {
    expect(formatMoneyWith("en-AU", 1234, "ZZZ")).toContain("ZZZ");
  });
});

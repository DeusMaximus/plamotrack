/** The browser half of the money conversions (#6).
 *
 * Every case here is read from `__fixtures__/money-cases.json`, which
 * `backend/tests/test_currency.py` reads too. That is the point: these two
 * implementations have to agree, and both defects found in this file so far — the
 * float rounding at the halfway point, and exponent notation parsing as zero —
 * were cases where they didn't, caught by a person rather than by a test.
 *
 * Add a shared case to the fixture, not to one suite.
 */
import { expect, test } from "vitest";

import { minorFractionDigits, stepFor } from "./currency";
import moneyCases from "./__fixtures__/money-cases.json";
import { formatMoney, majorToMinor, minorToMajor } from "./format";

const cases = moneyCases as {
  minor_fraction_digits: { currency: string; digits: number }[];
  major_to_minor: { major: string; currency: string; minor: number }[];
  minor_to_major: { minor: number; currency: string; major: string }[];
  round_trips: { currencies: string[]; minor_amounts: number[] };
};

const roundTrips = cases.round_trips.currencies.flatMap((currency) =>
  cases.round_trips.minor_amounts.map((minor) => ({ currency, minor })),
);

test.for(cases.minor_fraction_digits)("$currency has $digits minor digits", ({ currency, digits }) => {
  expect(minorFractionDigits(currency)).toBe(digits);
});

test.for(cases.major_to_minor)("$major $currency → $minor minor units", ({ major, currency, minor }) => {
  expect(majorToMinor(major, currency)).toBe(minor);
});

test.for(cases.minor_to_major)("$minor $currency minor units → $major", ({ minor, currency, major }) => {
  expect(minorToMajor(minor, currency)).toBe(major);
});

test.for(roundTrips)("$minor $currency survives a trip through major units", ({
  minor,
  currency,
}) => {
  expect(majorToMinor(minorToMajor(minor, currency), currency)).toBe(minor);
});

// --- browser-only behaviour, with no backend counterpart to share ---------------

test("unparseable input is zero rather than NaN", () => {
  for (const value of ["", ".", "abc", "1e", "-", "  "]) {
    expect(majorToMinor(value, "AUD")).toBe(0);
  }
});

test("whitespace and numeric arguments are accepted", () => {
  expect(majorToMinor(" 12.34 ", "AUD")).toBe(1234);
  expect(majorToMinor(24.5, "AUD")).toBe(2450);
  expect(majorToMinor(-3.5, "AUD")).toBe(-350);
});

test("step is the currency's smallest unit", () => {
  expect(stepFor("AUD")).toBe("0.01");
  expect(stepFor("JPY")).toBe("1");
  expect(stepFor("KWD")).toBe("0.001");
  expect(stepFor("CLF")).toBe("0.0001");
});

test("formatMoney shows the currency's own decimals, not the locale's", () => {
  // Intl left alone renders 1234 IQD minor units as "IQD 1,234" — a thousand times
  // the 1.234 dinar actually stored — because CLDR reports IQD as having none.
  expect(formatMoney(1234, "IQD")).toContain("1.234");
  expect(formatMoney(1234, "KWD")).toContain("1.234");
  expect(formatMoney(1200, "JPY")).not.toContain(".");
});

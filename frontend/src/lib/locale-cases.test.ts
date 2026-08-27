/**
 * The formatting-locale contract, judged by the consumer (#23; PR #159 review,
 * P3-2): every tag the backend will store must be one `Intl` actually accepts,
 * or the Settings page hands the formatter a stored value it throws on.
 *
 * Every case is read from `__fixtures__/locale-cases.json`, which
 * backend/tests/test_settings.py also reads — add cases there, not here. This
 * suite runs under Node's full-ICU, the same engine family the browser uses.
 */

import { describe, expect, it } from "vitest";

import cases from "./__fixtures__/locale-cases.json";

describe("accepted tags are Intl-consumable and canonicalise identically", () => {
  for (const { input, canonical } of cases.accepted) {
    it(`${JSON.stringify(input)} -> ${canonical}`, () => {
      expect(Intl.getCanonicalLocales(input)[0]).toBe(canonical);
    });
  }
});

describe("tags refused everywhere are ones Intl throws on too", () => {
  for (const { input } of cases.refused_everywhere) {
    it(`${JSON.stringify(input)} throws`, () => {
      // Whitespace is plamotrack trimming policy, not an Intl question; the
      // trimmed emptiness is what Intl refuses.
      expect(() => Intl.getCanonicalLocales(input.trim())).toThrow(RangeError);
    });
  }
});

describe("policy refusals are valid to Intl — the refusal is plamotrack's", () => {
  // Pinned so nobody "fixes" the backend by widening it to everything Intl
  // takes: these are deliberately refused there (extension subtags carry
  // settings of their own) while being perfectly well-formed here.
  for (const { input } of cases.refused_by_policy) {
    it(`${JSON.stringify(input)} does not throw`, () => {
      expect(() => Intl.getCanonicalLocales(input)).not.toThrow();
    });
  }
});

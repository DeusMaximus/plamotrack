/** Every shipped catalogue — one import line per language, and that line IS
 * the registration: i18next's `resources` are derived from this map in
 * `index.ts`, and `catalogue.test.ts` validates exactly this map against the
 * manifest. One list feeding both is the point (PR #161 review, P2): when the
 * runtime and the validation suite kept separate lists, a language could pass
 * every gate — validation, coverage, the backend parity test — while the
 * browser silently fell back to English, because nothing ever loaded it.
 * docs/translating.md step 3 sends contributors here. */
import enAU from "./catalogues/en-AU.json";

export const CATALOGUES = {
  "en-AU": enAU,
} as const;

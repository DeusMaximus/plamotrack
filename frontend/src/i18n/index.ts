/** The interface-language runtime (design §6.1). `en-AU` is the canonical
 * source catalogue and unconditional fallback; every other language ships from
 * the repository through `manifest.json` and a `catalogues/<tag>.json`, reviewed
 * per docs/translating.md. The language is pinned to `en-AU` here until the
 * Settings page can change it (#27) — wiring it to `GET /settings` belongs to
 * that issue, not this module.
 *
 * Init is synchronous by construction: resources are inline imports, no backend
 * or detector plugins, so `t` is usable the moment this module is evaluated.
 * Keep it that way — a loading state for the app's own words helps nobody.
 * Nothing may call `t()` at module scope (a frozen string is an init-order
 * hazard now and a stale-language bug once #27 lands); label lookups live in
 * functions, see src/lib/labels.ts.
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enAU from "./catalogues/en-AU.json";
import manifest from "./manifest.json";

export const resources = {
  "en-AU": { translation: enAU },
} as const;

void i18n.use(initReactI18next).init({
  lng: "en-AU",
  fallbackLng: "en-AU",
  resources,
  // React already escapes rendered text; i18next escaping too would mangle the
  // non-ASCII copy this UI is full of (“ ” ＋ · … →) and break the e2e suite's
  // exact-text locators.
  interpolation: { escapeValue: false },
  returnNull: false,
  // An empty catalogue value is a defect (the validation suite refuses it), so
  // an empty string at runtime should fall through rather than render blank.
  returnEmptyString: false,
});

export default i18n;
export { manifest };

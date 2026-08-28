import type { InstanceSettings } from "../api/types";
import i18n, { manifest } from "../i18n";

/** Instance-wide presentation (#27, design §6.1): which language the interface
 * speaks and how dates, times and numbers render. One module holds the resolved
 * values; `src/lib/format.ts` reads them, and `Layout` calls
 * `applyInstanceSettings` whenever the settings row arrives or changes — so
 * every browser renders from the same persisted values and there is no hidden
 * per-browser preference.
 *
 * Presentation only: nothing here writes, and changing any of it leaves stored
 * business data byte-for-byte unchanged. Canonical identifiers (BCP 47 tags,
 * IANA zones, enum values) stay untranslated wherever they travel.
 */

export interface ManifestLanguage {
  tag: string;
  nativeName: string;
  direction: string;
  enabled: boolean;
}

/** The languages a selector may offer — the manifest's enabled entries, which
 *  the backend parity test holds equal to what PATCH /settings accepts. */
export function enabledLanguages(): ManifestLanguage[] {
  return manifest.languages.filter((entry) => entry.enabled);
}

export interface ResolvedLanguage {
  entry: ManifestLanguage;
  /** True when the saved tag is unknown to this build or disabled — the UI
   *  renders the en-AU fallback and says so, recoverably (#27). */
  fallback: boolean;
}

const EN_AU: ManifestLanguage = { tag: "en-AU", nativeName: "English (Australia)", direction: "ltr", enabled: true };

/** The saved interface language, resolved against the shipped manifest — or the
 *  unconditional `en-AU` fallback (§6.1) when this build can't serve it. Pure,
 *  so the fallback rule is testable without a DOM. */
export function resolveLanguage(tag: string): ResolvedLanguage {
  const entry = manifest.languages.find((candidate) => candidate.tag === tag);
  if (entry && entry.enabled) return { entry, fallback: false };
  return { entry: manifest.languages.find((candidate) => candidate.tag === "en-AU") ?? EN_AU, fallback: true };
}

export interface FormatPreferences {
  locale: string;
  timeZone: string;
  dateStyle: string;
  hourCycle: string;
}

/** The seeded defaults (#23) — also what renders before the settings row has
 *  arrived, so first paint and a fresh instance agree. */
const DEFAULTS: FormatPreferences = {
  locale: "en-AU",
  timeZone: "UTC",
  dateStyle: "locale",
  hourCycle: "locale",
};

let preferences: FormatPreferences = DEFAULTS;

export function formatPreferences(): FormatPreferences {
  return preferences;
}

/** Presentation state from a settings row, without side effects beyond this
 *  module — the format helpers read it on every call, so anything re-rendered
 *  after a change shows the new shape (the Language section's save invalidates
 *  every query for exactly that reason). */
export function setFormatPreferences(settings: {
  formatting_locale: string;
  time_zone: string;
  date_style: string;
  hour_cycle: string;
}): void {
  preferences = {
    locale: settings.formatting_locale,
    timeZone: settings.time_zone,
    dateStyle: settings.date_style,
    hourCycle: settings.hour_cycle,
  };
}

/** Test-only escape hatch — the module is a singleton and vitest cases must not
 *  leak preferences into each other. */
export function resetFormatPreferences(): void {
  preferences = DEFAULTS;
}

/** Everything a settings row implies for this browser: formatting preferences,
 *  the interface language (falling back to en-AU when the saved tag isn't
 *  shipped), and the document's own lang/dir metadata (#27). Idempotent — the
 *  Layout effect runs it on every settings change, including the first load. */
export function applyInstanceSettings(settings: InstanceSettings): ResolvedLanguage {
  setFormatPreferences(settings);
  const resolved = resolveLanguage(settings.interface_language);
  if (i18n.language !== resolved.entry.tag) {
    void i18n.changeLanguage(resolved.entry.tag);
  }
  document.documentElement.lang = resolved.entry.tag;
  document.documentElement.dir = documentDirection(resolved.entry.direction);
  return resolved;
}

/** The document `dir` a manifest entry implies — anything but an explicit
 *  "rtl" is "ltr", so a malformed entry can't leave the attribute unset. Pure,
 *  because the vitest suite runs without a DOM (the no-jsdom decision, #22)
 *  and the real attribute write is e2e's to observe. */
export function documentDirection(direction: string): "ltr" | "rtl" {
  return direction === "rtl" ? "rtl" : "ltr";
}

/** The per-browser theme (design §13.1): light, dark, or follow the device.
 *
 *  The one deliberate exception to the instance-wide settings rule (§6.1, rule
 *  11): "system" only means something on the device asking, so the preference
 *  lives in this browser's `localStorage`, not in `instance_settings`. Two
 *  things read it — `public/theme.js` before first paint (a classic script the
 *  bundled CSP allows; an inline one it would not) and this module for the
 *  running app — and `theme.test.ts` evaluates that script against the same
 *  cases so the key, the accepted values and the attribute cannot drift.
 *
 *  The resolved theme is `data-theme` on <html>; `src/index.css` defines the
 *  tokens for the dark default and redefines them under `[data-theme="light"]`.
 */

import { useSyncExternalStore } from "react";

export const THEME_STORAGE_KEY = "plamotrack.theme";
export const THEME_ATTRIBUTE = "data-theme";
export const THEME_PREFERENCES = ["light", "dark", "system"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];
export type ResolvedTheme = "light" | "dark";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function isPreference(value: unknown): value is ThemePreference {
  return (THEME_PREFERENCES as readonly unknown[]).includes(value);
}

/** What this browser stored, or "system" for nothing, garbage, or a storage
 *  that throws (a private window with storage denied, for one). */
export function readPreference(): ThemePreference {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    stored = null;
  }
  return isPreference(stored) ? stored : "system";
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

function systemPrefersDark(): boolean {
  return typeof matchMedia === "function" && matchMedia(DARK_QUERY).matches;
}

/** Put the resolved theme on <html>; returns what was applied. */
export function applyTheme(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(preference, systemPrefersDark());
  document.documentElement.setAttribute(THEME_ATTRIBUTE, resolved);
  return resolved;
}

// --- the store the switch subscribes to ---------------------------------------

let current: ThemePreference | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function getPreference(): ThemePreference {
  if (current === null) current = readPreference();
  return current;
}

export function setPreference(preference: ThemePreference): void {
  current = preference;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage unavailable: this tab still switches; the next load follows the device.
  }
  applyTheme(preference);
  notify();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Test-only: forget the cached preference so the next read goes to storage. */
export function resetThemeStore(): void {
  current = null;
}

/** Apply the stored preference and keep it applied: the device's scheme while
 *  the preference is "system", and another tab of this origin changing the
 *  preference. Called once at start-up; returns the teardown. */
export function watchTheme(): () => void {
  applyTheme(getPreference());
  const media = matchMedia(DARK_QUERY);
  const onMedia = () => {
    if (getPreference() === "system") applyTheme("system");
  };
  const onStorage = (event: StorageEvent) => {
    // `key` is null for `clear()`, which also changes this preference.
    if (event.key !== null && event.key !== THEME_STORAGE_KEY) return;
    current = readPreference();
    applyTheme(current);
    notify();
  };
  media.addEventListener("change", onMedia);
  window.addEventListener("storage", onStorage);
  return () => {
    media.removeEventListener("change", onMedia);
    window.removeEventListener("storage", onStorage);
  };
}

export function useTheme(): [ThemePreference, (preference: ThemePreference) => void] {
  const preference = useSyncExternalStore(subscribe, getPreference, () => "system" as const);
  return [preference, setPreference];
}

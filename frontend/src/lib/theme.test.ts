/** The theme has two readers of one storage key — public/theme.js before first
 *  paint and src/lib/theme.ts in the running app — and neither can import the
 *  other. This file is what holds them together: the pre-paint script is
 *  evaluated as text against the same stubs, and both must land on the same
 *  `data-theme` for every value the key can hold (null, empty, garbage, each of
 *  the three preferences, a storage that throws) under both device schemes. */

import { afterEach, describe, expect, it, vi } from "vitest";

// The script as text (Vite's `?raw`): app code has no business seeing Node's
// fs types, and the point is to run the file the browser runs.
import PRE_PAINT from "../../public/theme.js?raw";

import {
  THEME_ATTRIBUTE,
  THEME_STORAGE_KEY,
  applyTheme,
  getPreference,
  readPreference,
  resetThemeStore,
  resolveTheme,
  setPreference,
} from "./theme";

type Stored = string | null | "throws";

function stubs(stored: Stored, systemDark: boolean) {
  const attributes = new Map<string, string>();
  const storage = {
    // Keyed, so a script or module reading a different key sees nothing.
    getItem: vi.fn((key: string) => {
      if (stored === "throws") throw new Error("storage denied");
      return key === THEME_STORAGE_KEY ? stored : null;
    }),
    setItem: vi.fn((_key: string, _value: string) => {
      if (stored === "throws") throw new Error("storage denied");
    }),
  };
  const document = {
    documentElement: {
      setAttribute: (name: string, value: string) => attributes.set(name, value),
    },
  };
  const matchMedia = vi.fn((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" && systemDark,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  return { attributes, storage, document, matchMedia };
}

function runPrePaint(stored: Stored, systemDark: boolean): string | undefined {
  const dom = stubs(stored, systemDark);
  // The script names its globals bare, so parameters shadow them here.
  new Function("localStorage", "matchMedia", "document", PRE_PAINT)(
    dom.storage,
    dom.matchMedia,
    dom.document,
  );
  return dom.attributes.get(THEME_ATTRIBUTE);
}

function runModule(stored: Stored, systemDark: boolean): string | undefined {
  const dom = stubs(stored, systemDark);
  vi.stubGlobal("localStorage", dom.storage);
  vi.stubGlobal("matchMedia", dom.matchMedia);
  vi.stubGlobal("document", dom.document);
  resetThemeStore();
  applyTheme(getPreference());
  return dom.attributes.get(THEME_ATTRIBUTE);
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetThemeStore();
});

const STORED: Stored[] = [null, "", "garbage", "light", "dark", "system", "throws"];

describe("the pre-paint script and the module resolve the same theme", () => {
  it.each(STORED)("stored=%j on a light device", (stored) => {
    const expected = stored === "dark" ? "dark" : "light";
    expect(runPrePaint(stored, false)).toBe(expected);
    expect(runModule(stored, false)).toBe(expected);
  });

  it.each(STORED)("stored=%j on a dark device", (stored) => {
    const expected = stored === "light" ? "light" : "dark";
    expect(runPrePaint(stored, true)).toBe(expected);
    expect(runModule(stored, true)).toBe(expected);
  });

  it("the script reads the module's key from the module's attribute", () => {
    expect(PRE_PAINT).toContain(JSON.stringify(THEME_STORAGE_KEY));
    expect(PRE_PAINT).toContain(JSON.stringify(THEME_ATTRIBUTE));
  });
});

describe("the preference", () => {
  it("reads only the three values, else system", () => {
    for (const [stored, expected] of [
      [null, "system"],
      ["", "system"],
      ["dark ", "system"],
      ["LIGHT", "system"],
      ["light", "light"],
      ["dark", "dark"],
      ["system", "system"],
      ["throws", "system"],
    ] as const) {
      const dom = stubs(stored, false);
      vi.stubGlobal("localStorage", dom.storage);
      expect(readPreference(), String(stored)).toBe(expected);
    }
  });

  it("resolves system from the device and an explicit choice from itself", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("setPreference stores, applies and is what the next read returns", () => {
    const dom = stubs(null, true);
    vi.stubGlobal("localStorage", dom.storage);
    vi.stubGlobal("matchMedia", dom.matchMedia);
    vi.stubGlobal("document", dom.document);
    resetThemeStore();
    setPreference("light");
    expect(dom.storage.setItem).toHaveBeenCalledWith(THEME_STORAGE_KEY, "light");
    expect(dom.attributes.get(THEME_ATTRIBUTE)).toBe("light");
    expect(getPreference()).toBe("light");
    setPreference("system");
    expect(dom.storage.setItem).toHaveBeenLastCalledWith(THEME_STORAGE_KEY, "system");
    expect(dom.attributes.get(THEME_ATTRIBUTE)).toBe("dark");
  });

  it("a storage that refuses the write still switches this tab", () => {
    const dom = stubs("throws", false);
    vi.stubGlobal("localStorage", dom.storage);
    vi.stubGlobal("matchMedia", dom.matchMedia);
    vi.stubGlobal("document", dom.document);
    resetThemeStore();
    expect(() => setPreference("dark")).not.toThrow();
    expect(dom.attributes.get(THEME_ATTRIBUTE)).toBe("dark");
    expect(getPreference()).toBe("dark");
  });
});

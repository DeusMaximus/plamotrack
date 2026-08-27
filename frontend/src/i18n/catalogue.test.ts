/** The catalogue gate, in three layers (docs/translating.md is the contract):
 *
 *  1. Each validator is proven against inline bad fixtures — standing negative
 *     controls, so "the shipped files pass" can only be green because the files
 *     are right, not because a check went soft.
 *  2. The shipped manifest and every shipped catalogue pass every check, and an
 *     `enabled` language must cover 100% of en-AU's keys.
 *  3. What the compiler cannot see: dynamic lookups (enum → label) are driven
 *     through every runtime member, and the i18next behaviours the app relies
 *     on (interpolation, plural selection, en-AU fallback) are pinned.
 *
 *  Compile-time typing (src/i18n/i18next.d.ts) already refuses a typo in a
 *  static `t("...")` literal; this file owes the rest.
 */
import { describe, expect, it } from "vitest";

import {
  IMPORT_MODES,
  ITEM_TYPES,
  KIT_STATUSES,
  PACKING_QUALITIES,
  ROW_ACTIONS,
  SHIPPING_SPEEDS,
  WOULD_ORDER_AGAIN,
} from "../api/types";
import {
  dateWithElapsed,
  importActionLabel,
  importTableLabel,
  itemTypeLabel,
  itemTypePlural,
  itemTypeTitle,
  packingQualityLabel,
  shippingSpeedLabel,
  statusLabel,
  wouldOrderAgainLabel,
} from "../lib/labels";
import enAU from "./catalogues/en-AU.json";
import i18n, { manifest } from "./index";
import { CATALOGUES as REGISTRY } from "./registry";
import {
  catalogueProblems,
  compareToSource,
  flattenCatalogue,
  placeholderNames,
  pluralCategories,
  summarize,
  validateManifest,
} from "./validate";

/** THE registry — the same map i18next's resources are derived from
 * (src/i18n/registry.ts), widened for indexing by manifest tag. Validating the
 * runtime's own source list is the point: a test-only copy of it is how a
 * language passes every gate while the runtime never loads it (PR #161
 * review, P2). */
const CATALOGUES: Record<string, unknown> = REGISTRY;

const flatten = (raw: unknown) => {
  const { entries, problems } = flattenCatalogue(raw);
  expect(problems).toEqual([]);
  return entries;
};

describe("the validators refuse what they must (standing negative controls)", () => {
  it("an empty or whitespace-only value", () => {
    expect(flattenCatalogue({ a: "" }).problems).toEqual(['"a" is blank']);
    expect(flattenCatalogue({ a: "   " }).problems).toEqual(['"a" is blank']);
    expect(flattenCatalogue({ a: "\n\t" }).problems).toEqual(['"a" is blank']);
    // Whitespace *around* content is content — byte-preserved, not judged.
    expect(flattenCatalogue({ a: " · " }).problems).toEqual([]);
  });

  it("a separator inside a key segment", () => {
    expect(flattenCatalogue({ "a.b": "x" }).problems).toEqual([
      'key segment "a.b" contains a separator character',
    ]);
    expect(flattenCatalogue({ "a:b": "x" }).problems).toHaveLength(1);
  });

  it("a non-string leaf and a non-object root", () => {
    expect(flattenCatalogue({ a: 3 }).problems).toEqual(['"a" is not a string or group']);
    expect(flattenCatalogue(null).problems).toEqual(["catalogue root is not an object"]);
  });

  it("nesting past three levels", () => {
    expect(flattenCatalogue({ a: { b: { c: { d: "x" } } } }).problems).toEqual([
      '"a.b.c" nests deeper than 3 levels',
    ]);
  });

  it("unbalanced braces and a non-camelCase placeholder", () => {
    expect(placeholderNames("{{name} missing").problems).toEqual(["unbalanced {{ }} braces"]);
    expect(placeholderNames("{{Name}}").problems).toEqual([
      'placeholder "{{Name}}" is not a camelCase name',
    ]);
  });

  it("a bare key colliding with its plural forms", () => {
    const entries = flatten({ n: "x", n_one: "y", n_other: "z" });
    expect(catalogueProblems(entries, "en-AU")).toContain('"n" exists both bare and plural-suffixed');
  });

  it("an incomplete plural set for the language", () => {
    const entries = flatten({ n_one: "y" });
    const problems = catalogueProblems(entries, "en-AU");
    expect(problems).toEqual(['"n" has plural forms [one] but en-AU needs [one, other]']);
  });

  it("a key the source catalogue does not know", () => {
    const source = summarize(flatten({ a: "x" }));
    const target = summarize(flatten({ a: "x", rogue: "y" }));
    expect(compareToSource(source, target).problems).toEqual([
      '"rogue" is not a key en-AU knows',
    ]);
  });

  it("a placeholder set that drifted from the source", () => {
    const source = summarize(flatten({ a: "hello {{name}}" }));
    const target = summarize(flatten({ a: "bonjour {{nom}}" }));
    expect(compareToSource(source, target).problems).toEqual([
      '"a" placeholders [nom] differ from en-AU\'s [name]',
    ]);
  });

  it("a bare key where the source is plural", () => {
    const source = summarize(flatten({ n_one: "{{count}} x", n_other: "{{count}} xs" }));
    const target = summarize(flatten({ n: "{{count}} x" }));
    expect(compareToSource(source, target).problems).toContain(
      '"n" is plural in en-AU but not here',
    );
  });

  it("coverage counts missing base keys", () => {
    const source = summarize(flatten({ a: "x", b: "y", n_one: "z", n_other: "zs" }));
    const target = summarize(flatten({ a: "x" }));
    const { missing, coverage } = compareToSource(source, target);
    expect(missing.sort()).toEqual(["b", "n"]);
    expect(coverage).toBeCloseTo(1 / 3);
  });

  it("a manifest without en-AU, or with it disabled", () => {
    expect(validateManifest({ languages: [] })).toContain("en-AU is missing from the manifest");
    expect(
      validateManifest({
        languages: [{ tag: "en-AU", nativeName: "English", direction: "ltr", enabled: false }],
      }),
    ).toContain("en-AU must stay enabled and ltr");
  });

  it("a malformed manifest entry", () => {
    const entry = { tag: "en-AU", nativeName: "English (Australia)", direction: "ltr", enabled: true };
    expect(validateManifest({ languages: [entry, { ...entry, tag: "EN-au" }] })).toContain(
      '"EN-au" is not written in its canonical form',
    );
    expect(validateManifest({ languages: [entry, { ...entry, tag: "not a tag!" }] })).toContain(
      '"not a tag!" is not a valid BCP 47 tag',
    );
    expect(validateManifest({ languages: [entry, { ...entry, direction: "lrt" }] })).toContain(
      '"en-AU" direction must be "ltr" or "rtl"',
    );
    expect(validateManifest({ languages: [entry, entry] })).toContain('"en-AU" is listed twice');
  });
});

describe("the shipped manifest and catalogues pass", () => {
  it("the manifest is valid", () => {
    expect(validateManifest(manifest)).toEqual([]);
  });

  it("every manifest language ships a catalogue and vice versa", () => {
    const tags = manifest.languages.map((entry) => entry.tag).sort();
    expect(Object.keys(CATALOGUES).sort()).toEqual(tags);
  });

  it("every registered catalogue is loaded into the runtime", () => {
    // The registry feeds i18next's resources by derivation; this holds if that
    // derivation is ever replaced with a hand-written list again.
    for (const tag of Object.keys(CATALOGUES)) {
      expect(i18n.hasResourceBundle(tag, "translation"), tag).toBe(true);
    }
  });

  it("every catalogue is structurally sound for its language", () => {
    for (const [tag, raw] of Object.entries(CATALOGUES)) {
      const { entries, problems } = flattenCatalogue(raw);
      expect(problems, tag).toEqual([]);
      expect(catalogueProblems(entries, tag), tag).toEqual([]);
      expect(entries.size, tag).toBeGreaterThan(0);
    }
  });

  it("an enabled language covers 100% of en-AU", () => {
    const source = summarize(flatten(enAU));
    for (const entry of manifest.languages) {
      const { problems, coverage } = compareToSource(
        source,
        summarize(flatten(CATALOGUES[entry.tag])),
      );
      expect(problems, entry.tag).toEqual([]);
      if (entry.enabled) expect(coverage, entry.tag).toBe(1);
    }
  });
});

describe("dynamic keys resolve for every runtime enum member", () => {
  it.each(KIT_STATUSES)("kit status %s has a label", (status) => {
    const label = statusLabel(status);
    expect(label).not.toBe("");
    expect(label).not.toContain(status); // resolved, not echoed back as the key
  });

  it.each(ITEM_TYPES)("item type %s has singular, plural and title nouns", (type) => {
    for (const label of [itemTypeLabel(type), itemTypePlural(type), itemTypeTitle(type)]) {
      expect(label).not.toBe("");
      expect(label).not.toContain("itemType.");
    }
  });

  it.each(PACKING_QUALITIES)("packing quality %s has a label", (quality) => {
    expect(packingQualityLabel(quality)).not.toContain(quality);
  });

  it.each(SHIPPING_SPEEDS)("shipping speed %s has a label", (speed) => {
    expect(shippingSpeedLabel(speed)).not.toContain(speed);
  });

  it.each(WOULD_ORDER_AGAIN)("would-order-again %s has a label", (answer) => {
    expect(wouldOrderAgainLabel(answer)).not.toBe("");
    expect(wouldOrderAgainLabel(answer)).not.toContain("wouldOrderAgain.");
  });

  it.each(ROW_ACTIONS)("row action %s has a badge word and both counted phrases", (action) => {
    expect(importActionLabel(action)).not.toContain("importAction.");
    for (const count of [1, 5]) {
      for (const group of ["importCount", "importPill"] as const) {
        const phrase = i18n.t(`${group}.${action}`, { count });
        expect(phrase, `${group}.${action}`).toContain(String(count));
        expect(phrase, `${group}.${action}`).not.toContain(`${group}.`);
      }
    }
  });

  it("the elapsed-day cell keeps its bytes, non-breaking space included", () => {
    // U+00A0 before the "d" — the source spelling KitsPage carried so "3 d"
    // never wraps; a plain space here is the transcription defect this pins.
    expect(dateWithElapsed("8/26/2026", 0)).toBe("8/26/2026 · same day");
    expect(dateWithElapsed("8/26/2026", 3)).toBe("8/26/2026 · 3 d");
  });

  it("the orders counted phrases keep their bytes", () => {
    expect(i18n.t("orders.acrossLines", { total: 1, count: 1 })).toBe("1 across 1 line");
    expect(i18n.t("orders.acrossLines", { total: 7, count: 3 })).toBe("7 across 3 lines");
    expect(i18n.t("orders.spawnedKits", { count: 1 })).toBe("spawned 1 kit");
    expect(i18n.t("orders.spawnedKits", { count: 4 })).toBe("spawned 4 kits");
    // NBSP before the "d", matching the Kits column — the disclosed one-byte
    // normalization of the received cell's plain space (#164 → PR 4).
    expect(i18n.t("orders.inTransitDays", { count: 3 })).toBe("in transit · 3\u00a0d");
    expect(i18n.t("orders.inTransitToday")).toBe("in transit · today");
  });

  it("the pill and totals phrasings diverge exactly where main's did (#163 P3-1)", () => {
    // The one action whose two phrasings differ is the standing proof the two
    // groups are both load-bearing — collapse them and this goes red.
    expect(i18n.t("importPill.error", { count: 6 })).toBe("6 error");
    expect(i18n.t("importCount.error", { count: 6 })).toBe("6 with errors");
  });

  it.each(IMPORT_MODES)("import mode %s has a label and a blurb", (mode) => {
    for (const leaf of ["label", "blurb"] as const) {
      const value = i18n.t(`importMode.${mode}.${leaf}`);
      expect(value).not.toBe("");
      expect(value).not.toContain("importMode.");
    }
  });

  // The portable-table vocabulary is spec.py's key set, restated as a literal
  // so the subject is independent of the code under test; DataPage's export
  // list and ImportPreview's headings both resolve through these keys.
  const PORTABLE_TABLES = [
    "retailers",
    "tools",
    "consumables",
    "upgrades",
    "display_items",
    "orders",
    "order_items",
    "kits",
    "upgrade_applications",
    "kit_photos",
    "instance_settings",
  ];

  it.each(PORTABLE_TABLES)("portable table %s has a display name", (table) => {
    expect(importTableLabel(table)).not.toContain("importTable.");
    expect(importTableLabel(table)).not.toBe(table === "kits" ? "" : table);
  });

  it("an unknown table key falls back to itself, not a dotted key", () => {
    expect(importTableLabel("not_a_table")).toBe("not_a_table");
  });

  it.each(["archive", "csv-set", "starter-sheet"])("import source %s has a label", (source) => {
    const value = i18n.t(`importSource.${source}` as "importSource.archive");
    expect(value).not.toBe("");
    expect(value).not.toContain("importSource.");
  });

  // The Inventory route segments, restated as a literal — the tab ids are not
  // wire item types ("display-items" vs "display"), so they get their own row.
  const INVENTORY_TABS = ["tools", "consumables", "upgrades", "display-items"] as const;

  it.each(INVENTORY_TABS)("inventory tab %s has a label and an empty state", (tab) => {
    for (const key of [`inventory.tabs.${tab}`, `inventory.emptyNone.${tab}`] as const) {
      const value = i18n.t(key);
      expect(value, key).not.toBe("");
      expect(value, key).not.toContain("inventory.");
    }
  });

  it.each(["tools", "consumables", "display-items"] as const)(
    "inventory tab %s has a category placeholder",
    (tab) => {
      expect(i18n.t(`inventory.categoryPlaceholder.${tab}`)).not.toContain("inventory.");
    },
  );
});

describe("runtime behaviour the app relies on", () => {
  it("looks a key up byte-exactly", () => {
    expect(i18n.t("nav.orders")).toBe("Orders");
    expect(i18n.t("kitStatus.pre_ordered")).toBe("Pre-ordered");
  });

  it("interpolates byte-exactly, escaping nothing", () => {
    expect(i18n.t("api.exportFailed", { status: 404 })).toBe("Export failed (404)");
    expect(i18n.t("board.loadFailed", { message: "<oops>" })).toBe("Failed to load kits: <oops>");
  });

  it("selects plural forms by count and falls back to en-AU per key", () => {
    // A probe language registered only here: one plural pair plus a hole where
    // nav.orders should be, so both behaviours are observed on a language that
    // is not the fallback. The private-use subtag is the collision guard — the
    // backend refuses `-x-` tags as interface languages, so no shipped
    // catalogue can ever claim this name (a real en-NZ broke the previous
    // spelling of this test); Intl still resolves it to English plural rules.
    i18n.addResourceBundle("en-x-probe", "translation", {
      probe_one: "{{count}} widget",
      probe_other: "{{count}} widgets",
    });
    const t = i18n.getFixedT("en-x-probe") as (
      key: string,
      opts?: Record<string, unknown>,
    ) => string;
    expect(t("probe", { count: 1 })).toBe("1 widget");
    expect(t("probe", { count: 5 })).toBe("5 widgets");
    expect(t("nav.orders")).toBe("Orders");
  });

  it("pins en-AU's plural categories, explicitly tagged", () => {
    expect(pluralCategories("en-AU")).toEqual(["one", "other"]);
  });

  it("carries direction metadata for the resolved language", () => {
    const entry = manifest.languages.find((language) => language.tag === i18n.language);
    expect(entry?.direction).toBe("ltr");
  });
});

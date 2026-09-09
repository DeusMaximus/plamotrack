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
  DATE_STYLES,
  HOUR_CYCLES,
  IMPORT_MODES,
  ITEM_TYPES,
  KIT_STATUSES,
  PACKING_QUALITIES,
  SHIPPING_SPEEDS,
  WOULD_ORDER_AGAIN,
} from "../api/types";
import type { RowAction } from "../api/types";
import {
  dateWithElapsed,
  countedPhrase,
  importActionLabel,
  importFieldLabel,
  importTableLabel,
  itemTypeLabel,
  itemTypePlural,
  itemTypeTitle,
  matchedByLabel,
  packingQualityLabel,
  shippingSpeedLabel,
  statusLabel,
  wouldOrderAgainLabel,
} from "../lib/labels";
import { formatNumber } from "../lib/format";
import { resetFormatPreferences, setFormatPreferences } from "../lib/presentation";
import apiErrorCodes from "../lib/__fixtures__/api-error-codes.json";
import { camelizeKey } from "../lib/apiError";
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
    expect(validateManifest({ languages: [{ ...entry, nativeName: " \t " }] })).toContain(
      '"en-AU" has no native name',
    );
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

  it.each([
    ["create", "new"],
    ["update", "updated"],
    ["unchanged", "unchanged"],
    ["skip", "skipped"],
    ["error", "error"],
  ] as const)("row action %s has its catalogue badge word and both counted phrases", (action, label) => {
    expect(importActionLabel(action)).toBe(label);
    for (const count of [1, 5]) {
      for (const group of ["importCount", "importPill"] as const) {
        const phrase = i18n.t(`${group}.${action}`, { count, countDisplay: String(count) });
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
    expect(i18n.t("orders.acrossLines", { total: 1, count: 1, countDisplay: "1" })).toBe(
      "1 across 1 line",
    );
    expect(i18n.t("orders.acrossLines", { total: 7, count: 3, countDisplay: "3" })).toBe(
      "7 across 3 lines",
    );
    expect(i18n.t("orders.spawnedKits", { count: 1, countDisplay: "1" })).toBe("spawned 1 kit");
    expect(i18n.t("orders.spawnedKits", { count: 4, countDisplay: "4" })).toBe("spawned 4 kits");
    // NBSP before the "d", matching the Kits column — the disclosed one-byte
    // normalization of the received cell's plain space (#164 → PR 4).
    expect(i18n.t("orders.inTransitDays", { count: 3, countDisplay: "3" })).toBe(
      "in transit · 3\u00a0d",
    );
    expect(i18n.t("orders.inTransitToday")).toBe("in transit · today");
  });

  it("Japanese copy honours the values composed for quantity suffixes and order totals", () => {
    const ja = i18n.getFixedT("ja");
    const promptTail =
      "の使用記録を取り消しますか？ 在庫に戻すかどうかを選んでください。部品が物理的に残っている場合のみ在庫に戻してください。使用済みまたは破損している場合は在庫に戻せません。";

    // KitsPage passes an empty suffix for one item and the whole preformatted
    // " (×N)" notation for several. The placeholder is not a bare count.
    expect(ja("kits.withdrawPrompt", { name: "メタルスラスター", qty: "" })).toBe(
      `「メタルスラスター」${promptTail}`,
    );
    expect(ja("kits.withdrawPrompt", { name: "メタルスラスター", qty: " (×2)" })).toBe(
      `「メタルスラスター」 (×2)${promptTail}`,
    );
    expect(ja("orders.acrossLines", { total: 4, count: 2, countDisplay: "2" })).toBe(
      "2件、合計4個",
    );
  });

  it("the pill and totals phrasings diverge exactly where main's did (#163 P3-1)", () => {
    // The one action whose two phrasings differ is the standing proof the two
    // groups are both load-bearing — collapse them and this goes red.
    expect(i18n.t("importPill.error", { count: 6, countDisplay: "6" })).toBe("6 error");
    expect(i18n.t("importCount.error", { count: 6, countDisplay: "6" })).toBe("6 with errors");
  });

  it.each(IMPORT_MODES)("import mode %s has a label and a blurb", (mode) => {
    for (const leaf of ["label", "blurb"] as const) {
      const value = i18n.t(`importMode.${mode}.${leaf}`);
      expect(value).not.toBe("");
      expect(value).not.toContain("importMode.");
    }
  });

  // The portable-table vocabulary is spec.py's key set, restated as a literal
  // so the subject is independent of the code under test; DataSection's export
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

  // All portable column names plus the legacy imported alias, restated from
  // spec.py rather than from the label helper: known diagnostic parameters and
  // ImportPreview change rows must never expose these canonical identifiers.
  const PORTABLE_FIELDS = [
    "id", "interface_language", "formatting_locale", "time_zone", "date_style", "hour_cycle",
    "reference_currency", "name", "url", "rating", "packing_quality", "shipping_speed",
    "would_order_again", "notes", "category", "quantity_on_hand", "unit_cost_reference_minor",
    "unit_cost_reference", "unit_cost_reference_currency", "condition_notes", "manufacturer",
    "low_stock_threshold", "retailer_id", "retailer_name", "order_date", "order_number",
    "delivery_service", "tracking_number", "tracking_url", "shipping_cost_minor", "shipping_cost",
    "currency_code", "shipped_at", "received_at", "order_id", "item_type", "catalog_ref_id",
    "catalog_name", "quantity", "unit_price_minor", "unit_price", "converted_price_minor",
    "converted_price_aud_minor", "converted_currency_code", "kit_name", "kit_grade", "kit_scale",
    "kit_number", "kit_status", "grade", "scale", "series", "status", "status_updated_at",
    "build_started_at", "build_completed_at", "build_notes", "order_item_id", "created_at",
    "updated_at", "upgrade_id", "upgrade_name", "kit_id", "quantity_used", "applied_at",
    "file_path", "caption", "taken_at",
  ];

  it.each(PORTABLE_FIELDS)("portable field %s has a display label", (field) => {
    expect(importFieldLabel(field)).not.toBe(field);
  });

  it("an unknown field falls back to the canonical identifier", () => {
    expect(importFieldLabel("future_column")).toBe("future_column");
  });

  it("an unknown table key falls back to itself, not a dotted key", () => {
    expect(importTableLabel("not_a_table")).toBe("not_a_table");
  });

  it.each(DATE_STYLES)("date style %s has an option label (#27)", (style) => {
    const label = i18n.t(`dateStyle.${style}`);
    expect(label).not.toBe("");
    expect(label).not.toContain("dateStyle.");
  });

  it.each(HOUR_CYCLES)("hour cycle %s has an option label (#27)", (cycle) => {
    const label = i18n.t(`hourCycle.${cycle}`);
    expect(label).not.toBe("");
    expect(label).not.toContain("hourCycle.");
  });

  it.each(["archive", "csv-set", "starter-sheet"])("import source %s has a label", (source) => {
    const value = i18n.t(`importSource.${source}` as "importSource.archive");
    expect(value).not.toBe("");
    expect(value).not.toContain("importSource.");
  });

  // The wire `matched_by` identifiers (#26), restated as a literal: "id",
  // matching natural keys from spec.py, and the importer's three order phrases
  // canonicalised to snake_case.
  const MATCHED_BY = [
    ["id", "id"],
    ["name", "name"],
    ["application", "upgrade application"],
    ["photo", "photo"],
    ["instance_settings", "the settings row"],
    ["retailer_order_number", "retailer + order number"],
    ["retailer_date_lines", "retailer + date + lines"],
    ["order_line", "order + line"],
  ] as const;

  it.each(MATCHED_BY)("matched-by %s has its catalogue display phrase", (value, label) => {
    expect(matchedByLabel(value)).toBe(label);
  });

  it("an unknown matched-by value falls back to itself — a column name is already true", () => {
    expect(matchedByLabel("kit_number")).toBe("kit_number");
  });

  /** The same contract for row actions, which used to render the dotted key
   *  instead. `RowAction` binds this repo's callers, not the JSON a newer
   *  backend sends, so the cast is the point of the test: it stands in for a
   *  preview payload naming an action this build has never heard of
   *  (#177 review, P3-3). `ImportPreview`'s badge is the shipped consumer. */
  it("an unknown row action falls back to its canonical wire value", () => {
    expect(importActionLabel("future_action" as RowAction)).toBe("future_action");
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

  it("uses the formatting locale for every shared counted phrase without changing plural selection", () => {
    // Literal keys, not a source-derived list: this is the cross-page count
    // matrix for import pills/totals/results, inventory, the picker, elapsed
    // time and order-line summaries. Each keeps the raw `count` for grammar
    // while the separately supplied display value gets the locale's digits.
    const COUNTED_PHRASES = [
      "importPill.error",
      "importCount.error",
      "data.result.created",
      "importPreview.recordsDeleted",
      "inventory.applyOnHand",
      "catalogPicker.onHand",
      "orders.acrossLines",
      "orders.spawnedKits",
      "orders.inTransitDays",
      "common.elapsed.days",
    ];
    setFormatPreferences({
      formatting_locale: "de-DE",
      time_zone: "UTC",
      date_style: "locale",
      hour_cycle: "locale",
    });
    for (const key of COUNTED_PHRASES) {
      const value = countedPhrase(key, 1234, {
        date: "14.3.2026",
        total: formatNumber(4567),
      });
      expect(value, key).toContain("1.234");
    }
    expect(i18n.t("importCount.error", { count: 1, countDisplay: formatNumber(1) })).toBe(
      "1 with errors",
    );
    resetFormatPreferences();
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

describe("REST error codes (#25) — the registry, the catalogue, and the params agree", () => {
  // The shared fixture is the subject (rule: never derive the enumeration from
  // the code under test); backend/tests/test_error_envelope.py pins
  // app/error_codes.py to the same file from the other side.
  const CODES = Object.entries(apiErrorCodes.codes) as [string, { params: string[] }][];

  // request.validation has a structured per-finding renderer under
  // `validation.request.*`, rather than a generic api.* sentence.
  const RENDERED = CODES.filter(([code]) => code !== "request.validation");

  it("covers every wire code, and request.validation is the only exception", () => {
    expect(CODES.length).toBeGreaterThan(50);
    expect(RENDERED.length).toBe(CODES.length - 1);
  });

  it.each(RENDERED)("api.%s resolves with its declared params", (code, entry) => {
    const counts = entry.params.includes("count") ? [1, 4] : [undefined];
    for (const count of counts) {
      const options: Record<string, unknown> = {};
      for (const param of entry.params) {
        options[camelizeKey(param)] = param === "count" ? count : `‹${param}›`;
      }
      if (count !== undefined) options.countDisplay = String(count);
      expect(i18n.exists(`api.${code}`, options), `api.${code}`).toBe(true);
      const text = (i18n.t as (key: string, options?: Record<string, unknown>) => string)(
        `api.${code}`,
        options,
      );
      expect(text, `api.${code}`).not.toBe("");
      expect(text, `api.${code}`).not.toContain("api.");
    }
  });

  it("no api.* entry interpolates a placeholder outside its code's declared params", () => {
    const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;
    const entries = [...flatten(enAU)].filter(([key]) => key.startsWith("api."));
    expect(entries.length).toBeGreaterThan(RENDERED.length);
    for (const [key, value] of entries) {
      if (key === "api.exportFailed") continue; // downloadFile's own key, not a wire code
      const code = key.slice("api.".length).replace(PLURAL_SUFFIX, "");
      const declared = apiErrorCodes.codes[code as keyof typeof apiErrorCodes.codes];
      expect(declared, `${key} maps to no wire code in api-error-codes.json`).toBeDefined();
      const allowed = new Set(declared.params.map(camelizeKey));
      if ((declared.params as readonly string[]).includes("count")) allowed.add("countDisplay");
      for (const name of placeholderNames(value).names) {
        expect(allowed.has(name), `${key} interpolates {{${name}}}, not declared for ${code}`).toBe(
          true,
        );
      }
    }
  });
});

/** Catalogue and manifest validation, pure functions over parsed JSON — no I/O,
 * so src/i18n/catalogue.test.ts can prove each check against inline bad
 * fixtures (its standing negative controls) before applying it to the real
 * files. The conventions enforced here are documented in docs/translating.md;
 * change them there and here together. */

export interface ManifestEntry {
  tag: string;
  nativeName: string;
  direction: string;
  enabled: boolean;
}

export interface Manifest {
  note?: string;
  languages: ManifestEntry[];
}

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;
const PLACEHOLDER = /\{\{([^{}]*)\}\}/g;
const MAX_DEPTH = 3;

/** CLDR plural categories for a language, sorted — the suffix set every plural
 * key group must carry, exactly. Always an explicit tag: the runner's own
 * locale must never leak into an assertion (.agents/lessons.md → "A
 * locale-dependent assertion is green only where the runner happens to live"). */
export function pluralCategories(tag: string): string[] {
  return [...new Intl.PluralRules(tag).resolvedOptions().pluralCategories].sort();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Nested catalogue → dotted keys. Structural problems (non-string leaves,
 * empty values, separator characters inside a segment, excessive nesting) are
 * reported rather than thrown so one pass lists everything wrong. */
export function flattenCatalogue(raw: unknown): {
  entries: Map<string, string>;
  problems: string[];
} {
  const entries = new Map<string, string>();
  const problems: string[] = [];
  if (!isRecord(raw)) {
    return { entries, problems: ["catalogue root is not an object"] };
  }

  const walk = (node: Record<string, unknown>, prefix: string, depth: number) => {
    for (const [segment, value] of Object.entries(node)) {
      if (segment.includes(".") || segment.includes(":")) {
        // "." and ":" are i18next's key and namespace separators.
        problems.push(`key segment "${segment}" contains a separator character`);
        continue;
      }
      const key = prefix ? `${prefix}.${segment}` : segment;
      if (typeof value === "string") {
        if (value === "") problems.push(`"${key}" is empty`);
        entries.set(key, value);
      } else if (isRecord(value)) {
        if (depth >= MAX_DEPTH) {
          problems.push(`"${key}" nests deeper than ${MAX_DEPTH} levels`);
        } else {
          walk(value, key, depth + 1);
        }
      } else {
        problems.push(`"${key}" is not a string or group`);
      }
    }
  };
  walk(raw, "", 1);
  return { entries, problems };
}

/** `{{name}}` interpolation params of one value. Reports unbalanced braces and
 * non-camelCase names; returns the names it could read either way. */
export function placeholderNames(value: string): { names: Set<string>; problems: string[] } {
  const names = new Set<string>();
  const problems: string[] = [];
  for (const match of value.matchAll(PLACEHOLDER)) {
    const name = match[1];
    if (!/^[a-z][a-zA-Z0-9]*$/.test(name)) {
      problems.push(`placeholder "{{${name}}}" is not a camelCase name`);
    }
    names.add(name);
  }
  // Anything left over after removing well-formed placeholders must not look
  // like half of one.
  const stripped = value.replace(PLACEHOLDER, "");
  if (stripped.includes("{{") || stripped.includes("}}")) {
    problems.push("unbalanced {{ }} braces");
  }
  return { names, problems };
}

/** One catalogue's key groups: plural variants collapsed onto their base key,
 * placeholder names unioned across variants. This is the unit two catalogues
 * are compared in — a language whose CLDR categories differ from English still
 * covers the same *bases*. */
export interface KeySummary {
  plural: boolean;
  placeholders: Set<string>;
}

export function summarize(entries: Map<string, string>): Map<string, KeySummary> {
  const bases = new Map<string, KeySummary>();
  for (const [key, value] of entries) {
    const plural = PLURAL_SUFFIX.test(key);
    const base = plural ? key.replace(PLURAL_SUFFIX, "") : key;
    const summary = bases.get(base) ?? { plural, placeholders: new Set<string>() };
    summary.plural ||= plural;
    for (const name of placeholderNames(value).names) summary.placeholders.add(name);
    bases.set(base, summary);
  }
  return bases;
}

/** Everything wrong with one catalogue on its own: value syntax, plural-group
 * shape for the catalogue's language, bare-and-plural collisions. */
export function catalogueProblems(entries: Map<string, string>, tag: string): string[] {
  const problems: string[] = [];
  for (const [key, value] of entries) {
    for (const problem of placeholderNames(value).problems) {
      problems.push(`"${key}": ${problem}`);
    }
  }

  const expected = pluralCategories(tag);
  const suffixes = new Map<string, Set<string>>();
  for (const key of entries.keys()) {
    const match = PLURAL_SUFFIX.exec(key);
    if (!match) continue;
    const base = key.slice(0, match.index);
    const group = suffixes.get(base) ?? new Set<string>();
    group.add(match[1]);
    suffixes.set(base, group);
  }
  for (const [base, group] of suffixes) {
    if (entries.has(base)) {
      problems.push(`"${base}" exists both bare and plural-suffixed`);
    }
    const actual = [...group].sort();
    if (actual.join(",") !== expected.join(",")) {
      problems.push(
        `"${base}" has plural forms [${actual.join(", ")}] but ${tag} needs [${expected.join(", ")}]`,
      );
    }
  }
  return problems;
}

/** A translated catalogue against the en-AU source: unknown keys are hard
 * failures (CI's "known keys" check), placeholder sets must match per base key,
 * bare-vs-plural shape must agree. Coverage is presence over the source's
 * bases; the manifest's `enabled` flag decides whether short of 100% fails —
 * the caller (test / report) applies that policy. */
export function compareToSource(
  source: Map<string, KeySummary>,
  target: Map<string, KeySummary>,
): { problems: string[]; missing: string[]; coverage: number } {
  const problems: string[] = [];
  const missing: string[] = [];
  for (const [base, summary] of target) {
    const expected = source.get(base);
    if (!expected) {
      problems.push(`"${base}" is not a key en-AU knows`);
      continue;
    }
    if (expected.plural !== summary.plural) {
      problems.push(`"${base}" is ${expected.plural ? "plural" : "bare"} in en-AU but not here`);
    }
    const want = [...expected.placeholders].sort().join(",");
    const got = [...summary.placeholders].sort().join(",");
    if (want !== got) {
      problems.push(`"${base}" placeholders [${got}] differ from en-AU's [${want}]`);
    }
  }
  for (const base of source.keys()) {
    if (!target.has(base)) missing.push(base);
  }
  const coverage = source.size === 0 ? 1 : (source.size - missing.length) / source.size;
  return { problems, missing, coverage };
}

export function validateManifest(manifest: unknown): string[] {
  const problems: string[] = [];
  if (!isRecord(manifest) || !Array.isArray(manifest.languages)) {
    return ["manifest has no languages array"];
  }
  const tags = new Set<string>();
  for (const entry of manifest.languages as unknown[]) {
    if (!isRecord(entry) || typeof entry.tag !== "string") {
      problems.push("manifest entry without a tag");
      continue;
    }
    const { tag } = entry;
    if (tags.has(tag)) problems.push(`"${tag}" is listed twice`);
    tags.add(tag);
    try {
      const canonical = Intl.getCanonicalLocales(tag);
      if (canonical.length !== 1 || canonical[0] !== tag) {
        problems.push(`"${tag}" is not written in its canonical form`);
      }
    } catch {
      problems.push(`"${tag}" is not a valid BCP 47 tag`);
    }
    if (typeof entry.nativeName !== "string" || entry.nativeName === "") {
      problems.push(`"${tag}" has no native name`);
    }
    if (entry.direction !== "ltr" && entry.direction !== "rtl") {
      problems.push(`"${tag}" direction must be "ltr" or "rtl"`);
    }
    if (typeof entry.enabled !== "boolean") {
      problems.push(`"${tag}" enabled must be a boolean`);
    }
  }
  const fallback = (manifest.languages as unknown[]).find(
    (entry) => isRecord(entry) && entry.tag === "en-AU",
  );
  // en-AU is the unconditional fallback (design §6.1) — it may never be
  // absent, disabled, or anything but left-to-right English.
  if (!isRecord(fallback)) problems.push("en-AU is missing from the manifest");
  else if (fallback.enabled !== true || fallback.direction !== "ltr") {
    problems.push("en-AU must stay enabled and ltr");
  }
  return problems;
}

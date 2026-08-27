/** Translation coverage, as a markdown table — `npm run i18n:report`, and CI
 * appends it to the job summary. Presentation only, exit 0 always: enforcement
 * (known keys, placeholder parity, plural shapes, the 100% bar for enabled
 * languages) lives in src/i18n/catalogue.test.ts, so a small local reimplement
 * of key-flattening here cannot mask a defect there. */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const i18nDir = join(here, "../src/i18n");

const manifest = JSON.parse(readFileSync(join(i18nDir, "manifest.json"), "utf8"));

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

/** Nested catalogue → set of base keys (plural variants collapsed). */
function baseKeys(node, prefix = "") {
  const bases = new Set();
  for (const [segment, value] of Object.entries(node)) {
    const key = prefix ? `${prefix}.${segment}` : segment;
    if (typeof value === "string") {
      bases.add(key.replace(PLURAL_SUFFIX, ""));
    } else if (value && typeof value === "object") {
      for (const base of baseKeys(value, key)) bases.add(base);
    }
  }
  return bases;
}

const catalogues = new Map(
  readdirSync(join(i18nDir, "catalogues"))
    .filter((name) => name.endsWith(".json"))
    .map((name) => [
      name.replace(/\.json$/, ""),
      baseKeys(JSON.parse(readFileSync(join(i18nDir, "catalogues", name), "utf8"))),
    ]),
);

const source = catalogues.get("en-AU") ?? new Set();

console.log("### Translation coverage\n");
console.log("| Language | Native name | Direction | Enabled | Keys | Coverage |");
console.log("| --- | --- | --- | --- | --- | --- |");
for (const entry of manifest.languages) {
  const bases = catalogues.get(entry.tag) ?? new Set();
  const present = [...source].filter((base) => bases.has(base)).length;
  const coverage = source.size === 0 ? 1 : present / source.size;
  console.log(
    `| ${entry.tag} | ${entry.nativeName} | ${entry.direction} | ${entry.enabled ? "yes" : "no"} | ` +
      `${present}/${source.size} | ${(coverage * 100).toFixed(1)}% |`,
  );
}

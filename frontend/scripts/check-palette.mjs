/** The Workbench rule (design §13.1): components use the semantic token
 * utilities from src/index.css — `bg-surface`, `text-muted`, `border-rule`,
 * `text-status-building` — never Tailwind's stock palette. The `@theme` block
 * there already removes the palette, so a stray `bg-zinc-100` produces no CSS;
 * this refuses the spelling, so the regression is a red lint step rather than a
 * colour someone notices missing later. Run by `npm run lint`; exit 1 lists
 * every offender as path:line: match. */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "../src");

const HUES =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|black|white";
const PREFIXES =
  "bg|text|border|border-[trblsexy]|ring|ring-offset|divide|outline|shadow|accent|fill|stroke|from|via|to|placeholder|caret|decoration";
// `<variant:>*<prefix>-<hue>[-<shade>][/<opacity>]`, standing alone — so a
// token named after a colour word (`text-text`) or a status (`text-status-…`)
// does not match, and neither does prose that merely contains a hue.
const PALETTE_UTILITY = new RegExp(
  `(?<![\\w-])(?:[\\w-]+:)*(?:${PREFIXES})-(?:${HUES})(?:-\\d{2,3})?(?:/\\d{1,3})?(?![\\w-])`,
  "g",
);

const offenders = [];
for (const entry of readdirSync(src, { recursive: true, withFileTypes: true })) {
  if (!entry.isFile() || !/\.(?:tsx?|css)$/.test(entry.name)) continue;
  const path = join(entry.parentPath ?? entry.path, entry.name);
  readFileSync(path, "utf8")
    .split("\n")
    .forEach((line, index) => {
      for (const match of line.matchAll(PALETTE_UTILITY)) {
        offenders.push(`${relative(here + "/..", path)}:${index + 1}: ${match[0]}`);
      }
    });
}

if (offenders.length > 0) {
  console.error(
    `${offenders.length} stock palette utilit${offenders.length === 1 ? "y" : "ies"} under src/ — ` +
      "use the semantic tokens in src/index.css (design §13.1):",
  );
  for (const offender of offenders) console.error(`  ${offender}`);
  process.exit(1);
}
console.log("check-palette: no stock palette utilities under src/");

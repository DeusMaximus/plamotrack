# Translating plamotrack

plamotrack's interface copy lives in per-language catalogue files that ship
with the repository. `en-AU` is the canonical source catalogue and the
unconditional fallback: anything a translation doesn't cover renders in
Australian English rather than as a blank or a raw key. Adding or improving a
language is a normal pull request — catalogue data plus one manifest entry, no
application code.

> **Status:** every page's copy is served from the catalogue (#22). New
> features add keys as they land, so an existing translation may drift below
> 100% between releases — the coverage report tells you what to top up.

## Where things live

| Path | What it is |
| --- | --- |
| `frontend/src/i18n/manifest.json` | The language registry: BCP 47 tag, native display name, text direction, and whether the language is enabled |
| `frontend/src/i18n/catalogues/<tag>.json` | One catalogue per language; `en-AU.json` is the source of truth for keys |
| `frontend/src/i18n/registry.ts` | The import map the runtime loads catalogues from — one line per language |
| `frontend/src/i18n/catalogue.test.ts` | The automated checks (run by `npm test`) |
| `frontend/scripts/i18n-report.mjs` | Coverage table — `npm run i18n:report` |

Two lists must always agree, and a backend test enforces it: the manifest's
*enabled* tags and `SUPPORTED_INTERFACE_LANGUAGES` in
`backend/app/services/instance_settings.py`. Enabling a language is one PR
that flips `enabled` **and** extends that tuple.

## Key conventions

- Keys are semantic, grouped, and dot-separated: `nav`, `common`, one group per
  page (`board`, `kits`, `orders`, …), and one group per domain vocabulary
  (`kitStatus`, `itemType`, …). Leaves are camelCase — except vocabulary
  leaves, which are the canonical wire value verbatim (`kitStatus.pre_ordered`)
  so code can look a value's label up directly.
- Key segments never contain `.` or `:` (they are the runtime's separators).
  Values may, freely.
- Interpolation uses `{{name}}` placeholders with camelCase, semantic names. A
  translation must use exactly the same placeholders as the `en-AU` value —
  reordering is fine, dropping or inventing one is an error.
- Plurals use i18next's suffix convention: `key_one`, `key_other`, and so on.
  The suffix set must match **your language's** CLDR plural categories, not
  English's — Japanese needs only `_other`; Polish needs `_one`, `_few`,
  `_many`, `_other`. The test suite checks this per language. English
  catalogues carry `_one`/`_other` pairs even where the words happen to be
  identical; that shape is the contract, not a redundancy.
- `count` is the reserved parameter that drives plural selection. Noun forms
  that aren't count-driven (dictionary singular/plural, like
  `itemType.display.singular`) are ordinary leaves instead.
- The plural endings themselves are reserved: never name an ordinary key so
  its last segment ends in `_zero`, `_one`, `_two`, `_few`, `_many` or
  `_other` — the shape checks would read it as a plural form.
- Values are never blank: an empty or whitespace-only value renders as an
  invisible label, so the checks refuse it. Whitespace around content is fine
  and preserved byte-for-byte.

## What is never translated

Canonical identifiers are the API, not presentation: REST/MCP enum values and
tool names, database values, CSV headers, and everything a user typed (kit
names, notes, retailer names, categories). Catalogues translate labels *for*
those values; the values themselves are stable on every surface.

## Proposing a language

1. Copy `frontend/src/i18n/catalogues/en-AU.json` to `<tag>.json` (the tag in
   its canonical BCP 47 form, e.g. `ja` or `pt-BR`) and translate the values.
   Keep every placeholder; adjust plural suffixes to your language's
   categories.
2. Add a manifest entry: `tag`, `nativeName` (in the language itself),
   `direction` (`ltr` or `rtl`), and `"enabled": false`.
3. Register the catalogue import in `frontend/src/i18n/registry.ts` — one
   line. That line is what loads your language into the application *and* puts
   it in front of the validation suite; the tests refuse a manifest entry
   without it.
4. Run `npm test` and `npm run i18n:report` from `frontend/`. The tests tell
   you about unknown keys, placeholder drift, and plural-shape problems; the
   report tells you coverage.
5. Open a PR with the coverage number in the description.

An incomplete catalogue is welcome in-tree as long as it stays
`"enabled": false` — the fallback covers the holes.

## The bar for enabling a language

`"enabled": true` means the language appears in the interface-language setting,
so it carries a review bar:

- 100% key coverage (the test suite enforces this for enabled languages).
- Green catalogue checks.
- The PR names who translated and who reviewed the language, and both agree
  it's ready.
- A visual pass of the major screens in that language — some strings only
  reveal their length or context problems when rendered.
- The same PR extends `SUPPORTED_INTERFACE_LANGUAGES` in
  `backend/app/services/instance_settings.py` (the parity test will insist).

## Reviewing a language PR

CI proves the mechanical half: keys are known, placeholders match, plural
shapes fit the language, coverage is what the PR claims. A human owes the
other half: the translation reads naturally, terminology is consistent across
screens, and nothing canonical got translated. Reviewers don't need to speak
the language to check the second list's last item — the first two need someone
who does.

# Translating plamotrack

plamotrack ships its interface translations with the application. Adding or
improving a language is a normal pull request: no translation service or
separate language pack is involved.

`en-AU` is the canonical source catalogue and the unconditional fallback. If a
translated catalogue does not contain a key, the interface renders that key in
Australian English rather than showing a blank label or a raw key.

> **Status:** every page's copy is served from the catalogue (#22). New
> features add keys as they land, so an existing translation may drift below
> 100% between releases. `npm run i18n:report` shows what needs topping up.

## Translation and regional formatting are separate

M5.1 introduced two independent parts of localisation:

- **Interface language** chooses the words in the UI. It must name an enabled
  catalogue shipped by this build.
- **Regional formatting** controls numbers, money, dates and times. It is made
  up of a formatting locale, IANA time zone, date style and hour cycle. These
  are instance settings and do not come from the translation catalogue.

For example, an owner can use a Japanese interface with Australian number and
date formatting. Selecting a language offers its tag as a convenient formatting
locale, but never changes the formatting setting automatically.

Adding `ja` as an interface language therefore does **not** require a separate
list of Japanese formatting rules. A well-formed locale such as `ja`, `ja-JP`
or `en-NZ` is already accepted as `formatting_locale`; the browser's `Intl`
implementation supplies the formatting data. The time zone remains an
independent IANA name such as `Asia/Tokyo`.

In short, a new disabled translation changes three places; enabling it changes
a fourth:

| Contribution state | Required changes |
| --- | --- |
| Incomplete, disabled translation | `<tag>.json`, `manifest.json`, `registry.ts` |
| Finished, selectable translation | The three above, plus `SUPPORTED_INTERFACE_LANGUAGES` |
| Another regional formatting locale | No repository change; save its canonical tag in Settings |

## How a catalogue reaches the browser

The language path is deliberately small and synchronous:

1. `manifest.json` describes each language and whether owners may select it.
2. `registry.ts` imports every catalogue that ships in the build.
3. `index.ts` gives those catalogues to i18next and fixes `en-AU` as the
   fallback language.
4. The instance settings row supplies `interface_language`. The frontend
   applies it, sets the document's `lang` and `dir`, and re-renders the app.

Only manifest entries with `"enabled": true` appear in **Settings → Language &
region**. A disabled catalogue still ships and is validated, which lets an
incomplete translation develop in-tree without being presented as finished.

## Where things live

| Path | What it is |
| --- | --- |
| `frontend/src/i18n/catalogues/en-AU.json` | Canonical source of every translatable key |
| `frontend/src/i18n/catalogues/<tag>.json` | One translated catalogue per language |
| `frontend/src/i18n/manifest.json` | BCP 47 tag, native name, text direction and enabled state |
| `frontend/src/i18n/registry.ts` | Import map used by both the runtime and validation suite |
| `frontend/src/i18n/index.ts` | Synchronous i18next setup and `en-AU` fallback |
| `frontend/src/i18n/catalogue.test.ts` | Catalogue, runtime and coverage checks |
| `frontend/src/i18n/validate.ts` | Pure validation rules used by the tests |
| `frontend/scripts/i18n-report.mjs` | Coverage table produced by `npm run i18n:report` |
| `backend/app/services/instance_settings.py` | Allow-list of enabled interface languages |

Two lists must always agree, and a backend test enforces it: the manifest's
enabled tags and `SUPPORTED_INTERFACE_LANGUAGES` in
`backend/app/services/instance_settings.py`. This prevents the API from storing
a language the browser cannot render, or the browser offering a language the
API refuses.

## Catalogue shape and key conventions

Catalogues are nested JSON objects with strings at the leaves. Keys are
semantic rather than copies of their English text, so translators can change a
sentence without changing the code that asks for it.

```json
{
  "nav": {
    "orders": "Orders"
  },
  "kitStatus": {
    "pre_ordered": "Pre-ordered"
  }
}
```

- Keys are grouped and dot-separated at runtime: `nav`, `common`, page groups
  such as `board` and `orders`, and domain vocabulary such as `kitStatus` and
  `itemType`.
- Leaves use camelCase, except vocabulary leaves that mirror a canonical wire
  value. For example, `kitStatus.pre_ordered` deliberately retains
  `pre_ordered` so the app can look up the display label for that API value.
- A catalogue may nest no deeper than three levels.
- Key segments may not contain `.` or `:` because i18next treats them as
  separators. Values may contain either character.
- Values may not be empty or whitespace-only. Meaningful surrounding
  whitespace is preserved byte-for-byte.
- Do not rename keys or invent translation-only keys. `en-AU` defines the key
  set; an unknown translation key fails the tests. A disabled, incomplete
  catalogue may omit source leaves so those messages use the fallback.

### Interpolation

Interpolation uses semantic camelCase placeholders such as `{{name}}` or
`{{countDisplay}}`. A translation must use exactly the same placeholder set as
the corresponding `en-AU` value. Reordering placeholders is fine; omitting one,
renaming one, or adding one is an error.

```json
{
  "welcome": "Welcome, {{name}}"
}
```

### Plurals

Plural messages use i18next suffixes: `_zero`, `_one`, `_two`, `_few`, `_many`
and `_other`. Each plural group must contain exactly the CLDR categories for
its language:

- English uses `_one` and `_other`.
- Japanese uses only `_other`.
- Polish uses `_one`, `_few`, `_many` and `_other`.

`count` is the reserved parameter that selects the grammatical form. The app
may also pass `countDisplay`, which contains the same number formatted for the
instance's regional locale; preserve both placeholders where the source uses
them.

English keeps `_one`/`_other` pairs even when both values happen to read the
same. The plural shape is part of the message's contract, not redundant copy.
Do not give an ordinary, non-plural key a name ending in a plural suffix.

## What is never translated

Canonical identifiers are the API, not presentation. Do not translate:

- REST or MCP enum values, tool names, error codes or parameter names;
- database values or CSV table names, headers and enum values;
- BCP 47 locale tags, IANA time-zone names or ISO currency codes; or
- user-entered content such as kit names, notes, retailers and categories.

Catalogues contain display labels and messages *for* known identifiers. Unknown
identifiers deliberately fall back to their raw value so a newer backend does
not become unreadable in an older browser.

## Add a new language

Use the canonical BCP 47 tag that describes the translation, such as `ja`,
`de`, `pt-BR` or `zh-Hant`. `Intl.getCanonicalLocales()` is a quick way to
check the spelling and casing.

### 1. Create the catalogue

Copy `frontend/src/i18n/catalogues/en-AU.json` to
`frontend/src/i18n/catalogues/<tag>.json` and translate its values. Keep the
JSON structure, keys and placeholders, but change plural suffixes to the CLDR
categories for the new language.

If the first contribution is intentionally incomplete, remove untranslated
non-plural leaves and whole untranslated plural groups before submitting it.
Keep every included plural group complete for the target language. Coverage
measures the presence of keys, not the language of their values, so leaving
English placeholders in every untranslated entry would misleadingly report
100%. Keep an English value only when it is genuinely the correct wording or
borrowing in the target language.

### 2. Add the manifest entry

Add the language to `frontend/src/i18n/manifest.json`:

```json
{
  "tag": "ja",
  "nativeName": "日本語",
  "direction": "ltr",
  "enabled": false
}
```

- `tag` is the canonical BCP 47 tag and must match the catalogue filename.
- `nativeName` is the language name written in that language.
- `direction` is `ltr` or `rtl`. The app uses it for the document direction,
  so right-to-left languages must say `rtl`.
- Start with `enabled: false` unless the same PR meets the enablement bar below.

### 3. Register the catalogue

Import the JSON file and add it to `CATALOGUES` in
`frontend/src/i18n/registry.ts`:

```ts
import ja from "./catalogues/ja.json";

export const CATALOGUES = {
  "en-AU": enAU,
  ja,
} as const;
```

This one map feeds both i18next and the validation suite. The tests refuse a
manifest entry without a registered catalogue, a catalogue without a manifest
entry, or a registered catalogue the runtime did not load.

### 4. Validate the contribution

From `frontend/`, run:

```bash
npm install
npm test
npm run i18n:report
npm run lint
npm run build
```

The tests check manifest validity, catalogue structure, known keys, placeholder
parity, plural shape, runtime loading and the 100% rule for enabled languages.
The report prints key coverage; it is informative rather than the enforcement
step.

Open the pull request with the language tag and reported coverage in its
description. An incomplete catalogue is welcome as long as it remains disabled
and the untranslated leaves are absent, allowing the `en-AU` fallback to serve
them honestly.

## Enable a finished language

Enabling a language makes it selectable for every client of the instance. In a
single pull request:

1. Bring the catalogue to 100% key coverage.
2. Set its manifest entry to `"enabled": true`.
3. Add its tag to `SUPPORTED_INTERFACE_LANGUAGES` in
   `backend/app/services/instance_settings.py`.
4. Run the frontend checks above and, from `backend/`:

   ```bash
   uv sync
   uv run pytest tests/test_settings.py
   ```

   The backend suite needs the Postgres service described in the repository's
   [development setup](../README.md#developing-on-it). CI runs the same parity
   check on the pull request.

No schema migration, REST route, settings form option or handwritten locale
formatter should be needed. The language selector is derived from the manifest,
the API allow-list is the tuple above, and formatting remains the browser's
job.

The review bar for enabling a language is:

- 100% key coverage and green catalogue checks;
- a translator and a language reviewer named in the pull request, with both
  agreeing that the catalogue is ready;
- consistent terminology and natural phrasing in context; and
- a visual pass of the major screens, including narrow layouts, interpolated
  messages, singular and plural counts, errors, dialogs, and long labels.

For an RTL language, also verify the document direction and the major layouts.
The app uses logical-direction utilities, but rendered inspection is what finds
an overlooked physical left/right assumption.

## Update an existing translation

Use `en-AU.json` and `npm run i18n:report` to find missing source keys. Add the
translated leaves using the same rules as a new catalogue. If the language is
enabled, CI requires it to return to 100% in the same change that adds new
source keys.

When English wording changes without a key change, coverage cannot identify a
stale translation: the key is still present. Feature pull requests should call
out changed source meanings, and translation reviewers should compare the
affected `en-AU` values rather than relying only on the percentage.

## Review a language pull request

CI proves the mechanical half: the language is registered and loadable, keys
are known, placeholders match, plural groups fit the language, and enabled
catalogues are complete. A human reviewer still needs to confirm that:

- the translation reads naturally in the rendered context;
- terminology is consistent across pages;
- English values have not been left merely to inflate coverage;
- canonical identifiers and user data remain unchanged; and
- the direction metadata and visual layout are correct.

A reviewer who does not speak the language can check structure, canonical
identifiers and layout. Natural phrasing and terminology need someone who does.

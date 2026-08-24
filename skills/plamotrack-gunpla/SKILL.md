---
name: plamotrack-gunpla
description: Conventions for logging Gunpla (Gundam plastic model kit) data in plamotrack, including kit names, numbers, grades, series, categories, tools, consumables, Gundam Markers, display items, upgrades, and retailers. Use whenever adding, editing, reviewing, or naming plamotrack records for a Gunpla collection, even when the request only says to log a kit, marker, tool, accessory, or Gundam-branded product. Not for other plastic-model genres unless the user asks to apply the same conventions.
---

# plamotrack — Gunpla conventions

plamotrack itself is generic: it tracks plastic-model hobbies, not just Gunpla. This skill is the Gunpla-specific layer on top — naming and categorisation conventions that keep a Gunpla collection consistent and scannable as it grows.

plamotrack's own MCP tool descriptions cover the mechanics — searching before creating, how orders spawn kits, when stock moves. This skill deliberately does not repeat them; it only adds the conventions the app cannot decide for you.

## The one rule that covers most of this

**Check before you create, then be consistent.** Some plamotrack fields are free text and will silently fragment if the same real-world thing is spelled two ways. Before adding a series, retailer, grade, category, manufacturer, or catalogue item, inspect the collection's existing values (`list_kit_series`, `search_catalog`, `list_catalog_categories`, the Retailers list, and relevant existing records) and reuse an established spelling when it represents the same thing.

Some choices below are genuinely collector-defined: which label to use for a continuity, how to classify an accessory pack or boxed set, how to name a regional Amazon storefront, or what a four-star kit means. Follow the collection's established house style rather than treating a personal preference as a universal Gunpla fact. If no convention exists, choose a clear one with the user and apply it consistently.

---

## Kit naming

**Strip the scale from the name.** Scale has its own field, so do not repeat it in the name. `HGUC 1/144 Gundam Ez8` becomes name `HGUC Gundam Ez8`, scale `1/144`. Better still, leave the scale *field* blank for standard-scale kits — plamotrack derives it from the grade (HG → 1/144, MG → 1/100, PG → 1/60) — and state it only when the kit differs from its grade's default, such as a 1/48 Mega Size or a 1/60 HG.

**Keep the structured grade broad; keep the precise product line in the name.** plamotrack's `grade` field is the collection's broad reporting bucket, such as `HG`, `MG`, `RG`, `EG`, `FM`, `PG`, or `SD`. More specific Gunpla line prefixes such as `HGUC`, `HGCE`, `HGAC`, `HGBF`, `HGBD`, `HGBD:R`, and `HGIBO` remain in the kit name but normally map to structured grade `HG`. For example:

- name `HGUC MS-06 Zaku II` → grade `HG`
- name `HGCE Aile Strike Gundam` → grade `HG`
- name `HGBF Star Build Strike Gundam Plavsky Wing` → grade `HG`

The broad bucket is not only about tidy filters: it is also what drives the automatic scale derivation above, so a kit filed under an invented grade like `HGUC` silently loses its derived 1/144 as well. plamotrack already knows `HG`, `RG`, `EG`, `MG`, `MGEX`, `MGSD`, `RE/100`, `FM`, `PG`, and `SD` as buckets with their own scale defaults — using one of those is not inventing a new grade.

Apply the same principle to other sub-lines while respecting the collection's existing buckets. Do not create a new structured grade such as `HGUC` merely because it appears in the official product name; doing so fragments grade filters and statistics. Distinct top-level lines that a collection already tracks separately may keep their established grade, but check before introducing one.

**Normalise names without erasing meaning.** Reuse the collection's established house style for whitespace, punctuation, Roman numerals, and common product-line spellings. Prefer one spelling for forms such as `Ver.RM` versus `Ver. RM`, `II` versus `Ⅱ`, and `Option Parts Set` versus `Options Part Set`. Preserve meaningful official model codes, version markers, bracketed descriptors, and suffixes; normalisation should make equivalent names match, not collapse genuinely different releases.

**Keep version suffixes.** `Ver.Ka`, `Ver.2.0`, `Ver.RM`, `[Beyond Global]`, and similar labels can denote different tooling or a different kit number. They are part of the identifying name and must not be dropped.

**P-Bandai and other exclusive releases get a bracket suffix:**

- Plain P-Bandai kit → append `(P-Bandai)`.
- Kit that already has a bracket suffix → fold it in: `(Parachute Pack)` becomes `(Parachute Pack - P-Bandai)`.
- Use the same pattern for other relevant exclusivity channels or variants, such as `(Gundam Base Limited)` or `(Clear Color Ver.)`.

Do not append a redundant exclusivity suffix when the canonical product name already communicates the same information unambiguously. The goal is to keep collector-relevant release information visible without duplicating it.

**What counts as "a kit" is collector-defined — state the definition, don't just apply it.** One coherent, common definition: a kit is one purchased box of runners you assemble, regardless of what it produces at the end — whether that's a single mobile suit, a weapon/accessory pack, or several distinct figures and terrain pieces in one box. Under this definition, both of the following follow naturally:

- **Option Parts Sets and accessory packs** are kits like any other, and reasonably take the grade of the product ecosystem they're built for: an EG Strike accessory pack as grade `EG`, an IBO option-parts set for HG kits as grade `HG`.
- **Multi-kit boxed sets** (e.g. a Ground War Set with several sub-models in one box) get **one row per purchased box**, not one row per physical model inside it.

A collector who instead defines "a kit" more narrowly — one buildable *model*, so an accessory pack isn't really a kit, or a boxed set should split into a row per figure — will reasonably want different rules than the two above. Either definition is internally consistent; what matters is picking one and applying it the same way across both cases, since they're really the same question (what counts as one purchase-to-build unit) asked twice. Check the collection's existing practice before assuming which definition is in play, and note the choice if it isn't otherwise obvious.

This is where a firm definition earns its keep rather than being pedantic. Two real P-Bandai releases show why:

- A box containing **two complete figures** (e.g. a Zaku II F Type and a Zaku II Unidentified Type variant, packaged together) — under the "one box = one kit" definition, this is still one row, even though it builds into two separate display-able models.
- A box containing **two figures plus a conversion parts set** that modifies a *different, separately-owned* kit into a new variant — same definition, same answer: still one row, even though one of the three things inside isn't a standalone model at all, it's parts that attach to something else already in the collection. Without the definition settled up front, this box is genuinely ambiguous — is it one kit, two, three, or does the conversion-parts portion not count as a "kit" at all? The definition resolves it the same way every time instead of needing a fresh judgment call per box.

---

## Kit number

Source the kit number from **manual.bandai-hobby.net** — the 品番 (part number) field on the kit's manual page. It matches the number printed on the box directly above the barcode, following the `645075-` prefix. For example, if the box shows `645075-2301235`, record kit number `2301235`.

**The box often carries a second, unrelated number — don't mistake it for the kit number.** Near the QR code / `bandai-hobby.net` website credit (usually a different panel to the main barcode), boxes commonly print a separate number (e.g. `5057955`) that won't return anything if searched on the manual site and isn't the kit number. The number that matters is the one directly above the barcode with the `645075-` prefix.

**The box number and the manual site number can differ by a single leading digit on some kits — the manual site wins.** Confirmed example: MG Crossbone Gundam X1 Ver.Ka shows `0145936` on the box, but the corresponding manual.bandai-hobby.net listing has 品番 `1145936` — same kit, leading digit differs (`0` vs `1`). This shows up on at least some older/premium re-release kits. When manual.bandai-hobby.net has a listing for the kit, treat that number as canonical over the box if the two disagree only in the leading digit; don't assume a typo and "correct" the site's number to match the box.

If a kit is not listed on the Bandai Hobby manual site, as can happen with older releases, some P-Bandai exclusives, or very recent releases, fall back to the same barcode-adjacent number on the physical box. If neither source is available, leave the kit number blank rather than guessing. A wrong number creates false matches later; a missing one does not.

**Don't confuse this with a retailer's own SKU or listing ID.** Most online retailers assign their own internal item number to a listing, which is not the same as Bandai's `645075-` box number and won't match it. If a number from a retailer's website doesn't appear anywhere on the physical box, it's a retailer SKU, not the kit number — don't record it as one.

---

## Series / continuity

Check `list_kit_series` before adding a new series. Beyond that, series naming is a collector-defined convention: some collectors prefer timeline names such as `Universal Century`, `Cosmic Era`, `After Colony`, `Anno Domini`, or `Post Disaster`; others prefer show titles such as `Gundam SEED` or `Iron-Blooded Orphans`. Either can work, but do not mix approaches accidentally. Follow the existing collection and prefer its more specific established series when a kit is tied to one, such as `08th MS Team` rather than the broader `Universal Century`.

**Treat blank metadata as incomplete, not contradictory.** A missing `series` or similar field may reflect an older import or a creation workflow, such as order entry, that did not expose every field. Do not infer that blanks are an intentional convention or use them to override populated examples. When reliable product information and an established collection convention make the value clear, fill the gap using that convention. If the correct value remains uncertain, leave it blank rather than inventing one.

---

## Categories

Tools, consumables, and display items each carry a required `category`, and each table keeps its own vocabulary. Check `list_catalog_categories` for the table before writing one and reuse a value that fits. A category matching an existing one case-insensitively is stored under the existing spelling automatically, but a near-miss — `cutters` versus `cutting` — creates a second grouping, which is why checking first still matters.

A workable Gunpla starting vocabulary, if the collection doesn't already have one:

- tools: `cutting`, `filing`, `gluing`, `airbrush`
- consumables: `paint`, `markers`, `cement`, `blades`, `sanding`
- display items: `stand`, `base`, `scenery`, `backdrop`

Whether Gundam Markers get their own `markers` category or fold into `paint` is collector-defined — pick one and stay with it.

---

## Tools & Consumables

Tools and Consumables do not have a manufacturer field, so include the maker in the name unless the item is generic or unbranded.

- Branded tools/consumables: `Tamiya Extra Thin Cement`, `GodHand Nippers`, `Mr. Surfacer 1000` (Mr. Hobby / GSI Creos)
- Generic/unbranded: `Cutting Mat`, `Tweezers` — no maker needed

**Gundam Markers are a special case within Consumables.** Lead with the product code because it is the most useful reorder identifier. The maker, GSI Creos under Bandai's licence, is implied and constant across the line, so it need not be repeated in every name.

- Individual markers: `GM01 Black Fine Tip`, `GM09 Light Green`, `GM302 Gray (Pour Type)`
- Sets: `GMS105 Basic Set`, `GMS106 G-Generation Set`
- Expected sub-families include standard, metallic, and weathering markers; Pour Type (`GM3xx`); Real Touch (`GM4xx`); and EX, AG, or POP lines. Use the same code-first pattern.

**Do not confuse Gundam Markers with Panel Line Accent Color.** It serves a similar purpose but is a different product line and has no GM code. Name it plainly: `Mr. Hobby Panel Line Accent Color (Black)`.

---

## Display items & Upgrades

Display items and Upgrades have a manufacturer field, so do not repeat the maker in the item name. Use `Action Base 1 (Gray)`, not `Bandai Spirits Action Base 1 (Gray)`.

Choose and reuse one canonical manufacturer spelling, such as `Bandai Spirits`, rather than alternating among `Bandai`, `Bandai Spirits`, and `BANDAI SPIRITS`. Otherwise manufacturer filters and statistics fragment just as series and grades do.

**Aftermarket decal sheets — waterslides, dry transfers, third-party sets — are Upgrades, not consumables.** Applying an upgrade to a kit records which kit got it and decrements stock, which is exactly what a decal sheet wants. Because upgrades carry a manufacturer field, the maker goes there, not in the name: name `Holo Water Decal — RG Nu Gundam`, manufacturer `Delpi Decal`, rather than a `Delpi Decal — …` name prefix.

---

## Retailers

Check the existing Retailers list before adding a new one. Decide how to distinguish regional variants of the same storefront, such as `Amazon (US)` and `Amazon (JP)`, according to the collector's buying habits, then use that convention consistently.

plamotrack has no retailer-level currency setting — the currency that matters is the one recorded on each order. State the order's `currency_code` whenever a purchase isn't in the instance's reference currency, and omit it only when it is; `get_meta` reports which currency that is. The currency recorded on the order is authoritative for that purchase.

---

## Optional: dated revision notes

When updating an existing kit's build notes later, such as for a re-rating or added observation, a lightweight `[YYYY-MM-DD] note` prefix can keep the field readable as a history. This is optional; plain freeform notes are also valid. Build lifecycle dates do not belong in notes at all — build started/completed and status changes have their own fields.

---

## Scope boundary

This skill covers Gunpla: Gundam-branded **plastic model kits**, including collector-defined boxed kits whose contents may be figures, vehicles, accessories, or other buildable parts. Gundam-adjacent non-plastic-kit product lines such as Metal Build, Metal Robot Spirits, S.H.Figuarts, and similar die-cast or ABS figure lines are out of scope. Do not apply these conventions to them merely because they are Gundam-branded.

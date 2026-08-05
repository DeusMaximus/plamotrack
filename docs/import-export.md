# Import & export

Your collection is yours. plamotrack stores it as plain CSV on the way out, and
reads the same files back in — so you can back it up, move it to another
instance, keep it in a spreadsheet, or leave for something else entirely.

Everything here lives on the **Data** page.

---

## Getting data out

| What | Where | Use it for |
|---|---|---|
| **Full archive** (`.zip`) | Data → Export | Backups, moving instances, keeping a copy |
| **Single table** (`.csv`) | Data → Export, or the button on any list page | Pulling one table into a spreadsheet |

The archive holds one CSV per table plus a `manifest.json`:

```json
{
  "format": "plamotrack-archive",
  "export_version": 1,
  "schema_version": "9d78b6148c30",
  "app_version": "0.1.0",
  "exported_at": "2026-08-06T04:09:31+00:00",
  "tables": { "kits": { "file": "kits.csv", "rows": 8 } }
}
```

`schema_version` is the live database migration revision. Importing an archive
written by a **newer** version of plamotrack is refused outright rather than
silently mangled; a mismatch in the other direction is just a warning.

---

## Getting data in

Three ways, all through Data → Import, and **nothing is written until you've seen
a preview of exactly what will change**.

### 1. The starter sheet — one row per kit

The fastest way in if you're coming from a spreadsheet, Notion, or Baserow.
Download `starter-sheet.csv`, fill it in, import it.

| Column | Notes |
|---|---|
| `kit_name`, `grade` | Required. |
| `scale` | Blank derives it from the grade (HG → 1/144, MG → 1/100, PG → 1/60). |
| `kit_number`, `build_notes` | Optional. |
| `status` | `pre_ordered` / `ordered` / `in_transit` / `backlog` / `building` / `complete`. Blank = backlog. |
| `rating` | 1–5, if you've finished it. |
| `quantity` | How many of this kit. Blank = 1. |
| `retailer` | Where you bought it. **Blank = no order recorded**, just a kit in the collection. |
| `order_date`, `order_number` | The purchase. Rows sharing a retailer + date + number collapse into **one order**. |
| `unit_price`, `currency` | Major units (`49.99`). Currency blank = AUD. |
| `received` | `yes`/`no`. Blank = yes. Received-on defaults to the order date, not today. |

You write kits; plamotrack works out the retailers, orders, and order lines.

### 2. The template pack — one file per table

`plamotrack-templates.zip` holds a blank, header-only CSV for every table, in
exactly the export's shape, plus `COLUMNS.txt` describing every column. Use this
when you want to control tools, consumables, upgrades, or multi-line orders
precisely. Fill in whichever files you have data for — every file is optional.

### 3. An archive — restoring or merging a previous export

Drop the `.zip` straight back in.

---

## Modes

| Mode | Matched rows | New rows |
|---|---|---|
| **Merge** (default) | Updated | Added |
| **Add only** | Left completely alone | Added |
| **Replace everything** | *Whole collection deleted first*, then restored | Added |

Replace everything requires typing `REPLACE` to confirm, and tells you how many
existing records it will delete before you do.

---

## How plamotrack avoids duplicating things

This is the part that matters if you import the same file twice, or bring an
archive into an instance that already has data.

**Every row carries an `id`.** On import, a row whose id already exists *is* that
record. Import an archive into an empty instance and every uuid is preserved
exactly, so all the internal links survive untouched.

**Rows without an id fall back to a natural key:**

| Table | Matched on |
|---|---|
| Retailers | Name, case-insensitive |
| Tools / consumables / upgrades | Name, case-insensitive, within that table |
| Orders | Retailer + order number. No order number? Retailer + date + the set of lines |
| Order lines | Their line details, within the order they belong to |
| Upgrade applications | Upgrade + kit + date applied |
| **Kits** | **Never matched automatically** — see below |

**Kits are deliberately excluded.** A kit row is one *physical* kit, so two of the
same product are legitimately two rows. Matching them by name would silently merge
purchases you actually made. Instead, importing a kit that looks like one you own
tells you so in the preview — "you already have 2 kits called 'Gouf Custom'" — and
lets you decide.

**References follow the match.** If your archive's `orders.csv` points at retailer
`abc-123`, and this instance already has that shop under a different uuid, the
reference is rewritten to the local one. You don't end up with two Hobby Link Japans.

---

## Two rules worth knowing

**Stock never comes from orders.** `quantity_on_hand` is read only from
`tools.csv` / `consumables.csv` / `upgrades.csv`. Importing an order — even a
received one — never changes what you have on hand. Otherwise re-importing would
quietly double your paint collection.

**A blank cell in a column you included means "empty this field".** A column you
*leave out of the file entirely* is left alone. So a partial CSV with just
`id,name` renames things without touching anything else, while a full archive
restores nulls faithfully. (The starter sheet only ever emits columns it actually
knows about, so importing a kit list won't wipe a retailer's rating.)

---

## Editing the CSVs by hand

Two conveniences make the files readable, and both follow the same rule — **the
canonical column wins when both are filled in**:

- Every `*_id` column has a readable twin: `retailer_name` beside `retailer_id`,
  `catalog_name` beside `catalog_ref_id`. Fill in either.
- Every `*_minor` money column has a major-unit twin: `unit_price` (`49.99`)
  beside `unit_price_minor` (`4999`). Money is stored as whole minor units so it
  can't drift through floating point; the major column is for typing.

On `order_items`, the `kit_*` columns mirror the kits a line bought. If you import
an order line whose kits aren't in the file, those columns are what plamotrack
creates them from.

Dates are `YYYY-MM-DD` (though `14/03/2026` and `03/14/2026` are accepted).
Leave `id` blank on rows you add by hand.

---

## Limits and safety

- One transaction: if any row is unreadable, **nothing** is imported. The preview
  shows you which line, and why, before you get that far.
- 10 MB / 50,000 rows per import.
- Apply re-checks the plan against a fingerprint of what you previewed. If the
  collection changed in between, it refuses and asks you to preview again rather
  than writing something you didn't agree to.

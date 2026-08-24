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
| `series` | e.g. `Iron-Blooded Orphans`. Free text — match your own earlier spelling. |
| `status` | `pre_ordered` / `ordered` / `in_transit` / `backlog` / `building` / `complete`. Blank = backlog. |
| `rating` | 1–5, if you've finished it. |
| `build_started`, `build_completed` | `YYYY-MM-DD` — when you started / finished the build. Blank = not recorded; the importer never invents one. |
| `quantity` | How many of this kit. Blank = 1, at most 1,000 per row. You get that many kits in your collection either way — whether the row names a retailer or not — so a bigger haul goes on more than one row. Starter rows spell their kits out as ordinary rows, so the whole sheet answers to the 50,000-row limit (see Limits). |
| `retailer` | Where you bought it. **Blank = no order recorded**, just a kit in the collection. |
| `order_date`, `order_number` | The purchase. Rows sharing a retailer + date + number collapse into **one order** — across separate imports too, so **fill in `order_number` whenever a shop + date pair isn't unique**. A row that reaches an existing order and names a kit already on it *restates that purchase line* (its price and quantity included) rather than adding a second one; a second copy of the same kit on one order is a second row in the **same** sheet. |
| `unit_price`, `currency` | Major units (`49.99`). Currency blank = your instance's `REFERENCE_CURRENCY` (`AUD` unless you changed it). The example rows in the downloaded sheet are already filled in with yours. |
| `received` | `yes`/`no`. Blank = yes. Received-on defaults to the order date, not today. When several rows collapse into one order you only need to say it once — but if two rows of the same order say *different* things, that's an error rather than a guess. Re-importing with `no` un-marks an order you'd previously imported as received. |

You write kits; plamotrack works out the retailers, orders, and order lines. Every
kit column travels whether or not the row names a retailer — `rating`,
`build_notes`, `series` and the build dates land on the kit either way.

### 2. The template pack — one file per table

`plamotrack-templates.zip` holds a blank, header-only CSV for every table, in
exactly the export's shape, plus `COLUMNS.txt` describing every column. Use this
when you want to control tools, consumables, upgrades, display items, or multi-line orders
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
| Tools / consumables / upgrades / display items | Name, case-insensitive, within that table |
| Orders | Retailer + order number. No order number? Retailer + date + the set of lines |
| Order lines | Item, quantity, unit price **and currency**, within their order |
| Upgrade applications | Upgrade + kit + date applied |
| **Kits** | **Never matched automatically** — see below |

An ambiguous match — two stored retailers or two catalog rows that differ only in
case or surrounding whitespace — is reported as an error row asking for an explicit id.
The application itself no longer creates that pair: since 0.2.7, adding or renaming a
retailer, tool, consumable, upgrade or display item onto a name another row of the same table
already holds is refused. If an instance still carries one from before, rename one of
the two in the app and import again.

**Category spellings fold only on brand-new rows.** In the app, giving an item a
category that matches an existing one case-insensitively stores the existing
spelling, so "stands" and "Stands" stay one group. The importer applies the same
rule to rows it *creates* without an id — a new row has no stored spelling to
preserve, and the preview tells you when one will be stored under an existing
spelling. Rows that update or restore existing records keep your file's spelling
verbatim, which is what keeps re-importing an export a no-op. If an instance holds
two spellings of one category from before this rule, both appear in the category
list — edit the rows you want folded together and the app will converge them.

**Kits are deliberately excluded.** A kit row is one *physical* kit, so two of the
same product are legitimately two rows. Matching them by name would silently merge
purchases you actually made. Instead, importing a kit that looks like one you own
tells you so in the preview — "you already have 2 kits called 'Gouf Custom'" — and
lets you decide.

**A price is a number *and* a currency.** ¥1000 and A$1000 are two different
purchases, and neither matching nor the preview will treat one as the other. It
doesn't matter which way you write the amount — `unit_price_minor` or the
major-unit `unit_price` beside it — both are compared in the same units.

**The same thing twice in one upload is refused.** Two rows sharing an `id`, or two
new rows naming the same retailer or catalog item, are reported in the preview with
the row numbers rather than merged or created twice. Two rows that each carry their
own `id` are always two records, even if they have the same name — that is what
keeps a collection holding two shops of the same name exportable and importable.

**References follow the match.** If your archive's `orders.csv` points at retailer
`abc-123`, and this instance already has that shop under a different uuid, the
reference is rewritten to the local one. You don't end up with two Hobby Link Japans.

---

## Two rules worth knowing

**Stock never comes from orders.** `quantity_on_hand` is read only from
`tools.csv` / `consumables.csv` / `upgrades.csv` / `display_items.csv`. Importing an order — even a
received one — never changes what you have on hand. Otherwise re-importing would
quietly double your paint collection.

**A blank cell in a column you included means "empty this field".** A column you
*leave out of the file entirely* is left alone. So a partial CSV with just
`id,name` renames things without touching anything else, while a full archive
restores nulls faithfully. (The starter sheet only ever emits columns it actually
knows about, so importing a kit list won't wipe a retailer's rating.)

That is about columns the app can leave empty. **A column it can't** — a kit's
created date, an order's retailer, a stock count — reads a blank cell as nothing
said rather than as an instruction, because there is no such thing as an order with
no shop. On a row you're updating, the stored value stays and the preview says so.
On a *new* row there's nothing to keep, so either the app fills it in for you (dates
and counts do this) or the row is refused by name, rather than failing halfway
through the import.

**A reference to something that isn't here is reported, not quietly dropped.** If a
row points at an order line or a catalog item that exists neither in this instance
nor anywhere in the file, the row still imports — that's what makes "import just
`kits.csv` into a fresh instance" work, where every row names an order the new
instance has never had — but the preview says which rows lost which link, so it's
your call rather than a surprise.

A **retailer** behaves differently, because an order can't be without one. Point an
existing order at a shop that isn't here and the order keeps the shop it already
had; enter a *new* order that way and the row is refused. Either way nothing is
lost quietly, but nothing is dropped either. The same goes for any other column the
row can't do without.

Money pairs bend the first half of that rule, because an amount with no currency
isn't storable: leaving `converted_currency_code` on `order_items` — or
`unit_cost_reference_currency` on `tools` — blank in a column you *did* include means
"the instance's reference currency", not "empty". The second half holds as written:
leave the column out of the file and an amount you correct keeps the currency it was
already recorded in, rather than being relabelled with yours.

---

## What an import can't do to an order

An order is a purchase record, and some of it is fact rather than a field. A sheet
that would change one of these is refused in the preview, naming the row and the
column, before anything is written.

**A line can't change what it is or which order it's on.** `item_type` and
`order_id` are settled when the line is entered. A kit line has already become
kits; a tool line has already moved (or will move) your on-hand count, and the two
can't swap without stranding whichever side effect already happened. Moving a line
between orders would take its kits with it and quietly rewrite what was bought
where. To correct either, leave the line alone and enter a new one. The Orders page
refuses both for the same reasons.

**A catalog line has to point at something.** Tool, consumable, upgrade and
display lines all need either `catalog_ref_id`, or a name in `catalog_name` — which
creates the item for you at 0 on hand, with a placeholder in any column it can't
know (category, manufacturer). A line pointing at nothing can never move stock in either direction, so
it's refused rather than stored.

**A received order can't become pending, and a pending order with a catalog line
can't be marked received.** This is the one that surprises people, so:

Importing never changes `quantity_on_hand` (the rule above). Marking a pending
order received through `orders.csv` would therefore leave the paint and tools it
bought uncounted, *and* leave the order reading as received — so the app would then
refuse to receive it, and the stock would never be applied at all. Clearing
`received_at` on an order that genuinely arrived is the mirror image: the stock it
already added stays where it is, and the next receive adds it a second time.

So on an order that holds a tool, consumable, upgrade or display line, `received_at` may not
be moved into or out of "received" by an import. What you can do instead:

- **To mark a pending order received:** leave `received_at` out of the sheet and
  receive the order in the app, which applies the stock. Stating the on-hand
  quantity in the catalog files does *not* stand in
  for that — it corrects a number, and the receipt in the sheet is still refused.
- **To correct a count on its own,** on an order you are not flipping: state it in
  `tools.csv` / `consumables.csv` / `upgrades.csv` / `display_items.csv`. That's where
  stock comes from.
- If you marked an order received **by mistake**: un-receiving isn't supported
  anywhere in plamotrack, by import or otherwise. Delete the order — that reverses
  the stock it applied — and enter it again as pending.

Everything else about receipt still imports:

- an order that holds only kit lines moves in both directions — that's the ordinary
  starter-sheet case, where a kit you already own arrives already received. The kits
  the receipt advances to backlog are stamped with the arrival instant the sheet
  states, the same as receiving in the app. The preview says so up front — a count
  of the kits that will move, and a message on each order saying which way — and
  the apply is held to exactly that set: if a kit moves in the app between preview
  and apply, the apply refuses and asks you to preview again;
- a **new** order imports with its receipt intact, in any mode. A full archive
  carries the received order *and* the post-receipt `quantity_on_hand` together, so
  restoring one is never ambiguous;
- correcting a received order's date to a different date is fine — it changes when,
  not whether. It moves the order's own date only: unlike a correction in the app, a
  CSV correction never re-dates the kits that arrived with the box.

One more rule, on any order: **a receipt date in the future is refused** — an
arrival can be backdated, not predicted, and the app refuses the same value
everywhere else. This applies where the sheet *changes* `received_at` (marking an
order received, or correcting its date); a row restating a value the order already
holds is left alone, and a **new** order imports whatever its sheet says — a
restore records the past, even when the past held something odd.

**`shipped_at` is simpler, because it never touches stock.** Marking an order
shipped through `orders.csv` works on any order — including ones with tool, display,
consumable or upgrade lines — and moves its waiting kits to In Transit, stamped
with the date the sheet states. The preview shows these moves the same way it shows
a receipt's — the count, and a message on the order saying which way — and the
apply is held to exactly that set: if a kit moves in the app between preview and
apply, the apply refuses and asks you to preview again. The same two rules apply:
a future ship date is refused, and clearing `shipped_at` is refused (un-shipping
isn't supported anywhere — remember that a blank cell in an included column means
"empty this field", so restate the ship date on sheets that carry the column).

**Reducing a kit line's quantity removes kits.** A line that says 1 where the
collection holds 3 is a disagreement, so the import gives up the extra kits — newest
first, and never one you've started: a kit that's building or complete, rated,
photographed, or carrying an applied upgrade is kept and the row is refused instead.
Kits named in the same upload's `kits.csv` are kept too, and a sheet that both lists
two kits and says the line bought one is refused rather than silently resolved. The
preview counts these deletions before you apply, the same way it counts a
replace-everything import's.

The count is of the kits the line will hold *after* the import, not before it. If the
same upload's `kits.csv` also moves a kit onto or off that line via `order_item_id`,
that move is counted first.

**Only a quantity you change authorises any of this.** A line whose `order_items.csv`
row restates its quantity unchanged — every line of a full archive does — describes
the line; it doesn't instruct the import to delete or spawn kits to make a move fit.
So moving a kit onto or off such a line is refused until you also say what the line
now holds: change its quantity in the same upload and the move lands, with the count
reconciled to the number you wrote. Re-importing an archive therefore never changes
your collection, whatever it holds.

Your own export can still contradict itself. Importers before 0.2.6 let a line end
up holding more kits than its quantity said, and a *replace everything* restore of an
archive taken from such an instance is refused with *"this line says quantity N, but
this upload supplies M kit(s)"* — every row is a create there, and the file is the
only world. Nothing is lost: `docs/operations.md` has the query that finds those
lines and the one-click fix in the app; or raise the quantity in `order_items.csv`
to match the kits that are really there, and import again.

---

## Editing the CSVs by hand

Two conveniences make the files readable, and both follow the same rule — **the
canonical column wins when both are filled in**:

- Every `*_id` column has a readable twin: `retailer_name` beside `retailer_id`,
  `catalog_name` beside `catalog_ref_id`. Fill in either.
- Every `*_minor` money column has a major-unit twin: `unit_price` (`49.99`)
  beside `unit_price_minor` (`4999`). Money is stored as whole minor units so it
  can't drift through floating point; the major column is for typing.

  How many minor units make one of the major follows the row's own currency, per
  ISO 4217: `49.99` AUD is `4999` cents, `1200` JPY is `1200` yen, and `1.234` KWD
  is `1234` fils. A code we don't recognise is imported as typed and read as having
  two decimal places — the preview flags it, so a mistyped `AUS` is visible before
  you apply it rather than after.

On `order_items`, the `kit_*` columns mirror the kits a line bought. If you import
an order line whose kits aren't in the file, those columns are what plamotrack
creates them from.

Dates are `YYYY-MM-DD` (though `14/03/2026` and `03/14/2026` are accepted).
Leave `id` blank on rows you add by hand.

### How numbers are read

A cell that can be read two ways is refused rather than guessed at, and the preview
names the row and column. The rule is that plamotrack will never quietly store a
different number from the one you wrote.

- **Whole-number columns** — quantities, ratings, thresholds, `*_minor` amounts —
  take whole numbers only. `3` and `3.0` both mean three; `1.9` is an error rather
  than a silent `1`. They also have to fit in a 32-bit integer — anything below
  -2,147,483,648 or above 2,147,483,647 is reported on the row instead of failing
  partway through the import.
- **A comma is only ever a thousands separator**, and only where it can't be
  anything else. `1,299.50` and `1,234,567` are fine — a decimal point already
  present, or a second comma, rules out any other reading. `12,34` is refused,
  because most of the world writes 12.34 that way and reading it as `1234` would
  store a hundred times the real price.
- **A single comma with no decimal point depends on the currency.** `1,234` is
  either one thousand two hundred and thirty-four, or the way much of the world
  writes `1.234` — a thousandfold difference. Where the currency has no minor unit
  it can only be the first, so `1,234` JPY imports as ¥1234. Everywhere else it's
  refused: in KWD it would be either 1,234,000 fils or 1234, and nothing in the
  cell says which. Write `1234`, or `1.234`, and it's unambiguous.
- **`1e2` works**, in both whole-number and money columns — spreadsheets and number
  inputs emit exponent notation on their own, so it's read the way they mean it.

If a sheet imported cleanly before and now reports errors on these, the errors are
the point: those cells were being read as numbers the sheet didn't say.

### Older exports still import

Column names occasionally change. When one does, the old name keeps working as an
alias — an archive you exported months ago imports as cleanly as one you exported
today, and re-importing it is still a no-op. Exports always write the current name.

So far there is one:

| Old column | Current columns | Notes |
| --- | --- | --- |
| `converted_price_aud_minor` | `converted_price_minor` + `converted_currency_code` | Rows under the old name are read as **AUD**, since that's what the name meant — even if your instance uses a different reference currency. |

One column changed meaning rather than name. Before v0.2.3-alpha, `tools.csv` held a
tool's price in a `unit_cost_reference` column of major units and recorded no currency
at all. That column still exists and still takes major units — it is now the readable
twin of `unit_cost_reference_minor` — but a row that doesn't name a currency is read
as being in your instance's reference currency. Re-importing a pre-0.2.3 `tools.csv`
into an instance whose reference currency isn't the one those prices were entered in
will therefore label them wrongly; set `unit_cost_reference_currency` in the file to
say what they really were.

---

## Limits and safety

- One transaction: if any row is unreadable, **nothing** is imported. The preview
  shows you which line, and why, before you get that far.
- 10 MB uploaded / 100 MB unpacked / 50,000 rows per import. The second one matters
  only for zips: a small archive can hold a very large amount of CSV, and the limit
  is checked while the archive is being read rather than after.
- One import can **create at most 10,000 kits from order lines** between them, even
  when every row is within its own 1,000. That counts only kits the import has to
  invent — kits your file lists explicitly in `kits.csv` are ordinary rows under
  the row limit, so a full archive of any size restores fine. The preview refuses
  up front and names the total.
- **Files must be UTF-8.** A file that isn't is refused by name and line number
  rather than imported with the odd character replaced — if your spreadsheet offers
  a plain "CSV" and a "CSV UTF-8", pick the second. A byte-order mark is fine.
- An archive exported by plamotrack is checked against its own `manifest.json`, in
  both directions. Missing data blocks the import; data that's merely not what the
  manifest describes is reported and left to you:
  - a file the manifest lists that isn't in the zip **blocks** — the archive is
    truncated or was only partly extracted;
  - two files with the same name — whether in one folder or in two — also **block**,
    because there is then no telling which one the manifest is describing;
  - a file that's shorter than the manifest says, a file the manifest never mentions,
    and a file filed under the wrong table each **warn**, naming the file.
  - A zip with no `manifest.json` is read as a loose set of CSVs and none of this
    applies, which is the simplest way to import part of an export on purpose.
- Apply re-checks the plan against a fingerprint of what you previewed. If the
  collection changed in between — or if the file itself did — it refuses and asks
  you to preview again rather than writing something you didn't agree to.
- **Every import is previewed first.** The browser does this for you. If you're
  driving the API yourself, `POST /import/apply` requires the `plan_hash` that
  `POST /import/preview` returned for that same file and mode; without it you get
  a 422. There is no way to apply an import nobody looked at.

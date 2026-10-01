plamotrack export
=================

This archive is your collection, in plain CSV. Nothing in here is locked to
plamotrack — open the files in any spreadsheet, keep them as a backup, or edit
them and import them back.

  manifest.json    what this archive is, and which schema version wrote it
  *.csv            one file per table

To restore or merge it: plamotrack -> Data -> Import, and drop this zip in.
You get a full preview of what will change before anything is written.

Two things worth knowing if you plan to edit these by hand:

  * Every `*_id` column has a readable twin (`retailer_name`, `catalog_name`).
    Fill in either one. The id wins when both are set and the id is known.
  * Money is stored as whole minor units (`unit_price_minor` = cents), with a
    major-unit twin (`unit_price` = 49.99) beside it. Same rule: the minor
    column wins when both are set.

Leave the `id` column blank on rows you add by hand and one will be generated.

Cells hold exactly what you stored -- including text starting with =, +, - or
@, which a spreadsheet may read as a formula rather than text. plamotrack does
not escape these on the way out, because the escape would come back through an
import as part of the value. Your own export holds only your own data; an
archive someone else sent you deserves the same caution as anything else they
sent you.

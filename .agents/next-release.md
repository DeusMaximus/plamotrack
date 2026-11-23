# What the next release owes

The user-facing docs — the docs site (`DeusMaximus/plamotrack-docs` →
https://docs.gunp.la) and the README's user-facing parts — describe the **published
release**, never `main` (`AGENTS.md` → Release artifacts). So a change a user would
notice reaches `main` without its docs, and this file holds what they owe until the
release that ships it.

- **Written in the same PR as the change**, one section per change, so it is reviewed
  with the code and merges with it. A change nobody using the release would notice
  (tests, CI, dev tooling, `docs/design.md`, `.agents/`) needs no entry.
- **Read at release**, in `.agents/releases.md` step 7. The release notes and the docs
  site's changelog are written from the **Release note** lines. The README and the
  docs site pages get what the other lines list, and land with the publication, not
  before it.
- **Trimmed once the release is published**, in the docs commit that records it on
  `main`. That commit removes the entries the release shipped — every change in the
  tagged commit — and keeps any merged after the tag, which the following release
  owes. So the file only ever holds what is unreleased; git history keeps what each
  release shipped. (Not in the version-bump PR: that is step 1, and step 7 still
  needs the entries.)
- Hand-off entries point here; they do not copy the list.

Shape:

```markdown
## #NNN — what changed, in a user's words (PR #NNN, `sha`)
- **Release note:** one or two sentences a user of the release reads.
- **README:** which sections change, and where the new wording is if it was
  written already. Or "nothing".
- **Docs site:** which pages change and what they must say. Or "nothing".
```

---

## #348 — an order can carry a note (PR #357)
- **Release note:** Orders have a free-text notes field, for what no other field holds:
  how it was paid, a substitution, a partial refund. It is in the order editor and under
  an order's expanded lines, on the `create_order`, `update_order`, `get_order` and
  `list_orders` tools, and in `orders.csv`. A note changes no total and no stock.
- **README:** nothing. The MCP tool table does not list a tool's fields.
- **Docs site:** `using/kits-and-orders.mdx`: one line that the order editor has a Notes
  field and that the note shows under the order's expanded lines. `using/import-export.mdx`
  lists the starter sheet's columns, which have no `notes`, so nothing there.

## #349 — an order can hold something the collection doesn't track (PR #360)
- **Release note:** An order line can be of type **Other**: something on the order that
  isn't a kit, tool, consumable, upgrade or display item, such as a magazine in a mixed
  basket. It takes a description, a quantity and a price, counts toward the order's
  total, and adds nothing to the collection: no kit, no catalog item, no stock. It is in
  the order editor, on `create_order` and `update_order` (`item_type: "other"` with a
  `description`), and in `order_items.csv`. A line's type still can't be changed, so to
  start tracking something, remove the line and add a kit or catalog line.
- **Release note (archives):** The archive's `export_version` is now 2. This release
  reads archives from every earlier release. An earlier release refuses an archive
  written by this one and says to update first.
- **Upgrade note:** one migration (`61442608b20e`). Downgrading past it is refused
  while any order holds an Other line.
- **README:** nothing. The MCP tool table does not list a tool's fields.
- **Docs site:** `using/kits-and-orders.mdx`: the line types an order takes now include
  Other, what it is for, and that it is never tracked. `using/import-export.mdx`: the
  archive's version, and that an older release refuses a newer archive.
- **Other docs:** `docs/import-export.md`: `description` in `order_items.csv`; the
  manifest example's `export_version`; and in "What an import can't do to an order",
  that the receipt and joining rules are about tool, consumable, upgrade and display
  lines, so an Other line is as free as a kit line, and that a description on any other
  type of line is refused.

## #350 — an order records discounts, vouchers and gift cards, and what was paid (PR #362)
- **Release note:** An order can record what came off its price at the checkout: a
  discount, a promo code, a voucher, a gift card. Each is a label and an amount in the
  order's currency, entered under the lines in the order editor. Line prices stay what
  the shop charged, and the order shows what was actually paid: in the Orders list's
  total and in a breakdown under the order's lines. Together they can't come to more
  than the order's lines in its currency plus its shipping. On `create_order` and
  `update_order` as `adjustments`, on every order read with per-currency `totals`
  (items, shipping, adjustments, paid), and in a new `order_adjustments.csv`.
- **Release note (changed behaviour):** the Orders list's total is now what was paid.
  For an order with no adjustments that is the same figure as before.
- **Upgrade note:** one migration (`b7d4f0a3c915`). Downgrading past it is refused
  while any order holds an adjustment.
- **README:** nothing. The MCP tool table does not list a tool's fields.
- **Docs site:** `using/kits-and-orders.mdx`: recording a discount or gift card on an
  order, that line prices are left alone, the Paid breakdown, and the limit.
  `using/import-export.mdx`: nothing for the starter sheet, which has no adjustments.
- **Other docs:** `docs/import-export.md`: the new `order_adjustments.csv` (columns,
  that `order_id` is required so an adjustment can only join an order that has an id,
  matching without an id on order + label, so two under one label on one order need ids), the archive's file list, and in
  "What an import can't do to an order", the limit: judged on the order as it lands,
  whichever of the three sheets changed it.

## #351 — reconcile documentation drift (pending next-release task)
- [ ] Complete [#351](https://github.com/DeusMaximus/plamotrack/issues/351) during
  the next release cycle, including the smaller Kanban and frontend README items.
  The issue records ten findings, source links pinned to `9908d5f`, verification,
  and completion criteria. This is pending work, not a shipped correction.
- **Release note:** none required for this documentation-only task.
- **README:** correct token permissions and MCP OAuth wording, phone import and
  starter-sheet support, source-development `.env` setup, and the Node version floor.
- **Docs site:** check the corresponding token, phone-import, archive-compatibility
  and release-installation claims; correct confirmed duplicates. The audit covered
  this repository, not a full audit of the separate docs site.
- **Other docs:** correct the archive-version explanation in `docs/import-export.md`,
  implemented-authentication and Kanban claims in `docs/design.md`, release-status
  and source-build wording in `AGENTS.md` and `docs/design.md`, and replace the
  generic `frontend/README.md` with a short project-specific orientation.

## #333 — a sign-out that fails says so, and the page keeps working (PR #340)
- **Release note:** If signing out fails (the server errors or the connection
  drops), plamotrack now says so beside the Sign out control, and you stay signed in
  with everything working; if plamotrack can't be reached to tell either way, it says
  that instead. Before, nothing was said, and every change you then made was refused
  until you reloaded the page.
- **README:** nothing.
- **Docs site:** nothing.

## #341, #343 — a damaged or unusual upload is refused with a reason, and long notes import (PR #347)
- **Release note:** Importing a CSV or archive no longer fails with an unexplained
  server error in a few cases. A kit whose build notes run past about 131,000
  characters now imports again, including from plamotrack's own export, and so does
  a CSV saved with old Mac (CR-only) line endings. A zip damaged in ways the import
  didn't recognise is refused with a message naming the problem. A `manifest.json`
  that can't be unpacked now refuses the import, as other damaged files in the
  archive already did; one that unpacks but can't be read is still only a warning.
- **README:** nothing.
- **Docs site:** nothing.

## #346, #352 — a stray NUL or a damaged BZIP2/LZMA archive is refused with a reason (PR #353)
- **Release note:** A value containing a NUL character, or half of a broken Unicode
  pair, is now refused instead of causing an unexplained server error, from the web
  app, the REST API, MCP tools and CSV imports. The refusal names the field (on
  `create_order` over MCP since #354). An import preview no longer
  approves a row that the import then fails on. A damaged archive is now refused the
  same way whichever compression it uses, and a `manifest.json` holding such a value
  is treated as unreadable: a warning, and the rows still import. A provider's sign-in
  with an unusable identity is refused without using up the setup token, and an
  unusable display name is skipped. A provider whose discovery document names an
  unusable endpoint is reported as unavailable, a fetched MCP client document that
  can't be displayed is treated as an unknown client, and a number too large for JSON
  in a request is refused rather than causing a server error. Two details a script could notice: a NUL in a
  settings value now answers `request.validation` rather than `settings.value_invalid`,
  and a required import cell that can't be read reports one problem rather than also
  saying it is missing.
- **README:** nothing.
- **Docs site:** nothing.

## #366 — a new order or tool opened just after a currency change starts on the new currency (PR #368)
- **Release note:** Right after the reference currency was changed (in Settings, or by
  importing an instance-settings sheet), a New order or Add tool dialog opened before the
  app had re-read the instance's details could start on the old currency and keep it,
  and an order saved from it could record its converted price in the old currency. The
  dialog now waits for the new currency, showing Loading for that moment.
- **README:** nothing.
- **Docs site:** nothing.

## #354 — an MCP `create_order` refusal names the argument to correct (PR #373)
- **Release note:** When `create_order` over MCP was given a value its order schema
  refuses (a currency code that is not three capital letters, an empty `items` list, a
  NUL in `order_number`, `tracking_url` or another text field), the agent got only
  "Invalid request parameters" and could not tell which argument to fix. The tool now
  answers with an error naming the argument and the rule, as REST's 422 names the field,
  and still stores nothing, including a shop named in the same call.
- **README:** nothing.
- **Docs site:** nothing.

## #361 — a line break in a name shows as a space in the editor, and an edit keeps the two words apart (PR #372)
- **Release note:** A name, number or other one-line field that was given a line break
  through the REST API, an MCP tool or a CSV import showed in the web app's editor with
  the two lines run together, and saving after typing in that field stored them joined.
  The editor now shows the break as a space, and saving stores what was on screen. A
  field you never click or tab into keeps its line break. One you click or tab into
  can be saved with the space, even if you typed nothing. Nothing already stored
  changes until it is saved from the editor.
- **README:** nothing.
- **Docs site:** nothing.

## #356 — re-importing your own export no longer rewrites text that ends in a newline (PR #377)
- **Release note:** A text value saved with surrounding whitespace (most often a
  trailing newline left in a notes box, through the web app, the REST API or an MCP
  tool) made a merge import of the instance's own export preview that row as an update,
  and applying it quietly removed the whitespace. Import reads every text cell without
  its surrounding whitespace, and now compares the stored value the same way, so the
  row is unchanged and nothing stored moves. A cell that says something different is
  still an update. A blank cell over a stored value that is only whitespace now leaves
  that value in place, where a merge used to clear it. A Replace everything import
  still recreates every row from its cells, so there the text comes back without the
  whitespace, as before.
- **README:** nothing.
- **Docs site:** nothing.

## #358 — saving an order, kit or shop no longer overwrites what an agent wrote while the dialog was open (PR #378)
- **Release note:** The order, kit and shop dialogs sent every field back on each save,
  so anything an assistant, a script or another tab wrote to the same record while the
  dialog was open (a tracking number added to an order, say) was silently replaced with
  what the dialog had shown when it opened. A save now sends only the fields you
  changed, and leaves the rest as they are stored. Where you and an agent changed the
  same field, your save wins.
  On an order, the shipping cost and the discounts are amounts in the order's
  currency, so each one you change is saved together with the currency you saw, and a
  currency you change is saved with the shipping cost and any discounts on screen. A
  change to one of the two amounts leaves the other as stored. Two cases are not yet
  handled, and both behave as they did before (#382). If something changes the
  order's currency while the dialog is open and you then change only one amount, the
  other amount, as that change stored it, is read in your currency. And if something
  adds a discount while the dialog is open with none on screen, and you then change
  the currency, that discount keeps its figure in your new currency (A$2.00 becomes
  ¥200); after a save whose ship or receive failed, the retry can instead be refused
  because that discount now comes to more than the order. In both cases, check the
  order's discounts after saving.
  An order save that stored its changes but then failed to mark the order shipped or
  received can be corrected and saved again: a field you put back to how it opened is
  now stored that way, a ship date changed after the ship went through is saved as a
  correction, and a field the first try already stored is not sent again unless you
  change it again, so something written to it in between is kept.
- **README:** nothing.
- **Docs site:** nothing.

## #380 — a kit's name or grade can no longer be only spaces (PR #386)
- **Release note:** A kit could be saved with a name or grade of nothing but spaces
  (or tabs, or a line break), through the kit dialog, the REST API, an MCP tool, or an
  order's kit line. Import reads a cell like that as empty, and both are required, so
  the instance's own export would no longer import: the preview stopped with "Name is
  required." on that kit and nothing in the archive could be applied. Every way of
  saving a kit now refuses a name or grade that is only whitespace, saying which one
  is blank, and saves nothing. A name with spaces around real text is saved as typed,
  as before.
  A kit already stored with a blank name or grade is not changed by this release, and
  its export still stops at the preview as above. To fix it, open the kit, give it a
  name or grade, save, and export again (or put the name in the `kits.csv` cell before
  importing). Until then, adding kits to the order line that bought it asks for the
  name or grade too, and so does any save that sends that line's kit details back,
  even unchanged. The web app sends them only when you change them, but a script or
  an assistant may send them with any edit to the line: leave the kit details out of
  such an edit, or fix the kit first (#388). Any other change to the order saves as
  before.
- **README:** nothing.
- **Docs site:** nothing.

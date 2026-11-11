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
  app, the REST API, MCP tools and CSV imports. The refusal names the field, except
  for a few `create_order` arguments over MCP (#354). An import preview no longer
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

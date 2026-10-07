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

## #326 — Home no longer scrolls sideways when a value has nowhere to break (PR #337)
- **Release note:** A grade, scale, kit number, kit name or carrier with no spaces
  no longer makes Home scroll sideways. A Backlog or Recently completed row whose
  details don't fit beside the name puts them under it, with the edit button
  beside both lines. Ordinary rows look as they did.
- **README:** nothing.
- **Docs site:** nothing.

## #268 — the keyboard stays where you pressed (PR #336)
- **Release note:** Pressing a button from the keyboard no longer sends the next
  Tab back to the top of the page. The stock steppers, Export CSV, Save, Create
  token, Revoke and Sign in keep the keyboard while they wait. Where a button
  can't be pressed again, the keyboard moves to the obvious next control: from −
  at zero to +, from a revoked token to the next one, from a finished Save to
  the field before it, and from Create token to Copy.
- **README:** nothing.
- **Docs site:** nothing.

## #331 — Access tokens and Data management show dates and sizes in your saved format (PR #335)
- **Release note:** Settings → Access tokens no longer shows its dates in the
  default format when the token list loads before your saved settings. Data
  management's file size and import counts now follow the saved format too.
- **README:** nothing.
- **Docs site:** nothing.

## #316 — a failure in Settings is said beside the button that failed (PR #334)
- **Release note:** In Settings, an error now appears next to the control that
  caused it. A failed download says so in its own card, rather than at the top of
  Data management, which on a phone was a screen above the starter sheet. A failed
  Save says so beside Save. A failed token revoke is scrolled into view, wherever
  the token is in a long list.
- **README:** nothing.
- **Docs site:** nothing.

## #315 — an import keeps going when you leave Data management, and says how it ended when you come back (PR #332, `48c37b9`)
- **Release note:** Leaving Settings → Data management while an import ran used to
  lose track of it: the import finished on the server, but coming back showed an
  empty Import card, with nothing to say it had run, and the same file could be
  applied again (under Add only, adding its kits a second time). Now, coming back
  while it runs shows it under way, with no file to pick until it ends; coming back
  after shows how it ended, once. Reloading or closing the tab while an import runs
  asks first.
- **README:** nothing.
- **Docs site:** `using/import-export.mdx`, under "Preview before you commit", one
  more paragraph: once you click **Apply import**, the import runs to the end even
  if you go to another page; come back to Data management to see it under way, then
  how it ended. Reloading or closing the tab while it runs asks first, because that
  would lose the outcome.

## #329, #327 — list tables fold when they don't fit, whatever the rows hold (PR #330, `75e0218`)
- **Release note:** From tablet width up, a list's table moves a column under the
  name (or a date under the status) when the whole table doesn't fit the space it
  has. It used to do this at fixed widths, so some unusual but valid rows (long words
  in every field, a fully dated and rated kit, a ten-digit stock count, a large
  cost in some currencies) could still push the row's Edit button out of sight. A
  table now folds only when it has to, and unfolds when the rows that needed it
  are gone. In Safari on an iPad, an Inventory item's count now goes above its − and
  + buttons when the column is short of room, instead of pushing the table wide.
  Settings → Access tokens shows card rows on a phone, as every list there does,
  including on a phone-width iPad mini.
- **README:** nothing.
- **Docs site:** nothing.

## #323 — a long word no longer pushes a list past the screen (PR #328)
- **Release note:** A name, category, manufacturer, grade, scale, note or shop
  address with no space in it — a product code run together, say — used to make a
  list's table wider than the page from tablet width up, pushing the row's Edit
  button out of sight; on a phone, a long grade or scale did the same to a kit's
  card. Such a word now breaks across lines where it has to. Ordinary names lay out
  exactly as before. Inventory's category filter is no longer as wide as its
  longest category. On a tablet, Inventory's Tools and Display tables now fold
  like the other lists: Condition (Tools) and Manufacturer and Notes (Display) move
  under the item's name when the table is short of room, rather than pushing the
  Edit button out of sight. And on a phone, an Inventory card's details wrap
  instead of being cut off with an ellipsis.
- **README:** nothing.
- **Docs site:** nothing.

## #318 — a phone shows every row (PR #319; #321, PR #322)
- **Release note:** On a phone, the list pages (Kits, Orders, Inventory, Retailers)
  now show every row in one long list instead of ten a page; search and the filters
  narrow it. Tablets and desktops still show ten a page. Turning a tablet from the
  phone layout to the wider one opens the list on the page that holds the row you
  were on, so the keyboard stays on it.
- **README:** nothing.
- **Docs site:** the phone page says lists show every row (no pager); any page that
  says "ten rows a page" without qualification gains "on a tablet or desktop". Phone
  screenshots of a list with more than ten rows change shape (no pager); retake the
  ones that show one.

## #304 — a phone can import (PR #314, `39a9661`)
- **Release note:** Settings → Data management on a phone now imports: choose a .zip
  archive or a .csv from your phone's files, preview it, and apply it, with **Merge**
  or **Add only**. That is the way from plamotrack for iPhone to your own server:
  export an archive in the app, import it here. **Replace everything** stays on a
  tablet or a computer, as does the full template pack; the starter sheet is on the
  phone too. On every screen size: an import's error now appears inside the Import
  card, beside the button that caused it, rather than at the top of the page; an
  import that has started says so, with its mode, until it finishes, and its mode
  and file can't be changed meanwhile; and "or browse for one" on the desktop's drop
  zone can be reached with the keyboard.
- **README:** nothing (the phone screenshot in its gallery is Home, not Data
  management).
- **Docs site:** `using/phone-and-tablet.mdx` → "What a phone leaves out": Data
  management on a phone imports, Merge and Add only; Replace everything and the full
  template pack need 768 px; the preview reads per table, and Apply sits in a bar
  above the tab bar. Its `phone-data` screenshots (light and dark) and their alt text
  and caption are retaken (`e2e/screenshots.spec.ts` with `SCREENSHOTS_OUT`): the
  export card and the import under it. `using/import-export.mdx`'s opening paragraph:
  a phone imports too, in those two modes — and, if the page describes where an
  import's errors appear or how to pick a file, that errors appear in the Import card
  and that Browse is keyboard-reachable. If the plamotrack-ios move has a page by
  then, it links here.

## #309 — the database refuses a negative shipping cost or low-stock threshold (PR #313, `4651ce2`)
- **Release note:** Upgrading clears any negative shipping cost or low-stock threshold
  to blank. Only an import made before this release's import range checks (#305) could
  have stored one; the upgrade log says how many it cleared. From then on the database
  refuses a negative in either, as every other way in already did.
- **README:** nothing.
- **Docs site:** the upgrade notes for this release: the one-line clean-up above.

## #305 — an import with an out-of-range value is refused in the preview, not at apply (PR #310, `8ba9c6e`)
- **Release note:** An import holding a rating outside 1–5, or a negative stock level,
  price, cost, shipping cost, low-stock threshold or quantity used, is now refused in
  the preview with the row and column named, the same values the app's own forms
  refuse. Before, most of these passed the preview and then failed the import with a
  server error, and a negative shipping cost or low-stock threshold was stored.
- **README:** nothing.
- **Docs site:** the import page's rules for whole-number columns: ratings are 1–5,
  and quantities, prices, costs and thresholds can't be negative (a quantity used,
  like a line's quantity, starts at 1). `docs/import-export.md` → "How numbers are
  read" owes the same line.

## #300, #301, #299 — a database password with punctuation no longer stops `migrate`; a settings error no longer prints secrets (PR #302, `b7f8a47`)
- **Release note:** A `POSTGRES_PASSWORD` with punctuation in it (`@ / + = # %`, a
  space: what a password generator produces) no longer stops the `migrate` service
  with `invalid interpolation syntax` before the API starts. Neither does a
  `DATABASE_URL` whose password is percent-encoded. Nothing in `.env` needs changing.
  A settings error at startup (an OIDC setting missing, a malformed
  `MCP_OAUTH_SIGNING_KEY`) no longer prints fragments of `.env`'s secrets into the
  `api` and `migrate` logs. It still names the setting to fix. If a log from such
  an error was shared, rotate what it showed: the database password's first
  characters, the end of `MCP_OAUTH_SIGNING_KEY` or `OIDC_CLIENT_SECRET`. For
  source runs, `POSTGRES_HOST` now takes an IPv6 address (`::1`, `[::1]`,
  `fe80::1%eth0`), and a host with a port in it (`db:5433`) is refused at start,
  naming the setting; the port is `POSTGRES_PORT`. The bundled stack pins the host
  to `db`, so that part changes nothing there.
- **README:** nothing. Its troubleshooting list already sends a failed `migrate` to
  `docker compose logs migrate`.
- **Docs site:** the configuration reference's `POSTGRES_PASSWORD` entry: drop any
  advice to keep the password to letters and digits, if there is any. Its
  `POSTGRES_HOST` entry, if it has one: an IPv6 address is written bare or bracketed.
  Not checked from this repo.

## #247 — Home and the Kits page sort by the dates they show (PR #298, `6000d96`)
- **Release note:** Home's On the bench now lists kits by build start date, and
  Recently completed by completion date — the dates the cards show — instead of by
  when each kit last changed status. A build with no date shows "—" and sits after
  the dated ones: completed kits imported from a CSV without a completion date move to
  the end of the strip until you give them one in the kit dialog. The Kits page opens
  on *Newest added* and offers *Oldest added*, *Recently started*, *Recently
  completed* and *Name A–Z*. "Newest first" is gone: it sorted by the last status
  change, which the page never showed. A list page link carrying a filter or sort it
  no longer knows opens with the default, and the address bar drops it. For agents,
  `list_kits` takes `sort` `newest`, `started` and `completed` as well.
- **README:** the Home paragraph ("A start page that admits you have a backlog") and
  the MCP table's `list_kits` row. The new wording is in `6000d96`
  (`git show 6000d96 -- README.md`).
- **Docs site:** any page describing Home's strips or the Kits page's sort options,
  and any MCP page listing `list_kits`'s sorts. Not checked from this repo; the
  plamotrack-docs repository was not attached to the session that wrote this.

## #289 — `create_order` takes the shop's id (PR #297, `e72a7cc`)
- **Release note:** MCP `create_order` names its shop with either `retailer_id` (an id
  from `list_retailers`) or `retailer` (a name, matched case-insensitively or created).
  An id passed as `retailer` is now refused. Before, it quietly created a new retailer
  named after the id.
- **README:** the MCP table's `create_order` row. The new wording is in `e72a7cc`
  (`git show e72a7cc -- README.md`).
- **Docs site:** any MCP page describing `create_order` or how an agent records a
  purchase. Not checked from this repo.

## #294 — MCP OAuth links with providers that implement RFC 8707 (PR #295, `ee458f4`)
- **Release note:** In OIDC mode the MCP OAuth proxy no longer forwards the client's
  `resource` to the provider, and always asks it for `openid`. A provider that
  enforces RFC 8707, Pocket ID among them, now links an assistant with no extra setup.
  Before, it refused with `invalid_request` unless the instance's `/mcp` was
  registered with it as an API. The browser login is unchanged. If you linked an
  assistant through Pocket ID with that registration, delete it after upgrading; the
  assistant then asks you to reconnect once — Claude.ai did so even for a connector
  that had been removed and added again.
- **README:** nothing.
- **Docs site:** a **Pocket ID page** — an optional supported provider from this
  release (#280, decided 2026-09-25). The recipe is in `.agents/spikes/280/findings.md`:
  §5 (its own hostname with HTTPS, a persistent volume, `ENCRYPTION_KEY` kept with the
  backups; one client carrying both callbacks, and a UI-created client is
  group-restricted by default; a login code in its access log), §4 (the backup set and
  lost-passkey recovery by a login code, no rebind), §3 (revocation is local only),
  and §8. No API-registration step; the reconnect line above for anyone who used it.
  Also the OIDC page's provider notes, if any mention `resource`.

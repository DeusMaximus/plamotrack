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
  registered with it as an API. The browser login is unchanged.
- **README:** nothing.
- **Docs site:** only if the docs cover Pocket ID by then (#280's open decision). Then
  drop the API-registration step (#280 findings §2a). The OIDC page's provider notes,
  if any mention `resource`.

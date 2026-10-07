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

Nothing is unreleased: v0.6.0-alpha (7 October 2026) shipped every entry that was here.

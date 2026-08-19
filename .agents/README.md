# .agents/ — process material for coding agents

Not user documentation — that is `docs/`. This directory holds what agents (and the
humans working alongside them) need *between* sessions, kept out of the always-loaded
`AGENTS.md` so that it costs context only when it is actually read.

- `handoff/YYYY-MM.md` — archived `HANDOFF.md` entries, verbatim, newest first, one
  file per month. `HANDOFF.md` in the repo root keeps only the five most recent;
  its header carries the rotation rule and the grep recipe. Never read one whole.
- `lessons.md` — the case histories behind the rules in `AGENTS.md`: what a defect
  cost, what a test missed and why. Append-only, stable headings, linked from the
  rules.
- `testing-and-review.md` — procedure, edited in place: how to write a regression
  test here, the fixtures, the mutation harness, e2e hygiene, the release gate,
  which reviewer for what, and how to answer a review.

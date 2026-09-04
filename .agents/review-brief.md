# Briefing an external reviewer — the envelope

A review round here is a prompt pasted into Cursor or Codex by the owner, and the
prompt has been rewritten from memory every time. The parts that recur are the parts
that have cost time when forgotten: `--body-file` not `--body`, the phrase *mutation
testing*, a fresh chat per Cursor round, a worktree rather than `git checkout --` for
the negative control, the attribution line. This file holds them once. The agent
opening the PR fills the `‹slots›` and **prints the finished brief directly in the
chat, in full, inside a fenced block the owner can copy** — a four-backtick fence,
because the brief itself contains three-backtick blocks. Never hand over only a path
to a file in a temp directory: the owner's next step is paste, not `cat` (owner's
call, 2026-08-24). Saving a scratchpad copy alongside is fine as a backup for later
rounds; it is not the deliverable. The reasons behind the fixed parts are in
`testing-and-review.md` → "External review" and `lessons.md` → "Review"; this file
is the shape, not the why.

**The PR body is the payload; the brief is the envelope.** The brief points at
sections of the PR body by heading rather than repeating them, so the PR thread stays
the single record a second round reads. That only works if the PR body has the
sections. The ones the template below assumes — the shape #108 and #109 settled on:

| PR-body section | Holds |
| --- | --- |
| opening line | the attribution (`AGENTS.md` → Git conventions) and the head sha |
| **What** | the change, by file; which rule it serves; what it deliberately does not touch |
| **Deliberate calls a reviewer may disagree with** | numbered, each with the reason — the list the reviewer judges |
| **Tests** | the new file and count; value axis, state axis, surfaces, controls |
| negative control (in Tests) | *N red / M green on unfixed `main`*, what the greens are, sampled reds on the intended assertion |
| mutation pass (in Tests) | a table — mutant → killed by — and, when the tracked harness doesn't carry the cases, the tuples in a `<details>` block |
| closing line | suite counts, lint, migration yes/no, sign-off |

---

## The template

Everything outside `‹…›` is meant to be sent as written. Trim a paragraph only if it
genuinely does not apply (a docs-only PR has no mutation pass); do not paraphrase the
fixed sentences — several of them are the exact wording that worked.

````markdown
Review PR #‹N› on DeusMaximus/plamotrack — branch `‹branch›`, head `‹sha›`, against
`main` at `‹main-sha›`. It closes ‹#issue(s)›. Read the issue, the PR body,
`AGENTS.md` (the architecture rules — ‹the numbered rules this touches› are the ones
in play) and `.agents/testing-and-review.md` ("Writing a regression test", "External
review → Responding to a review") before the diff.

**Context, one paragraph.** plamotrack is a single-owner, self-hosted model-kit
collection tracker, pre-adoption alpha, owner login + personal access tokens but no
tested TLS path yet (milestone 6 in progress), on a
trusted network. ‹Two or three sentences: the defect or feature in the issue's terms,
and what this branch does about it — file names, not adjectives.› No migration /
‹one migration, additive›. Inventory counts and purchase records, not access control.

**Environment is ready.** Repo at `/Users/tlgja/Code/plamotrack`; backend deps
installed (`cd backend && uv sync` already run); the dev Postgres is up
(`docker compose -f docker-compose.yml -f docker-compose.dev.yml ps db`). Run the
suite from `backend/` with `uv run pytest`; **one pytest session at a time** — two
overlapping runs deadlock on `TRUNCATE`. ‹Frontend: "untouched; don't start Vite" /
"`npm install` done; `npm run build`, `npm test`, e2e needs chromium installed".›

**Check the test claim first — it is the claim most worth checking, and re-measure
the numbers rather than reading them: the author's counts are the first thing to
get wrong.** The PR body's *Tests* section says ‹N red / M green› on unfixed `main`,
and names what the greens are. Verify that in a **git worktree** of `main`
(`git worktree add /private/tmp/plamotrack-‹N›-main main`), copying the new test
file(s) in — not `git checkout <branch> -- <path>`, which has discarded work on this
repo before. Check *which* tests go red and *why*: each should fail on the assertion
that names the defect ‹e.g. `201 == 409`, `DID NOT RAISE ToolError`›, not on setup
or an unrelated 500. Then all green at `‹sha›`. Remove the worktree when done.

**Then mutation testing.** The PR body has a table of ‹K› single-site mutants it says
were all killed — count the rows, and check an anchor or two really matches once‹, and the exact tuples (anchor → replacement → `-k` expression) in a
collapsed block›. Re-run the ones you think are load-bearing — at minimum ‹two or
three labels, and why those›. Make sure the tree is clean before you mutate and
restore from a backup copy afterwards, so a failed restore shows in `git status`.
‹If the tracked `backend/mutation_test.py` carries the cases: "run it with `-k ‹label
prefix›`". If not, say why not — e.g. "mid-rewrite on #86; deliberate."›

**The PR body's "Deliberate calls" — judge each.** ‹Restate them in one line apiece,
numbered as on the PR, so the reviewer answers in the same numbering.› Say if you'd
overrule any.

**Where I'd push, because these are assumptions rather than proofs:**

- ‹Each bullet: one assumption, what would falsify it, where to look. Three to six.
  See "Filling this section" below.›

**Severity by real exposure, not shape**: pre-adoption alpha on a trusted network is
a legitimate input to a P-level.

**Output.** A verdict (GO / NO-GO), then findings numbered with P1–P3, each with the
reproduction at `‹sha›` and the remedy — say both halves if the defect is right and
the obvious remedy is wrong. Open with the attribution line and close with the
sign-off, as the previous rounds did:

```
‹reviewer attribution line — see the footer for your reviewer›
…
‹reviewer sign-off›
```

Post it with `gh pr comment ‹N› --body-file <path>` — `--body-file`, not `--body`,
because a shell string mangles backticks and `$`. Write the file first, then post
once. The PR thread is the session memory for the next round, so don't leave
findings only in this chat.
````

---

## Reviewer footers

Pick one; it supplies the two `‹reviewer …›` slots and adds its own last paragraph.

The reviewer names itself and its version — the lines below are what previous rounds
wrote, given so the slots in the template read as one house style.

**GLM 5.3 Flash (Zhipu AI, via T3 Code on OpenRouter).** The default reviewer —
any size (1M context); see the roster in `testing-and-review.md` for its measured
traits and the remedies caveat.

```
**GLM 5.3 Flash (Zhipu AI / T3 Code) — review of PR #‹N›, at head `‹sha›`.**
— **GLM 5.3 Flash (Zhipu AI)**, via T3 Code
```

Add to the brief:

> This is one round in a fresh chat session; do not start a second review in this
> session — a truncated review that still emits a verdict is the worst outcome. If
> you cannot hold the whole diff and the PR body in context at once, say so
> explicitly in your verdict rather than reviewing the part you read as if it were
> the whole. If the PR thread already holds a previous round, read it: it is the
> record, and your findings should be numbered after it. If the checkout changes
> under you mid-round, re-run in a detached worktree at the reviewed head and say
> so (the #173 round's precedent).

**Codex (GPT 5.6 Sol).** Any size, or multi-round. Capacity stopped being the
constraint with the 2026-08-28 subscription bump — no meter check needed for a
routine round.

```
**Codex (OpenAI, GPT 5.6 Sol) — independent review of PR #‹N›, replayed at head `‹sha›`.**
— **Codex (OpenAI, GPT 5.6 Sol)**
```

(*independent re-review* / *third independent review* on later rounds.) Add:

> Replay, don't read: for each finding, a focused reproduction at the head, and
> which final-state assertion it fails on. If rounds keep landing in the same
> function, say so — that is a signal about the invariant, not the patch.

**Claude Code (Opus / Fable).** An option when Cursor and Codex are both spoken for,
with one caveat to write into the brief: most PRs here are authored by a Claude
model, and a reviewer from the author's own family shares its blind spots. Say
which model wrote the branch, and ask for a different one where the harness offers
it. Same shape as the Codex paragraph; attribution per `AGENTS.md`:

```
**Claude (Anthropic) — independent review of PR #‹N›, at head `‹sha›`.**
— **Claude ‹Opus 5 / Fable 5› (Anthropic)**, via Claude Code
```

---

## Filling "Where I'd push"

The one section a template cannot write, and the one that has found the most. Answer
these about the branch; each answer that is "I reasoned, I did not prove" is a bullet:

- **Which rule** (`AGENTS.md` number or `§n`) does the change serve, and **which
  paths** did the sweep cover, exclude, and why? Name the exclusions — the reviewer
  checking the sweep is the cheapest second pair of eyes on it.
- **What does the fix assume about its neighbours** — the importer, the other
  writers, a lock already held, an ordering of checks? Where two runtimes or two
  normalisations are supposed to agree, say in which direction you believe any
  disagreement falls, and ask for the counter-example.
- **What would a client notice changed** — a status code, a stored value, a message —
  that the release notes will have to say?
- **Which test is least deterministic** (a race, a timing pin, a repeat count) and
  what is the evidence it is enough?
- **What did you decide rather than derive** — and would you mind being overruled?
  (Those usually belong in the PR body's "Deliberate calls"; point at them here only
  if you want a second opinion specifically.)

Three to six bullets. More than that and the reviewer reads it as a checklist to tick
rather than places to dig.

First use: PR #109, 2026-08-19. The round found both P3s inside the "where I'd push"
list — the direction of a normalisation mismatch, and a race that was repeated
rather than pinned — and two author's-count errors in the PR body. The template is
what that brief looked like with the per-PR parts taken out.

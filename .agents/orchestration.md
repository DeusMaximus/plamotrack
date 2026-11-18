# Orchestrating

Read this when you are the **orchestrator**: the session that hands issues to worker
sessions, checks what comes back, and keeps `HANDOFF.md` current. A worker needs only
`AGENTS.md`, `HANDOFF.md`, and its issue.

The orchestrator writes briefs and checks results. Application code is written by
workers. **The goal is a PR the owner can sign off**: green, reviewed at its current
head, every finding answered, every claim either re-measured by you or named as the
worker's alone.

## The loop

Run these in order. Each step ends when its last line is true.

1. **Pick.** Read the newest `HANDOFF.md` entry and the open issues: the earliest
   unfinished milestone first, then the unmilestoned ones. An issue is **ready** when it
   has a readiness comment (step 2), every issue in its "Depends on" line is closed, and
   it does not carry the `owner` label. Done when you can name the ready issues and the
   ones worth making ready.
2. **Triage** each issue you want to start that is not ready. Most issues here are
   defect reports filed from a review round, and say what is wrong but not when the
   work is finished. Draft a readiness comment for each (shape below) and put the wave
   to the owner. Post the comments once the owner agrees. Done when every issue in the
   wave is ready.
3. **Decide what runs together** by the lane rules below. Done when each issue has a
   lane, or waits for one.
4. **Launch.** One standalone T3 Code thread per issue, on the implementer seat, in its
   own worktree cut from the base branch, on branch `<issue>-<slug>`, with the worker
   brief below. The base is `origin/main`, or the integration branch when the milestone
   lands through one (`AGENTS.md` → Git conventions). Done when the thread reports a run
   in progress.
5. **Wait** for the worker's final message. The worker answers its own review findings;
   the PR is its work until it hands back. Watch the PR once it opens: you are woken
   when its checks or reviews change. A wake is not a hand-back, so read the worker's
   last message each time, and use the wait to read the diff. Done when the final
   message has the PR URL, head sha, review states, and a hand-off entry.
6. **Review.** A PR whose issue carries `briefed-review` gets a briefed round (below).
   Add the label yourself, and say so in your report, when the work turns out bigger
   than the issue looked: the diff reaches a shared mechanism, a second writer, or a
   migration, or an automatic review raises a P1 or P2. Done when the PR has the review
   it owes at its current head.
7. **Verify** with the checklist below. Done when every line is ticked or reported as
   failed.
8. **Report to the owner:** ready or not, which claims you re-measured and which are
   the worker's alone, and each follow-up worth an issue. Done when the owner has what
   they need to sign off.
9. **Close out** once the owner signs off: merge with `gh pr merge --squash --auto
   --match-head-commit <sha>`, check the state of every issue the PR names, drop the
   lane's databases, remove its worktree, and commit the hand-off entry (rule below). Done when the base branch has the merge, `main` has the
   entry, and the lane is free.

## A ready issue

The readiness comment is what a worker builds to. It opens with the attribution line
(`AGENTS.md` → Git conventions) and holds:

```markdown
**Depends on:** ‹#N, #M / nothing›
**Rule:** ‹the numbered `AGENTS.md` rule or design `§n` the work falls under, or "none: a one-off"›
**Review:** ‹automatic reviews / automatic reviews plus a briefed round›

## Scope
- ‹What changes, by file or surface. For a defect under a rule: the paths the class sweep covers.›

## Acceptance
- [ ] ‹One checkable line each. For a defect: the regression test that is red on the base and green on the branch.›
- [ ] ‹A line only the owner can tick (a real device, the deployed instance) says so.›
```

- An issue that already has these parts (the M6.7 issues do) needs only the lines it
  lacks.
- Set `briefed-review` at triage for work on a shared mechanism everything flows
  through: the write gate, order dispatch and stock, money, the importer's invariants
  and `spec.py`, a migration, authentication, tokens, OAuth, ingress.
- An issue is `owner` when it needs a decision, a real account or device, the test
  host, a release, or the docs site.

## Lanes

**Two workers at once** (the owner's call, 2026-11-18; raise it only on the owner's
word). Each worker is a lane with its own checkout, test database and ports:
`.agents/testing-and-review.md` → "More than one session at a time" has the setup, and
the brief gives the worker its `N` and `LANE`. Lanes 1 and 2 are the workers; a
reviewer takes a lane number from 3 up. The main checkout, yours, keeps the defaults.

Two issues share a wave when all of these hold:

- Their Scope sections name different code files.
- At most one of them adds an Alembic migration. Two revisions cut from one head leave
  two heads.
- Neither depends on the other.

Files most PRs append to may be edited by both: `AGENTS.md`, `.agents/next-release.md`,
`.agents/lessons.md`, `docs/design.md`, `backend/mutation_test.py`. Tell each worker
which sections or cases the other owns. The PR that merges second takes the base in
with a merge commit, and its suites are run again on the result.

## Roster

The owner's working experience, as of 2026-11-18. Edit in place when a seat changes or
a model surprises you in either direction. The measured history of each reviewer is in
`.agents/testing-and-review.md` → "Which reviewer".

| Seat | Model | Use for |
| --- | --- | --- |
| Orchestrator | Claude Fable 5.2, high | This loop, triage, and questions about the shape of the work |
| Implementer | Claude Opus 5.5, high | Every issue, the mechanical ones included. Sonnet has no seat in this repo (the owner's call, from an earlier Sonnet's work here) |
| Briefed reviewer | GPT-6.1 Sol through Codex, high | Every briefed round. Quota is ample: when unsure whether a PR owes a round, run one. It keeps the seat until the owner has tried GPT-6.2 Sol and says to change it |
| Second opinion | GLM 5.3 on Mistral Vibe, high | A narrow should-this-merge read when a NO-GO is in question. Mistral Large 4 finds as much, but re-rate its P-levels |
| Manual fallback | The owner, in the Codex app | Work a model here has refused. No session here can start it. See "When a model refuses" |

Implementers are Claude models and the reviewers are not, so every PR gets a read from
outside the author's model family. Keep that true when a seat changes.

## The worker brief

A worker starts with no context from you. The brief carries what `AGENTS.md`,
`HANDOFF.md`, and the issue do not. Keep it to these parts, in this order:

```markdown
Implement GitHub issue #‹N› in this repository: "‹title›". Read the issue and its comments first (`gh issue view ‹N› --comments`); the Scope and Acceptance lists in its readiness comment are the definition of done.

Before you start, read `AGENTS.md` and the newest entry in `HANDOFF.md`. ‹For a defect: "Then `.agents/testing-and-review.md` → 'Writing a regression test'."›

What is already known, so you do not have to rediscover it:
- You are in a fresh git worktree cut from `‹base›` (`‹sha›`), on branch `‹N›-‹slug›`. The main checkout is `‹absolute path›`. You are lane ‹L›: set up as `.agents/testing-and-review.md` → "More than one session at a time" says, with `N=‹N›` and `LANE=‹L›`, before you run any suite or server.
- ‹Each other issue in flight, and the files, document sections or mutation cases it owns. "No other issue is in flight" when that is so.›
- ‹Facts this session has measured that bear on the issue: a count, a failing command, a decision taken since the issue was written.›

Scope: only what issue #‹N› lists. ‹Name the neighbouring issue that owns the nearest out-of-scope work.›

Rules beyond `AGENTS.md`:
- The repository is public. Commits and the PR carry no person's name, real domain, home-network detail, or local path containing a username.
- Open one PR against `‹base›` that closes #‹N›, its body in the shape `.agents/review-brief.md` gives. It owes ‹the automatic reviews only / the automatic reviews and a briefed round, which the orchestrator starts and briefs: write no review brief›.
- Wait for CI and for the Codex connector's review. Answer every finding posted by then, Greptile's included, as `.agents/testing-and-review.md` → "Responding to a review" says. After a fix commit, comment `@codex review` on the PR.
- The owner merges. List any issue worth filing in your final message; file none.
- Leave `HANDOFF.md` alone on your branch. End your final message with your hand-off entry, written to its template.
- If a safety filter or a refusal stops you on a step, stop there. Push what you have, and report the step, the message you got word for word, and what is left on the acceptance list.

Finish with: the PR URL, its head sha, the state of CI, the commit each automatic review covered, each acceptance line you could not verify and why, the issues you propose, then the hand-off entry.
```

Give facts, not instructions on how to do the work. A brief that needs more than the
"already known" list to be usable means the issue is underspecified: fix the readiness
comment.

When an acceptance line can only be shown by running something CI does not (the
from-empty e2e run, the packaged stack, a restore), say so in the "already known" list
and ask for the commands and output in the PR body.

## Verifying a result

A worker's report is a claim. Before telling the owner a PR is ready:

- [ ] CI's three checks are green at the head sha the worker named, and that sha is
      still the head.
- [ ] Every automatic finding has a fix or a reply on its thread, each reply with its
      attribution line and sign-off.
- [ ] The Codex connector's review covers the current head (its summary names the
      commit; `@codex review` asks again). Greptile's first pass is a bonus and is not
      asked for again.
- [ ] Each acceptance line maps to evidence in the PR body, and the body has its
      sections: What, Deliberate calls, Tests, Coverage record.
- [ ] **One claim CI does not cover is re-measured by you.** Pick the one the
      acceptance list leans on most: the negative control (the new tests on the base,
      in a worktree), a mutant from the table, the from-empty e2e run.
- [ ] For a defect under a rule: the PR names the rule and the paths its sweep covered,
      and lists the siblings it found.
- [ ] When the base has moved since the branch was cut, the suites are run on the PR
      merged with it, and `uv run alembic heads` prints one head.
- [ ] The diff stays inside the issue's Scope. Anything extra is reverted or listed
      under the PR's Deliberate calls.
- [ ] A user-visible change has its `.agents/next-release.md` entry, the entry matches
      the diff, and the README's user-facing parts are untouched.
- [ ] The diff, the PR body and every comment carry no personal name, real domain,
      home-network detail, or local path.
- [ ] Counts and procedural claims in the hand-off entry are checked against the repo.
- [ ] For `briefed-review`: the verdict is GO at the current head.

Tell the owner which lines you ticked by running something and which by reading.

## Briefed rounds

`.agents/testing-and-review.md` → "External review" is the procedure: the brief
template, starting the round with `delegate_task`, answering it. What the loop adds:

1. Start the round as soon as CI is green and the first automatic pass is answered. It
   does not need the worker's final message.
2. A P1 or P2 goes back to the worker's thread to fix. A fix is a new head: comment
   `@codex review`, and run the next round, with a new brief, on that head.
3. When the head moves after a GO for another reason (an automatic finding fixed, the
   base merged in), run a short round briefed on the new commits only. When they carry
   no hand-written code (a merge whose tree equals a mechanical one outside the
   conflicted documents), check that yourself, and say in your report that you did and
   how.
4. P3s on a GO become follow-up issues you propose to the owner. Folding one into the
   PR moves the head, so the round repeats.
5. **Change tracks when the rounds loop.** Stop and go to the owner when a PR gets a
   second NO-GO, or when a round's finding lands in the function or invariant the last
   round's fix touched. More patching there buys another round. Bring the options with
   your recommendation: ship the PR as scoped with its contract stated honestly and
   file the structural fix; make the structural fix here when it is small and in the
   PR's own files; or take the second-opinion seat's read on whether it should merge.

## When a model refuses

Some of this repo's work looks like offensive tooling to a safety filter although it
is the owner's own instance: OAuth and token handling, ingress and rate-limit tests
that send hostile input, the security scan's follow-ups. A worker, a reviewer, or you
may be refused or cut off partway through.

A refusal is a hand-over to the owner, who continues by hand in the Codex app.

1. Leave the branch as it is, with everything committed and pushed.
2. Write `.dev/<issue>/manual-handover.md` in the main checkout. The session that picks
   it up has no context, so the file stands alone:
   - the repository, the branch, and the issue number, with "read `AGENTS.md` and the
     issue first";
   - what is done, by commit;
   - the step that was refused, and the refusal message word for word;
   - what is left on the issue's acceptance list;
   - how to finish: push to the same branch, and name the model in the PR body's
     opening line.
3. Tell the owner the path and that the issue is waiting on them. Carry on with other
   ready issues.
4. When the branch moves again, verify it as you would any worker's result. The part
   written by the fallback model is from the briefed reviewer's own family, so its
   briefed round goes to a Claude model that did not write the PR.

Send the same task to the same seat again first only when the refusal is plainly about
wording in your brief. One retry; then hand over.

## Hand-off entries

- A worker in a worktree does not commit to `main`. It ends its final message with its
  entry, and you commit it.
- **One entry per issue, committed after the merge.** Take the worker's entry as
  written and add a `Merged:` line under **Done** with the merge commit, how each
  review ended, and any follow-up issues filed. Commit it before the merge only when
  the PR will sit unmerged past the end of your session.
- Then apply the rotation rule in `HANDOFF.md`'s header. Count the entries yourself.
- **End your own session with an orchestrator entry on top.** It holds live state for
  the next orchestrator: what is merged, what is in flight and in which lane, which
  issues are ready, what waits on the owner, and the wave you would start next.

## Stop for the owner

Ask before any of these. Everything else in the loop is yours.

- Merging a PR.
- Filing or closing an issue, posting a wave's readiness comments, or removing a label.
- Starting an issue labelled `owner`, or the part of an issue that needs a real
  account, a real device, the test host, or the deployed instance.
- Anything `AGENTS.md` → Git conventions calls outward-facing: a tag, a release, a
  registry write, a repository setting. The docs site is the same.
- A change that reverses a call `AGENTS.md` or `docs/design.md` records as the owner's.
- A review loop, as "Briefed rounds" step 5 describes.
- A refusal or safety block on legitimate work.
- Changing a seat in the roster, or the number of lanes.

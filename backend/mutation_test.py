# ruff: noqa: E501 - the anchors below are literal source text; wrapping breaks them
"""Hand-rolled mutation testing for the #82/#88 cell-semantics rules.

Standard mutation testing, in the mutmut / cosmic-ray sense, written by hand
because the mutants worth trying here are semantic rather than syntactic. Each
case introduces one deliberate fault, runs the tests that should detect it, and
restores the file. A mutant the suite **kills** (tests go red) is a rule the tests
genuinely cover; a mutant that **survives** (tests stay green) is the finding.

    uv run python mutation_test.py           # every case
    uv run python mutation_test.py -k 2b     # cases whose label contains "2b"

A surviving mutant means one of two things, and both are worth knowing:

* the condition is **dead** — some other condition already decides the outcome, so
  it can never change behaviour and no test could ever have covered it;
* the condition is live but **untested** — the case that would exercise it is
  missing from the suite.

**Adding cases is the point.** Append to CASES: (label, file, exact source to
replace, replacement, pytest -k expression that must fail). An anchor matching zero
or two places is reported as a failure rather than skipped quietly — a mutant that
never got applied is not a mutant that was killed.

Check that a mutant you add actually reproduces the defect you have in mind before
trusting its result: one that changes a line without changing behaviour reads green
and proves nothing.

The domain, for anyone reading this cold: plamotrack is a single-user, self-hosted
model-kit collection tracker. The rules being mutated decide what a CSV cell means
when it says nothing usable — inventory counts and purchase records, not access
control. The application has no authentication at all yet (milestone 6).

Restores from a backup in a `finally`, and refuses to start unless the tree is
clean, so an interrupted run is obvious in `git status`.
"""

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
IMP = ROOT / "app/services/portability/importing.py"

# (label, file, old, new, pytest -k expression that MUST go red)
CASES = [
    (
        "1. a blank cell writes NULL into a NOT NULL column again",
        IMP,
        "        self._keep_stored_where_unstatable(spec, row)",
        "        pass  # mutated",
        "keeps_the_stored_value",
    ),
    (
        "1a. nullability is read as always-nullable",
        IMP,
        "    return column is None or column.nullable",
        "    return True",
        "keeps_the_stored_value",
    ),
    (
        "1b. the blank is kept but still planned as a change",
        IMP,
        "            row.present.discard(column.name)",
        "            pass",
        "keeps_the_stored_value",
    ),
    (
        "1c. classification runs before references and money resolve",
        IMP,
        "                self._resolve_all_refs(spec, row, replace_all)\n                self._apply_money_alternates(spec, row)",
        "                pass",
        "mirror_still_wins",
    ),
    (
        "2. an unfillable create is not refused",
        IMP,
        "                self._refuse_unfillable_creates(spec, row)",
        "                pass  # mutated",
        "missing_a_required_value_is_named",
    ),
    (
        "2a. a schema default no longer counts as fillable",
        IMP,
        "    return column is not None and (column.default is not None or column.server_default is not None)",
        "    return False",
        "takes_the_schema_default or missing_a_required_value_is_named",
    ),
    (
        "3. a dangling optional reference is silent again",
        IMP,
        "            elif dangling is not None and _column_is_nullable(spec, column.name):",
        "            elif False:",
        "dangling_optional_reference_is_reported",
    ),
    (
        "3a. a required dangling reference degrades to a message",
        IMP,
        "            elif column.required:",
        "            elif False:",
        "required_column_still_blocks",
    ),
    (
        "3b. the dangling message ignores whether the column can hold null",
        IMP,
        "            elif dangling is not None and _column_is_nullable(spec, column.name):",
        "            elif dangling is not None:",
        "the_row_keeps_anyway_says_only_that or refused_create_carries_no_message",
    ),
    (
        "4. a refused create keeps the id it minted",
        IMP,
        "            if row.new_id is not None:\n                self.created_ids[spec.key].discard(row.new_id)",
        "            pass",
        "takes_back_the_id_it_minted",
    ),
    (
        "5. a kit line drops its catalog reference silently",
        IMP,
        "                if discarded is not None:",
        "                if False:",
        "ignores_a_catalog_reference",
    ),
    (
        "5a. the kit branch reports a dangling result as well",
        IMP,
        "                return None\n\n        dangling: tuple[str, uuid.UUID] | None = None",
        '                return ("catalog", discarded) if discarded else None\n\n        dangling: tuple[str, uuid.UUID] | None = None',
        "ignores_a_catalog_reference",
    ),
    (
        "5b. a blank cell is reported as a discarded reference",
        IMP,
        "                if discarded is not None:",
        "                if True:",
        "no_catalog_reference_says_nothing",
    ),
]


def run(expr: str) -> tuple[int, str]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_cell_semantics.py",
            "tests/test_portability.py",
            "-q",
            "-k",
            expr,
            "-x",
            "--no-header",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip().splitlines()[-1] if proc.stdout else ""


def tree_is_clean() -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "app", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return not proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", dest="filter", default="", help="substring of the case label")
    args = parser.parse_args()

    if not tree_is_clean():
        print("app/ or tests/ has uncommitted changes — commit or stash first, so that a")
        print("restore that doesn't happen is visible rather than mixed in with your edits.")
        return 2

    failures = []
    selected = [case for case in CASES if args.filter in case[0]]
    if not selected:
        print(f"no case label contains {args.filter!r}")
        return 2

    for label, path, old, new, expr in selected:
        original = path.read_text()
        if original.count(old) != 1:
            print(f"SKIP  {label}: anchor matched {original.count(old)} times")
            failures.append(label)
            continue
        backup = tempfile.mktemp()
        shutil.copy(path, backup)
        try:
            path.write_text(original.replace(old, new))
            code, summary = run(expr)
        finally:
            shutil.copy(backup, path)
        verdict = "RED  " if code != 0 else "GREEN"
        print(f"{verdict} {label}\n        -> {summary}")
        if code == 0:
            failures.append(label)

    if not tree_is_clean():
        print("\nWARNING: the tree is dirty after the run — a restore failed. `git diff`.")
        return 2
    if failures:
        print("\nSURVIVING MUTANTS (the finding):", *failures, sep="\n  - ")
        return 1
    print(f"\nall {len(selected)} mutants were killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

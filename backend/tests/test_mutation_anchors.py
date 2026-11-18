"""Every mutation case's anchor still names one place in its file (#359).

`mutation_test.py` applies each mutant by replacing an exact source string, and a
string that matches zero places, or two, is a mutant that never ran. The harness
reports one as a failure, but only for the cases a run selects, and a full run
takes about half an hour and is not part of CI: twelve anchors went stale on `main`
that way, unnoticed, after the code they named moved. This reads the case table
and counts each anchor, so the change that moves an anchored line fails here, in
the PR that caused it. It applies no mutant and runs none of the named tests.
"""

from pathlib import Path

import mutation_test

BACKEND = Path(mutation_test.__file__).resolve().parent


def test_every_mutation_anchor_matches_exactly_once():
    # A table that failed to load would pass vacuously: an empty loop asserts nothing.
    assert len(mutation_test.CASES) > 0
    texts: dict[Path, str] = {}
    stale = []
    for label, path, anchor, _replacement, _expr in mutation_test.CASES:
        if path not in texts:
            texts[path] = path.read_text()
        count = texts[path].count(anchor)
        if count != 1:
            where = path.resolve().relative_to(BACKEND.parent)
            stale.append(f"{label} — {where}: anchor matched {count} times")
    assert not stale, (
        "these mutation cases no longer apply; re-anchor each on the code its rule "
        "moved to, or retire it if the rule is gone (.agents/testing-and-review.md → "
        "Mutation testing):\n" + "\n".join(stale)
    )

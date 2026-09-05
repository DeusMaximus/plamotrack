# ruff: noqa: E501 - the anchors below are literal source text; wrapping breaks them
"""Hand-rolled mutation testing for the import validation rules.

Standard mutation testing, in the mutmut / cosmic-ray sense, written by hand
because the mutants worth trying here are semantic rather than syntactic. Each
case first runs its selection UNMUTATED and requires it to pass (a broken
environment — a test DB migrated past this tree's alembic head — otherwise
reads as a wall of kills), then introduces one deliberate fault, runs the tests
that should detect it, and restores the file. A **kill** is a test FAILURE:
pytest exit 1, "failed" in the summary, no errors — a mutant that stops the
file importing "fails" every test without any assertion running, which proves
a syntax accident, not coverage (both rules from the #117 review, P3-1). A
mutant that **survives** (tests stay green) is the finding; SICK, NONE and
ERROR verdicts are harness findings, not kills.

Tracked with the branch, on purpose. It is not part of the shipped application and
nothing imports it — but it is the only thing on #44 that has ever found a guard
which could not change an outcome, and keeping it untracked cost a dozen cases to
one careless edit with no history to recover them from.

Its anchors are exact source strings, so it rots the moment the code it points at
moves. That is a feature at review time — a stale anchor is reported as a failure
rather than skipped, which caught three of them after a refactor — and a
maintenance cost afterwards. Whoever merges #44 decides whether it earns its keep
on `main` or comes out with the branch.

    uv run python mutation_test.py           # every case
    uv run python mutation_test.py -k inv-4b # cases whose label contains "inv-4b"

A surviving mutant means one of two things, and both are worth knowing:

* the condition is **dead** — some other condition already decides the outcome,
  so it can never change behaviour and no test could ever have covered it;
* the condition is live but **untested** — the case that would exercise it is
  missing from the suite.

Three of this branch's five known coverage gaps were the first kind. All three
looked correct on the page, which is why reading the diff would have ratified
them and running the mutants did not.

**Adding cases is the point.** Append to CASES: (label, file, exact source to
replace, replacement, pytest -k expression that must fail). An anchor matching
zero or two places is reported as a failure rather than skipped quietly — a
mutant that never got applied is not a mutant that was killed, which cost a real
finding once already here.

The domain, for anyone reading this cold: plamotrack is a single-user, self-hosted
model-kit collection tracker. The rules being mutated are data-integrity checks
about inventory counts and purchase records — that a paint order can't be counted
twice, that a line's quantity matches the kits attached to it. Nothing here was an
access control until the `ingr-` set (#186, M6-1): those cases mutate the Host/Origin
guard — which names the instance answers to, which browser origins may write — the
first request-boundary control in the app, defensive hardening of a self-hosted
service that still has no authentication behind it (milestone 6). Two of them mutate
a shell file, the nginx server-name generator, killed by a test that runs it. The
`auth-` set (#187, M6-2) is the first that mutates authorization itself — the
principal/scope algebra, the default-deny dependency's 401/403 branches, the route
policy registry and the response profile it declares — against an app built with
`create_app(authorization=True)`: the shipped app stays unenforced until #188, so
those kills come from the matrix that drives the real route graph through the
dependency with injected principals, not from the shipped configuration.

Restores from a backup in a `finally`, and refuses to start unless the tree is
clean, so an interrupted run is obvious in `git status`.
"""

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
INV = ROOT / "app/services/portability/invariants.py"
IMP = ROOT / "app/services/portability/importing.py"
STARTER = ROOT / "app/services/portability/starter_sheet.py"
NAMES = ROOT / "app/services/names.py"
ORD = ROOT / "app/services/orders.py"
CAT = ROOT / "app/services/catalog.py"
KITS = ROOT / "app/services/kits.py"
MCP = ROOT / "app/mcp.py"
SPEC = ROOT / "app/services/portability/spec.py"
EXP = ROOT / "app/services/portability/exporting.py"
UPG = ROOT / "app/services/upgrades.py"
INVR = ROOT / "app/routers/inventory.py"
VERS = ROOT / "alembic/versions"
SCH = ROOT / "app/schemas/orders.py"
SET = ROOT / "app/services/instance_settings.py"
MAIN = ROOT / "app/main.py"
EXC = ROOT / "app/exceptions.py"
EC = ROOT / "app/error_codes.py"
META = ROOT / "app/services/meta.py"
#: The shared #25/#26 registry fixture and the audit that reads it — the first
#: targets outside app/ (oma-2/4/5): the #178 class is registry drift, so the
#: mutants that matter break the declaration and the audit, not just emitters.
#: Both paths are in the clean-tree check below, the way #151 added alembic/.
FIX = ROOT.parent / "frontend/src/lib/__fixtures__/api-error-codes.json"
TEE = ROOT / "tests/test_error_envelope.py"
#: The M6-1 ingress guard (#186, PR #196): the policy and middlewares, the shared
#: host grammar, the settings validators, the app factory — and the nginx
#: server-name generator, a POSIX-sh file the corpus test runs under `sh`. The
#: clean-tree check covers that path too, the way FIX joined for oma-2.
ING = ROOT / "app/ingress.py"
HOSTS = ROOT / "app/hostnames.py"
CFG = ROOT / "app/config.py"
ENVSH = ROOT.parent / "frontend/nginx/15-plamotrack-server-names.envsh"
#: The M6-2 auth foundation (#187, PR #198): the principal/scope algebra, the
#: default-deny dependency and the response profile it enforces, the route
#: policy registry — and the auth migration, mutated under the mig- set's
#: clean-tree cover. `IMP` (the importer) carries `plan_requires_admin`.
PRIN = ROOT / "app/auth/principal.py"
DEP = ROOT / "app/auth/dependency.py"
REG = ROOT / "app/auth/registry.py"
CRED = ROOT / "app/auth/credentials.py"
SESS = ROOT / "app/auth/sessions.py"
AUTH_SVC = ROOT / "app/services/auth.py"
MAIN = ROOT / "app/main.py"
# The #189 (pat-) set: personal access tokens.
TOK_SVC = ROOT / "app/services/tokens.py"
TOK_FMT = ROOT / "app/auth/tokens.py"
RESOLVER = ROOT / "app/auth/resolver.py"
MCP_AUTH = ROOT / "app/auth/mcp_auth.py"
# The #204 (f13-) set: the pre-routing gate.
PRE = ROOT / "app/auth/prerouting.py"
AUTH_MIG = VERS / "20260903_f1058c5de0f3_auth_foundation_tables_m6_2_187.py"
# #191 (M6-6): the oidc- set.
OIDC_SVC = ROOT / "app/services/oidc.py"
AUTH_ROUTER = ROOT / "app/routers/auth.py"
MODE = ROOT / "app/auth/mode.py"
# #192 (M6-7): the moa- set — MCP OAuth.
MCP_OAUTH = ROOT / "app/auth/mcp_oauth.py"

# (label, file, old, new, pytest -k expression that MUST go red)
CASES = [
    (
        "inv-1. immutable line columns off",
        INV,
        "    _check_immutable_line_columns(rows)",
        "    pass  # neutered",
        "invariant_matrix or names_the_column",
    ),
    (
        "inv-2. catalog target check off",
        INV,
        "    _check_catalog_targets(rows, by_id=by_id, created_ids=created_ids, "
        "replace_all=replace_all)",
        "    pass  # neutered",
        "resolve_for_its_own_item_type or blank_reference_cell",
    ),
    (
        "inv-3. receipt transitions off",
        INV,
        "    _check_receipt_transitions(rows)",
        "    pass  # neutered",
        "cannot_receive_an_order or cannot_un_receive",
    ),
    (
        "inv-3a. clearing allowed, arrival still refused",
        INV,
        "        if not (arriving or clearing):",
        "        if not arriving:",
        "cannot_un_receive",
    ),
    (
        "inv-3b. only the stored lines count",
        INV,
        "    for line in incoming.get(row.matched_id, []):",
        "    for line in []:",
        "catalog_line_this_upload_adds",
    ),
    (
        "inv-3c. any received_at change refused, not just a transition",
        INV,
        "        if not (arriving or clearing):\n            continue",
        "        pass",
        "correction_between_two_timestamps",
    ),
    (
        "inv-3d. refused regardless of catalog lines",
        INV,
        "        if not types:\n",
        "        if False:\n",
        "kit_only_order_still_moves",
    ),
    (
        "inv-3e. the value compared instead of the change",
        INV,
        '        change = _change(row, "received_at")\n        if change is None:\n            continue',
        "        from app.schemas.portability import FieldChange\n\n"
        '        change = FieldChange(field="received_at", before="", after="x")',
        "still_restores_from_an_archive",
    ),
    (
        "inv-4. downward reconciliation off",
        IMP,
        "                self._plan_removals(\n                    row,\n                    surplus=-missing,\n                    kit_rows=kit_rows,\n                    attached=attached,\n                    protected=protected,\n                )",
        "                pass  # neutered",
        "invariant_matrix or newest_kit or quantity_the_sheet_never_states",
    ),
    (
        "inv-4a. a quantity the sheet never states still reconciles",
        IMP,
        '        stated = row.values.get("quantity") if "quantity" in row.present else None\n        return stated if isinstance(stated, int) else None',
        '        return row.values.get("quantity") or 0',
        "quantity_the_sheet_never_states or carrying_no_quantity",
    ),
    (
        "inv-4b. progressed kits are removable",
        IMP,
        "        candidates = [\n            kit for kit in attached if kit.id not in described and kit.id not in protected\n        ]",
        "        candidates = [kit for kit in attached if kit.id not in described]",
        "invariant_matrix",
    ),
    (
        "inv-4c. kits the upload describes are removable",
        IMP,
        "        candidates = [\n            kit for kit in attached if kit.id not in described and kit.id not in protected\n        ]",
        "        candidates = [kit for kit in attached if kit.id not in protected]",
        "the_same_upload_describes",
    ),
    (
        "inv-4d. removals stay out of the fingerprint",
        IMP,
        '        "removals": sorted(\n            [str(removal.kit_id), str(removal.order_item_id), str(removal.row_number)]\n            for removal in removals\n        ),',
        '        "removals": len(removals),',
        "hashes_stably_and_moves_with_its_kits",
    ),
    (
        "inv-5. generated status stamp off",
        IMP,
        "        self._defer_generated_status_stamp(spec, row)",
        "        pass  # mutated",
        "timestamp_the_board_reads or both_stamp_one_kit or both_claim_the_column",
    ),
    (
        "inv-5a. the clock is read at plan time instead of apply time",
        IMP,
        '        row.present.discard("status_updated_at")',
        '        row.values["status_updated_at"] = datetime.now(UTC)\n        row.present.add("status_updated_at")',
        "does_not_move_the_plan_hash",
    ),
    (
        "inv-5b. a stated timestamp no longer wins",
        IMP,
        '        if row.values.get("status_updated_at") is not None:\n            return\n',
        "",
        "timestamp_the_board_reads",
    ),
    (
        "inv-6. attached-after ignores reparenting entirely",
        IMP,
        "            attached = self._attached_after(line_id, stored, kit_rows)",
        "            attached = list(stored)",
        "counts_the_kits_the_line_will_hold or arriving_from_another_line",
    ),
    (
        "inv-6a. kits moved onto the line are not counted",
        IMP,
        "        arriving = [\n            kit\n            for kit_id, (parent, kit) in reparented.items()\n            if parent == line_id and kit_id not in on_line\n        ]",
        "        arriving = []",
        "counts_the_kits_the_line_will_hold or arriving_from_another_line",
    ),
    (
        "inv-6b. kits moved off the line are still counted",
        IMP,
        "        kept = [kit for kit in stored if reparented.get(kit.id, (line_id, kit))[0] == line_id]",
        "        kept = list(stored)",
        "counts_the_kits_the_line_will_hold",
    ),
    (
        "inv-6c. a row that never mentions order_item_id moves the kit anyway",
        IMP,
        '            if kit_row.matched_id is None or kit_row.target is None:\n                continue\n            if "order_item_id" not in kit_row.present:\n                continue\n',
        "            if kit_row.matched_id is None or kit_row.target is None:\n                continue\n",
        "never_mentions_order_item_id",
    ),
    (
        "inv-7. the clearing refusal offers only the catalog file",
        INV,
        '            f"otherwise: if the receipt was a mistake, delete the order — that reverses the "\n'
        '            f"stock it applied — and enter it again as pending. To correct the count on its "',
        '            f"otherwise: if the receipt was a mistake, ask someone. To correct the count on its "',
        "cannot_un_receive",
    ),
    (
        "inv-8. the fan-out classifies from values alone",
        IMP,
        "            if invariants.effective_item_type(row) is not ItemType.KIT:",
        '            if row.values.get("item_type") is not ItemType.KIT:',
        "omits_item_type_still_reconciles",
    ),
    (
        "inv-8a. a created line counts nothing as attached",
        IMP,
        "            attached = self._attached_after(line_id, stored, kit_rows)",
        "            attached = (\n                [] if row.target is None\n                else self._attached_after(line_id, stored, kit_rows)\n            )",
        "moved_onto_a_line_this_upload_creates",
    ),
    (
        "inv-9. kit-side lines are not checked at all",
        IMP,
        "        self._refuse_unreconciled_kit_moves(kit_rows, reconciled, replace_all)",
        "        pass  # mutated",
        "cannot_reconcile_is_refused",
    ),
    (
        "inv-9a. only the line a kit moves TO is considered",
        IMP,
        "            for line_id in (before_line, after_line):",
        "            for line_id in (after_line,):",
        "cannot_reconcile_is_refused",
    ),
    (
        "inv-9b. a reconciled line is checked for a count anyway",
        IMP,
        "            if line_id in reconciled:\n                continue",
        "            if False:\n                continue",
        "may_still_leave_a_shortfall_to_spawn",
    ),
    (
        "inv-9c. kit creates are left out of the post-write count",
        IMP,
        "            after = len(self._attached_after(line_id, stored_kits, kit_rows)) + created",
        "            after = len(self._attached_after(line_id, stored_kits, kit_rows))",
        "cannot_reconcile_is_refused",
    ),
    (
        "inv-12. a line authorises reconciliation without writing its quantity",
        IMP,
        "            if not self._writes_quantity(row):\n                continue",
        "            pass",
        "carrying_no_quantity_authorises_no_reconciliation or leaves_alone_authorises_no_reconciliation or drifted_line_is_a_no_op",
    ),
    (
        "inv-13. a kit may name a catalog order line as provenance",
        IMP,
        "            if item_type is not ItemType.KIT:",
        "            if False:",
        "provenance_from_a_catalog_line",
    ),
    (
        "inv-14. the fan-out runs before the refusals again",
        IMP,
        '        self._refuse_unreconciled_kit_moves(kit_rows, reconciled, replace_all)\n\n        for row in self.rows.get("order_items", []):',
        '        for row in self.rows.get("order_items", []):',
        "contributes_no_planned_removal",
    ),
    (
        "inv-15. an unstated quantity does not fall back to the stored row",
        IMP,
        "            if quantity is None and stored is not None:\n                quantity = stored.quantity",
        "            pass",
        "carrying_no_quantity_authorises_no_reconciliation",
    ),
    (
        "inv-20. add_only trusts the skipped upload row instead of stored state",
        IMP,
        "    def _planned_line(self, line_id: uuid.UUID) -> _Row | None:\n"
        '        """The order-items row this upload will write for `line_id`, if any.\n\n'
        "        `SKIP` deliberately doesn't count: `add_only` leaves the stored line exactly\n"
        "        as it is, so the stored row — not the uploaded one — is what describes it\n"
        "        afterwards.\n"
        '        """\n'
        '        for row in self.rows.get("order_items", []):\n'
        "            if row.action in (RowAction.ERROR, RowAction.SKIP):\n"
        "                continue",
        "    def _planned_line(self, line_id: uuid.UUID) -> _Row | None:\n"
        '        """The order-items row this upload will write for `line_id`, if any.\n\n'
        "        `SKIP` deliberately doesn't count: `add_only` leaves the stored line exactly\n"
        "        as it is, so the stored row — not the uploaded one — is what describes it\n"
        "        afterwards.\n"
        '        """\n'
        '        for row in self.rows.get("order_items", []):\n'
        "            if row.action is RowAction.ERROR:\n"
        "                continue",
        "review_add_only_uses_stored_line_not_skipped_upload",
    ),
    (
        "inv-21. refusal writes a message but does not error the row before fan-out",
        IMP,
        "    @staticmethod\n"
        "    def _error_rows(rows: list[_Row], diagnostic: Diagnostic) -> None:\n"
        "        for row in rows:\n"
        "            row.refuse(diagnostic)",
        "    @staticmethod\n"
        "    def _error_rows(rows: list[_Row], diagnostic: Diagnostic) -> None:\n"
        "        for row in rows:\n"
        "            row.errors.append(diagnostic)",
        "review_refused_move_does_not_leave_a_removal_in_the_plan",
    ),
    (
        "inv-16. a protected kit's provenance can be stripped",
        IMP,
        "        self._refuse_stripping_protected_provenance(kit_rows, protected)",
        "        pass  # mutated",
        "cannot_strip_protected_provenance",
    ),
    (
        "inv-16a. only a cleared link counts, not a moved one",
        IMP,
        '            if before is None or row.values.get("order_item_id") == before:',
        '            if before is None or row.values.get("order_item_id") is not None:',
        "moved_even_when_both_counts_work_out",
    ),
    (
        "inv-17. protection ignores a status this upload writes",
        IMP,
        '            status = row.values.get("status") if "status" in row.present else None\n            if status is not None and KitStatus(status) in PROGRESSED_STATUSES:\n                protected.add(kit_id)',
        "            pass",
        "cannot_strip_protected_provenance",
    ),
    (
        "inv-17a. protection ignores a child this upload creates",
        IMP,
        '        for table in ("upgrade_applications", "kit_photos"):',
        "        for table in ():",
        "protects_its_kit_from_removal or every_candidate_gains_a_child",
    ),
    (
        "inv-17b. protection ignores a rating this upload writes",
        IMP,
        '            if "rating" in row.present and row.values.get("rating") is not None:\n                protected.add(kit_id)',
        "            pass",
        "review_rating_this_upload_writes_protects_provenance",
    ),
    (
        "inv-17c. protection ignores stored evidence",
        IMP,
        '        protected = {kit.id for kit in self.existing["kits"] if kit_progressed(kit)}',
        "        protected = set()",
        "invariant_matrix or cannot_strip_protected_provenance",
    ),
    (
        "inv-18. only child CREATEs count as protection",
        IMP,
        "            for row in self.rows.get(table, []):\n                if row.action in (RowAction.ERROR, RowAction.SKIP):\n                    continue",
        "            for row in self.rows.get(table, []):\n                if row.action is not RowAction.CREATE:\n                    continue",
        "moves_protects_the_kit_it_arrives_on or moves_also_protects",
    ),
    (
        "inv-19. a created line is exempt from over-supply",
        IMP,
        "        stated = self._stated_quantity(row)\n        if not isinstance(stated, int):\n            return",
        "        stated = self._stated_quantity(row)\n        if row.target is None or not isinstance(stated, int):\n            return",
        "creates_cannot_be_over_supplied_either",
    ),
    (
        "inv-19a. over-supply by the upload borrows the stored-kit message",
        IMP,
        "            if not attached:",
        "            if False:",
        "creates_cannot_be_over_supplied_either",
    ),
    (
        "cell-1. a blank cell writes NULL into a NOT NULL column again",
        IMP,
        "        self._keep_stored_where_unstatable(spec, row)",
        "        pass  # mutated",
        "keeps_the_stored_value",
    ),
    (
        "cell-1a. nullability is read as always-nullable",
        IMP,
        "    return column is None or column.nullable",
        "    return True",
        "keeps_the_stored_value",
    ),
    (
        "cell-1b. the blank is kept but still planned as a change",
        IMP,
        "            row.present.discard(column.name)",
        "            pass",
        "keeps_the_stored_value",
    ),
    (
        "cell-1c. classification runs before references and money resolve",
        IMP,
        "                self._resolve_all_refs(spec, row, replace_all)\n                self._apply_money_alternates(spec, row)",
        "                pass",
        "mirror_still_wins",
    ),
    (
        "cell-2. an unfillable create is not refused",
        IMP,
        "                self._refuse_unfillable_creates(spec, row)",
        "                pass  # mutated",
        "missing_a_required_value_is_named",
    ),
    (
        "cell-2a. a schema default no longer counts as fillable",
        IMP,
        "    return column is not None and (column.default is not None or column.server_default is not None)",
        "    return False",
        "takes_the_schema_default or missing_a_required_value_is_named",
    ),
    (
        "cell-3. a dangling optional reference is silent again",
        IMP,
        "            elif dangling is not None and _column_is_nullable(spec, column.name):",
        "            elif False:",
        "dangling_optional_reference_is_reported",
    ),
    (
        "cell-3a. a required dangling reference degrades to a message",
        IMP,
        "            elif column.required:",
        "            elif False:",
        "required_column_still_blocks",
    ),
    (
        "cell-3b. the dangling message ignores whether the column can hold null",
        IMP,
        "            elif dangling is not None and _column_is_nullable(spec, column.name):",
        "            elif dangling is not None:",
        "the_row_keeps_anyway_says_only_that or refused_create_carries_no_message",
    ),
    (
        # Re-anchored (#117 review, P3-1): the old two-line anchor's `pass`
        # replacement stranded the block's tail at deeper indentation, so the
        # mutant never compiled and every run "killed" it with an
        # IndentationError instead of the named assertion. The discard is the
        # load-bearing half (the comment at the site says why), so mutating it
        # alone is the same semantic mutant, compiling.
        "cell-4. a refused create keeps the id it minted",
        IMP,
        "                self.created_ids[spec.key].discard(row.new_id)",
        "                pass  # mutated",
        "takes_back_the_id_it_minted",
    ),
    (
        "cell-5. a kit line drops its catalog reference silently",
        IMP,
        "                if discarded is not None:",
        "                if False:",
        "ignores_a_catalog_reference",
    ),
    (
        "cell-5a. the kit branch reports a dangling result as well",
        IMP,
        "                return None\n\n        dangling: tuple[str, uuid.UUID] | None = None",
        '                return ("catalog", discarded) if discarded else None\n\n        dangling: tuple[str, uuid.UUID] | None = None',
        "ignores_a_catalog_reference",
    ),
    (
        "cell-5b. a blank cell is reported as a discarded reference",
        IMP,
        "                if discarded is not None:",
        "                if True:",
        "no_catalog_reference_says_nothing",
    ),
    (
        "merge-1. keep-stored runs before the deferral",
        IMP,
        "        self._defer_generated_status_stamp(spec, row)\n        self._keep_stored_where_unstatable(spec, row)",
        "        self._keep_stored_where_unstatable(spec, row)\n        self._defer_generated_status_stamp(spec, row)",
        "both_claim_the_column",
    ),
    # --- #82 x #44: an unreadable id may not clear a stored link -------------------
    (
        "inv-22. an id that names nothing may clear a stored link again",
        IMP,
        "            if column is None or column.get(row.target) is None:\n                continue",
        "            if True:\n                continue",
        "may_not_clear_a_stored_link or mistyped_order_item_id",
    ),
    (
        "inv-22a. the refusal fires with nothing stored to lose",
        IMP,
        "            if column is None or column.get(row.target) is None:\n                continue",
        "            if column is None:\n                continue",
        "may_not_clear_a_stored_link",
    ),
    (
        "inv-22b. the withdrawn 'imports without it' line stays in the preview",
        IMP,
        "            row.messages = [message for message in row.messages if message != told]",
        "            pass",
        "may_not_clear_a_stored_link",
    ),
    # --- authority is a written quantity; the refusal reads only moves ------------
    (
        "inv-12a. a created line no longer authorises reconciliation",
        IMP,
        "        if row.action is RowAction.CREATE:\n            return True",
        "        if row.action is RowAction.CREATE:\n            return False",
        "moved_onto_a_line_this_upload_creates or creates_cannot_be_over_supplied_either",
    ),
    (
        "inv-23. a kits row restating where its kit already is counts as a move",
        IMP,
        "            if after_line == before_line:\n                continue",
        "            pass",
        "drifted_line_is_a_no_op",
    ),
    (
        "inv-23a. a restated line's mismatch borrows the absent-line message",
        IMP,
        "            elif after != quantity and planned is not None:",
        "            elif False:",
        "leaves_alone_authorises_no_reconciliation",
    ),
    (
        "inv-23b. the refusal reads a kits row with no order_item_id column as a detach",
        IMP,
        '            if "order_item_id" not in kit_row.present:\n'
        "                continue\n"
        '            after_line = kit_row.values.get("order_item_id")',
        '            after_line = kit_row.values.get("order_item_id")',
        "never_mentions_order_item_id",
    ),
    (
        "stamp-1. a spawned kit stops borrowing the order's receipt",
        IMP,
        "            received_at=spawn.received_at,",
        "            received_at=None,",
        "borrows_its_receipt or carrying_its_receipt",
    ),
    (
        "stamp-2. the receive advance's descriptor takes the clock, not the receipt",
        IMP,
        "                        after, stamp = KitStatus.BACKLOG, newly_received",
        "                        after, stamp = KitStatus.BACKLOG, datetime.now(UTC)",
        "stamps_the_advance",
    ),
    (
        "stamp-3. the spawn's receipt instant falls out of the plan fingerprint",
        IMP,
        "                spawn.received,\n                canon(spawn.received_at),",
        "                spawn.received,",
        "stales_the_hash",
    ),
    (
        "fut-1. the future-receipt check is off",
        INV,
        "    _check_future_receipts(rows)",
        "    pass  # neutered",
        "in_the_future or into_the_future",
    ),
    (
        "fut-2. the refusal reads the cell instead of the change",
        INV,
        '        change = _change(row, "received_at")\n'
        "        if change is None or not change.after:\n"
        "            continue\n"
        '        value = row.values.get("received_at")',
        '        value = row.values.get("received_at")',
        "restores_a_future or restated_is_still",
    ),
    # --- #95: shipped_at, one mutant per fix site ------------------------------------
    (
        "ship-1. the ship advance re-stamps kits already in transit",
        ORD,
        "                if kit.status in SHIP_ELIGIBLE:",
        "                if kit.status in ARRIVAL_ELIGIBLE:",
        "ship_moves_pipeline_kits",
    ),
    (
        "ship-2. the ship advance forgets the stamp",
        ORD,
        "                    kit.status = KitStatus.IN_TRANSIT\n"
        "                    kit.status_updated_at = now",
        "                    kit.status = KitStatus.IN_TRANSIT",
        "ship_moves_pipeline_kits or ship_without_a_date",
    ),
    (
        "ship-3. a future entry-time shipment is accepted",
        ORD,
        "        _refuse_future_ship(data.shipped_at)",
        "        pass",
        "create_with_future_shipped_at",
    ),
    (
        "ship-4. the import-side ship rules are off",
        INV,
        "    _check_ship_dates(rows)",
        "    pass  # neutered",
        "unship_by_import or future_ship_date_by_import",
    ),
    # ship-5/ship-12/stamp-2 were re-anchored by #119: the apply-time advance
    # functions became plan-time `_Advance` descriptors consumed by
    # `_apply_planned_advances`, so the sites moved with them.
    (
        "ship-5. the apply stamps the advance with the clock, not the descriptor",
        IMP,
        "        kit.status_updated_at = advance.stamp",
        "        kit.status_updated_at = datetime.now(UTC)",
        "ship_by_import_advances",
    ),
    (
        "ship-6. the spawn's ship instant falls out of the plan fingerprint",
        IMP,
        "                canon(spawn.received_at),\n                canon(spawn.shipped_at),",
        "                canon(spawn.received_at),",
        "ship_correction_between_preview_and_apply",
    ),
    (
        "ship-7. a spawn never borrows the ship instant",
        ORD,
        "    if final_status is KitStatus.IN_TRANSIT:\n        stamp = shipped_at",
        "    pass",
        "create_shipped_lands_kits_in_transit or line_added_to_a_shipped_order",
    ),
    # --- round one, P3-3: the sites ship-4's whole-validator neuter and the ----------
    # --- original seven left unmutated, one tuple per site; ship-8 is the P2 fix -----
    (
        "ship-4a. clearing a ship date imports again",
        INV,
        "        if change.before and not change.after:",
        "        if False:",
        "unship_by_import",
    ),
    (
        "ship-4b. a future ship date imports again",
        INV,
        "        if value is not None and change.after and receipt_is_future(value):",
        "        if False:",
        "future_ship_date_by_import",
    ),
    (
        "ship-8. the ship correction takes any kit with the old stamp",
        ORD,
        "only_status=KitStatus.IN_TRANSIT",
        "only_status=None",
        "never_takes_a_receipt",
    ),
    (
        "ship-9. the transition's future guard is off",
        ORD,
        "    if shipped_at is not None:\n        _refuse_future_ship(shipped_at)",
        "    pass",
        "ship_with_a_future_date",
    ),
    (
        "ship-10. the correction's future guard is off",
        ORD,
        "        _refuse_future_ship(new_ship)",
        "        pass",
        "patch_ship_correction_into_the_future",
    ),
    (
        "ship-11. entry never lands a spawn in transit",
        ORD,
        "    if shipped and requested in SHIP_ELIGIBLE:\n        return KitStatus.IN_TRANSIT",
        "    pass",
        "create_shipped_lands_kits_in_transit",
    ),
    (
        "ship-12. the import advance stamps without moving the status",
        IMP,
        "        kit.status = advance.after\n        kit.status_updated_at = advance.stamp",
        "        kit.status_updated_at = advance.stamp",
        "ship_by_import_advances",
    ),
    # --- #107 / PR #109: name uniqueness (tuples from the PR body's collapsed -------
    # --- block, anchors verified once at d1d051d; folded in after #86 landed) -------
    (
        "n1. stored side not trimmed",
        NAMES,
        "func.lower(func.btrim(model.name, WHITESPACE)) == func.lower(name)",
        "func.lower(model.name) == func.lower(name)",
        "surrounding_whitespace and space",
    ),
    (
        "n1b. stored side trimmed of spaces only (btrim's default)",
        NAMES,
        "func.lower(func.btrim(model.name, WHITESPACE)) == func.lower(name)",
        'func.lower(func.btrim(model.name, " ")) == func.lower(name)',
        "(surrounding_whitespace or legacy_padded) and (tab or nbsp or newline or ideographic)",
    ),
    (
        "n2. input side not folded",
        NAMES,
        "func.lower(func.btrim(model.name, WHITESPACE)) == func.lower(name)",
        "func.lower(func.btrim(model.name, WHITESPACE)) == name",
        "create_refuses_a_name and recased-stored-lower",
    ),
    (
        "n3. stored side not folded",
        NAMES,
        "func.lower(func.btrim(model.name, WHITESPACE)) == func.lower(name)",
        "func.btrim(model.name, WHITESPACE) == func.lower(name)",
        "create_refuses_a_name and recased-stored-upper",
    ),
    (
        "n4. own id not excluded on rename",
        NAMES,
        "    if exclude_id is not None:\n        stmt = stmt.where(model.id != exclude_id)",
        "    pass",
        "rename_to_a_free_name_or_its_own",
    ),
    (
        "n5. blank not refused",
        NAMES,
        "    if not cleaned:\n"
        '        raise InvalidInputError("name cannot be blank", code=error_codes.NAME_BLANK)',
        "    pass",
        "whitespace_only or rename_to_blank or blank_retailer",
    ),
    (
        "n6a. clean_name stops stripping",
        NAMES,
        '        raise InvalidInputError("name cannot be blank", code=error_codes.NAME_BLANK)\n'
        "    return cleaned\n",
        '        raise InvalidInputError("name cannot be blank", code=error_codes.NAME_BLANK)\n'
        "    return name\n",
        "different-padded or Gundam_Base or creates_it_stripped or padded-input",
    ),
    (
        "n6b. require_unique_name hands back the raw name",
        NAMES,
        '                "existing_id": existing.id,\n'
        "            },\n        )\n    return cleaned\n",
        '                "existing_id": existing.id,\n            },\n        )\n    return name\n',
        "different-padded or Gundam_Base or creates_it_stripped",
    ),
    (
        "n7. the refusal itself",
        NAMES,
        "    if existing is not None:\n        noun = _NOUN[model]",
        "    if False:\n        noun = _NOUN[model]",
        "refuses or one_row_and_one_409 or conflict_not_an_integrity",
    ),
    (
        "o1. create_retailer skips the check",
        ORD,
        '    fields["name"] = await require_unique_name(session, Retailer, data.name)',
        '    fields["name"] = data.name.strip()',
        "retailers and (create_refuses_a_name or stored_with_surrounding) or mcp_create_retailer "
        "or one_row_and_one_409 or conflict_not_an_integrity",
    ),
    (
        "o2. update_retailer skips the check",
        ORD,
        '    if fields.get("name") is not None:\n'
        "        # `exclude_id`: a row may keep or re-case its own name; only *another* row\n"
        "        # already holding it is a conflict (#107).\n"
        '        fields["name"] = await require_unique_name(\n'
        '            session, Retailer, fields["name"], exclude_id=retailer.id\n'
        "        )",
        "    pass",
        "rename_onto_another and retailers or mcp_update_retailer",
    ),
    (
        "o3. new_item skips the check",
        ORD,
        "    name = await require_unique_name(session, CATALOG_MODELS[item_type], new_item.name)",
        "    name = new_item.name",
        "new_item",
    ),
    (
        "o4. get_or_create_retailer stops cleaning",
        ORD,
        "    wanted = clean_name(name)",
        "    wanted = name.strip()",
        "blank_retailer_name",
    ),
    (
        "o5. create_retailer checks before it takes the gate",
        ORD,
        "    await acquire_write_gate(session)\n"
        "    fields = data.model_dump()\n"
        "    # Refused, not merged: a REST or MCP caller that named an existing shop gets a 409\n"
        "    # naming it, and decides. Merging silently would hand back a row the caller did\n"
        "    # not ask for and could not tell apart from a create (#107, rule 3).\n"
        '    fields["name"] = await require_unique_name(session, Retailer, data.name)',
        "    fields = data.model_dump()\n"
        '    fields["name"] = await require_unique_name(session, Retailer, data.name)\n'
        "    await acquire_write_gate(session)",
        "one_row_and_one_409",
    ),
    (
        "c1. catalog create skips the check",
        CAT,
        '    fields["name"] = await require_unique_name(session, model, data.name)',
        '    fields["name"] = data.name.strip()',
        "(tools or consumables or upgrades) and (create_refuses_a_name or stored_with_surrounding)",
    ),
    (
        "c2. catalog rename skips the check",
        CAT,
        '    if fields.get("name") is not None:\n'
        "        # A rename onto a name another row of this table holds is a 409; the row's\n"
        "        # own id is excluded so it may keep or re-case its name (#107).\n"
        '        fields["name"] = await require_unique_name(\n'
        '            session, model, fields["name"], exclude_id=item_id\n'
        "        )",
        "    pass",
        "rename_onto_another and (tools or consumables or upgrades) or mcp_catalog_rename",
    ),
    (
        "c3. catalog rename excludes nothing",
        CAT,
        '            session, model, fields["name"], exclude_id=item_id',
        '            session, model, fields["name"], exclude_id=None',
        "rename_to_a_free_name_or_its_own and (tools or consumables or upgrades)",
    ),
    # --- #93 / PR #111: backdatable receipts (tuples from the PR body, verified ------
    # --- at a78ce76). rcpt-1 is re-anchored: #86's receipt_is_future refactor --------
    # --- turned the predicate's `if` into a `return`, same comparison. ---------------
    (
        "rcpt-1. today is refused along with the future",
        ORD,
        "    return received_at.date() > today_in_own_offset",
        "    return received_at.date() >= today_in_own_offset",
        "receipt_late_today_in_a_behind_offset",
    ),
    (
        "rcpt-2. the calendar is read in server time, not the instant's offset",
        ORD,
        "datetime.now(received_at.tzinfo)",
        "datetime.now(UTC)",
        "receipt_today_in_an_ahead_offset",
    ),
    (
        "rcpt-3. every spawned kit borrows the receipt, asserted statuses included",
        ORD,
        "    stamp = received_at if final_status is KitStatus.BACKLOG else None",
        "    stamp = received_at",
        "create_received_kit_asserted_building_keeps_the_entry_stamp",
    ),
    (
        "rcpt-4. a correction restamps every kit, moved ones included",
        ORD,
        "            if kit.status_updated_at == old:",
        "            if True:",
        "patch_corrects_the_receipt_and_restamps_only_untouched_kits",
    ),
    (
        "rcpt-5. a correction lands on a pending order",
        ORD,
        "        if order.received_at is None:",
        "        if False:",
        "patch_received_at_on_a_pending_order_is_a_conflict",
    ),
    # --- #94 + #96 / PR #113: build dates + series (tuples from the round-1 ----------
    # --- Cursor review, anchors verified once at 523deed) ----------------------------
    (
        "bd-1. the stamp overwrites a date someone set",
        KITS,
        "    if getattr(kit, field) is None:",
        "    if True:",
        "reentering_building_keeps_the_original_start or user_set_date_survives",
    ),
    (
        "bd-2. an explicitly supplied field is fought",
        KITS,
        "    if field is None or field in supplied:",
        "    if field is None:",
        "explicit_null_in_the_transitioning_patch",
    ),
    (
        "ser-1. frequency ordering dropped",
        KITS,
        "        .order_by(func.count().desc(), func.lower(Kit.series))",
        "        .order_by(func.count(), func.lower(Kit.series))",
        "distinct_values_come_most_frequent_first",
    ),
    (
        "ser-2. the series filter stops folding case",
        KITS,
        "        stmt = stmt.where(func.lower(Kit.series) == func.lower(series))",
        "        stmt = stmt.where(Kit.series == series)",
        "series_filter_is_case_insensitive_equality",
    ),
    (
        "ser-3. the series column vanishes from the spec",
        SPEC,
        '        col("series", parse_text, help="e.g. Iron-Blooded Orphans. Free text (#96)."),\n',
        "",
        "csv_round_trip_preserves_series or kits_spec_declares_series",
    ),
    # --- #97 / PR #115: MCP order edit (tuples from the PR body, verified at ---------
    # --- b7318c4) --------------------------------------------------------------------
    (
        "moe-1. the service omission gate hardwired off",
        ORD,
        "        if not allow_line_removal:",
        "        if False:",
        "test_omitting_a_stored_line_is_refused_by_default",
    ),
    (
        "moe-2. the MCP wrapper always allows line removal",
        MCP,
        "allow_line_removal=remove_missing_lines",
        "allow_line_removal=True",
        "test_omitting_a_stored_line_is_refused_by_default",
    ),
    # --- #126 / PR #129: display_items (tuples from the PR body; anchors re-checked --
    # --- at fold-in against `2b94a41` — none had moved under #130) -------------------
    (
        "dsp-1. the export loses the display_items table",
        EXP,
        '        "display_items": list(\n'
        "            (await session.scalars(select(DisplayItem).order_by(DisplayItem.name))).all()\n"
        "        ),",
        '        "display_items": [],',
        "round_trips_through_replace_all or restores_into_an_empty",
    ),
    (
        "dsp-2. the export drops the DISPLAY catalog-name map",
        EXP,
        '        ItemType.DISPLAY: {d.id: d.name for d in data["display_items"]},\n',
        "",
        "display_order_line_exports_and_reimports",
    ),
    (
        "dsp-4. names._NOUN loses its DisplayItem entry",
        NAMES,
        '    DisplayItem: "a display item",\n',
        "",
        "raises_a_conflict_not_an_integrity_error",
    ),
    (
        "dsp-5. _is_nullable reverts to the bare name set",
        CAT,
        "    return column is not None and column.nullable",
        "    return False",
        "clearing_manufacturer",
    ),
    (
        "dsp-6. DISPLAY drops out of the category-required tuple",
        ORD,
        "    if item_type in (ItemType.TOOL, ItemType.CONSUMABLE, ItemType.DISPLAY) and not category:",
        "    if item_type in (ItemType.TOOL, ItemType.CONSUMABLE) and not category:",
        "requires_a_category_but_not",
    ),
    (
        "dsp-7. catalog_names back to the three-table literal",
        IMP,
        "        for table in CATALOG_TABLES:\n            self.catalog_names.update(",
        '        for table in ("tools", "consumables", "upgrades"):\n'
        "            self.catalog_names.update(",
        "foreign_uuid",
    ),
    (
        "dsp-8. stubs skip required columns for display_items",
        IMP,
        "            if column.required and column.name not in values:",
        '            if column.required and column.name not in values and table != "display_items":',
        "name_only_catalog_line",
    ),
    (
        "dsp-9. _normalise_text leaves required text alone",
        CAT,
        "        elif value is not None:\n            fields[key] = clean_required_text(value, key)",
        "        elif value is not None:\n            pass",
        "required_text_column",
    ),
    (
        "dsp-10. the order dispatch stops trimming category",
        ORD,
        "    category = clean_optional_text(new_item.category)",
        "    category = new_item.category",
        "new_item_holds_the_same_text_rule",
    ),
    (
        "dsp-11. update_catalog_display dispatches TOOL (survived a green suite once)",
        MCP,
        "row = await catalog_service.update_catalog_item(session, ItemType.DISPLAY, parsed, changes)",
        "row = await catalog_service.update_catalog_item(session, ItemType.TOOL, parsed, changes)",
        "mcp_catalog_edits_cover_every_table",
    ),
    # --- #98 + #127 (+ #99) / PR #130: catalog create/list + category vocabulary -----
    # --- (tuples from the PR body and the three review rounds; verified at `f2215ff`,
    # --- re-checked at fold-in against `2b94a41`) ------------------------------------
    (
        "cat-1. create path fold off",
        CAT,
        '    if fields.get("category"):\n'
        '        fields["category"] = await canonical_category(session, model, fields["category"])\n',
        "",
        "create_folds_category_onto_the_existing_spelling",
    ),
    (
        "cat-2. update path fold off",
        CAT,
        '    if fields.get("category"):\n'
        "        # Same exclusion, opposite lean: another row's spelling is reused rather\n"
        "        # than refused, and the row's own is excluded so a re-case can correct it.\n"
        '        fields["category"] = await canonical_category(\n'
        '            session, model, fields["category"], exclude_id=item_id\n'
        "        )\n",
        "",
        "update_folds_category_onto_another_rows_spelling or mcp_update_folds",
    ),
    (
        "cat-3. exclude_id dropped",
        CAT,
        "        stmt = stmt.where(model.id != exclude_id)",
        "        pass  # neutered",
        "recasing_the_only_holder_wins",
    ),
    (
        "cat-4. canonical pick ignores frequency",
        CAT,
        '        .order_by(func.count().desc(), trimmed.collate("C"))',
        '        .order_by(trimmed.collate("C"))',
        "most_frequent_legacy_spelling_wins",
    ),
    (
        "cat-5. canonical tie-break loses its collation pin",
        CAT,
        '        .order_by(func.count().desc(), trimmed.collate("C"))',
        "        .order_by(func.count().desc(), trimmed)",
        "frequency_tie_breaks_by_byte_order",
    ),
    (
        "cat-6. order new_item fold off",
        ORD,
        "        category = await canonical_category(session, CATEGORISED_MODELS[item_type], category)\n",
        "        pass\n",
        "order_new_item_line_folds_its_category",
    ),
    (
        "cat-7. list filter becomes a pattern",
        CAT,
        "        stmt = stmt.where(func.lower(trimmed) == func.lower(category.strip()))",
        "        stmt = stmt.where(model.category.ilike(category))",
        "category_filter_is_case_insensitive_equality",
    ),
    (
        "cat-8. list filter folds one side only",
        CAT,
        "        stmt = stmt.where(func.lower(trimmed) == func.lower(category.strip()))",
        "        stmt = stmt.where(trimmed == func.lower(category.strip()))",
        "category_filter_is_case_insensitive_equality",
    ),
    (
        "cat-9. vocabulary ignores frequency",
        CAT,
        '        .order_by(func.count().desc(), func.lower(trimmed), trimmed.collate("C"))',
        '        .order_by(func.lower(trimmed), trimmed.collate("C"))',
        "distinct_categories_come_most_frequent_first",
    ),
    (
        "cat-10. vocabulary blank guard off",
        CAT,
        '        .where(trimmed != "")\n',
        "",
        "distinct_categories_hide_a_legacy_blank_row",
    ),
    (
        "cat-11. kit refusal off in item_type parsing",
        MCP,
        '    if normalized == "kit":\n'
        "        raise ToolError(\n"
        '            "kits are not a catalog table — list them with list_kits, add one with "\n'
        '            "create_kit (or a kit line on create_order for a purchase)"\n'
        "        )\n",
        "",
        "kits_are_refused or refuses_category_asks",
    ),
    (
        "cat-12. create_kit status vocabulary off",
        MCP,
        '    fields = kit.model_dump()\n    fields["status"] = _parse_status(fields["status"])\n',
        "    fields = kit.model_dump()\n",
        "create_kit_takes_the_tolerant_status_vocabulary",
    ),
    (
        "cat-13. filter's no-column refusal off",
        CAT,
        "            raise InvalidInputError(\n"
        '                f"{model.__tablename__} have no category column, so they cannot be filtered by one",\n'
        "                code=error_codes.CATALOG_ITEM_CATEGORY_UNSUPPORTED,\n"
        '                params={"table": model.__tablename__},\n'
        "            )",
        "            pass  # neutered",
        "refuses_category_asks_that_have_no_answer",
    ),
    (
        "cat-14. vocabulary's no-column refusal off",
        CAT,
        "        raise InvalidInputError(\n"
        '            f"{model.__tablename__} have no category column, so there is no "\n'
        '            "category vocabulary to list",\n'
        "            code=error_codes.CATALOG_ITEM_CATEGORY_UNSUPPORTED,\n"
        '            params={"table": model.__tablename__},\n'
        "        )",
        "        pass  # neutered",
        "refuses_category_asks_that_have_no_answer",
    ),
    (
        "cat-15. upgrade new_item gate off (#130 round 1, P2-1)",
        ORD,
        "    if category is not None and item_type in CATEGORISED_MODELS:",
        "    if category is not None:",
        "upgrade_new_item_line_carrying_a_category",
    ),
    (
        "cat-16. canonical pick returns the raw stored bytes (#130 round 1, P2-2)",
        CAT,
        "    stmt = (\n        select(trimmed)\n"
        "        .where(func.lower(trimmed) == func.lower(category.strip()))",
        "    stmt = (\n        select(model.category)\n"
        "        .where(func.lower(trimmed) == func.lower(category.strip()))",
        "never_propagates_legacy_padding",
    ),
    (
        "cat-17. filter loses its stored-side trim (#130 round 1, P2-2)",
        CAT,
        "        trimmed = func.btrim(model.category, WHITESPACE)\n"
        "        stmt = stmt.where(func.lower(trimmed) == func.lower(category.strip()))",
        "        stmt = stmt.where(func.lower(model.category) == func.lower(category.strip()))",
        "legacy_padded_category_is_found",
    ),
    (
        "cat-18. vocabulary returns the raw stored bytes (#130 round 1, P2-2)",
        CAT,
        '        select(trimmed)\n        .where(trimmed != "")',
        '        select(model.category)\n        .where(trimmed != "")',
        "legacy_padded_category_is_found",
    ),
    (
        "cat-19. importer folds id-bearing restores too (#130 round 1, P2-3)",
        IMP,
        "            return row.action is RowAction.CREATE and (\n"
        '                row.synthetic_id or row.values.get("id") is None\n'
        "            )",
        "            return row.action is RowAction.CREATE",
        "id_bearing_restore_create_keeps_its_stated_spelling",
    ),
    (
        "cat-20. importer fold off entirely (#130 round 1, P2-3)",
        IMP,
        "        self._fold_new_categories(replace_all)",
        "        pass  # neutered",
        "id_less_import_create_folds_its_category",
    ),
    (
        "cat-21. replace_all seeds the doomed stored vocabulary (#130 round 1, P2-3)",
        IMP,
        "            if not replace_all:\n                for instance in self.existing[spec.key]:",
        "            if True:\n                for instance in self.existing[spec.key]:",
        "uploads_own_rows_not_the_doomed_ones",
    ),
    (
        "cat-22. restores stop voting in the multiset (#130 round 2, P2-5)",
        IMP,
        "            for row in rows:\n"
        "                if row.action is RowAction.CREATE and not folds(row):\n"
        "                    # An id-bearing create-is-a-restore votes; UPDATEs already\n"
        "                    # voted through the overlay of the row they rewrite.\n"
        "                    value = stated_category(row)\n"
        "                    if value is not None:\n"
        "                        spellings[value.lower()][value] += 1\n",
        "",
        "folds_onto_a_restored_rows_spelling or vote_by_frequency",
    ),
    (
        "cat-23. the fold stops announcing itself in the preview (#130 round 1, P2-3)",
        IMP,
        "                    row.messages.append(\n"
        "                        Diagnostic(\n"
        "                            code=error_codes.IMPORT_CATEGORY_FOLDED,\n"
        '                            params={"stated": value, "stored": vocab[key]},\n'
        "                            detail=(\n"
        "                                f\"category '{value}' will be stored as '{vocab[key]}', \"\n"
        '                                "matching the spelling already in use"\n'
        "                            ),\n"
        "                        )\n"
        "                    )",
        "                    pass",
        "fold_is_stated_in_the_preview",
    ),
    (
        "cat-24. updates stop overlaying the rows they rewrite (#130 round 2, P2-5)",
        IMP,
        "            overlays: dict[uuid.UUID, str | None] = {}\n"
        "            for row in rows:\n"
        "                if row.action is RowAction.UPDATE and row.matched_id is not None:\n"
        '                    if "category" in row.present:\n'
        "                        overlays[row.matched_id] = stated_category(row)\n",
        "            overlays: dict[uuid.UUID, str | None] = {}\n",
        "update_is_writing",
    ),
    (
        "cat-25. the winner reverts to first-seen instead of the counted pick (#130 round 2, P2-5)",
        IMP,
        "                key: min(counted.items(), key=lambda item: (-item[1], item[0]))[0]",
        "                key: next(iter(counted.items()))[0]",
        "vote_by_frequency",
    ),
    # --- #90 / PR #133: the typeless catalog dispatch (tuples from the PR body;
    # anchors re-checked at the merged head `545f341`). The spawn-planning line of
    # the same shape reads `self.by_id["order_items"].get(line_id)` — a different
    # string, so ref-1/ref-2 cannot land there. -----------------------------------
    (
        "ref-1. the resolver reads the row as typeless again (#133)",
        IMP,
        '            stored = None if replace_all else self.by_id[spec.key].get(row.values.get("id"))',
        "            stored = None",
        "omitting_item_type",
    ),
    (
        "ref-2. replace_all types the line from the doomed database (#133)",
        IMP,
        '            stored = None if replace_all else self.by_id[spec.key].get(row.values.get("id"))',
        '            stored = self.by_id[spec.key].get(row.values.get("id"))',
        "doomed_database",
    ),
    (
        "ref-3. effective_item_type ignores the stored line it was handed (#133)",
        INV,
        '    return getattr(row.target if row.target is not None else stored, "item_type", None)',
        '    return getattr(row.target, "item_type", None)',
        "readable_mirror or uploads_remap or does_not_write_a_catalog_ref",
    ),
    # --- #112 / PR #136: the starter sheet's kit fan-out (tuples from the PR body,
    # queued as st-1..7 there; relabelled strt- at fold-in because "st-" is a
    # substring of "post-write" and "first-seen" in older labels, so `-k st-`
    # would select those too). Anchors re-checked at the merged head `ce59b2b`. ---
    (
        "strt-1. kit rows lose their purchase provenance (#136)",
        STARTER,
        "                    order_item_id=pending.line_id,\n",
        "",
        "retailer_row_carries_every_kit_field",
    ),
    (
        "strt-2. the landing status skips the shared resolution (#136)",
        STARTER,
        "        final = initial_kit_status(requested, received)",
        "        final = requested",
        "retailer_row_carries_every_kit_field",
    ),
    (
        "strt-3. the arrival stamp is never written (#136)",
        STARTER,
        '        stamp = orders[pending.key].get("received_at", "") if final is KitStatus.BACKLOG'
        ' else ""',
        '        stamp = ""',
        "receipt_instant",
    ),
    (
        "strt-4. repeated rows collapse onto one line id (#136)",
        STARTER,
        "        occurrence = line_occurrence.get(seq_key, 0)",
        "        occurrence = 0",
        "identical_rows_of_one_order",
    ),
    (
        "strt-5. the order line loses its synthesized id (#136)",
        STARTER,
        "                id=line_id,\n",
        "",
        "retailer_row_carries_every_kit_field or reimporting_a_kit_carrying",
    ),
    (
        "strt-6. series stops travelling (#136)",
        STARTER,
        '                        "series": row.get("series", ""),',
        '                        "series": "",',
        "retailer_row_carries_every_kit_field",
    ),
    (
        "strt-7. the kit fan-out reads blank received as no (#136)",
        STARTER,
        "    for pending in pending_kits:\n"
        "        settled = receipts.get(pending.key)\n"
        "        received = settled.stated if settled is not None else True",
        "    for pending in pending_kits:\n"
        "        settled = receipts.get(pending.key)\n"
        "        received = settled.stated if settled is not None else False",
        "receipt_instant",
    ),
    # --- #119 / PR #139: derived ship/receive advances as hash-bound plan ------------
    # --- descriptors; one mutant per fix site. The equivalent mutant (receive --------
    # --- branch reading kit.status instead of the ship-composed `after`) is ----------
    # --- excluded: SHIP_ELIGIBLE ⊂ ARRIVAL_ELIGIBLE makes the two reads always agree.
    (
        "adv-1. the advance descriptors fall out of the plan fingerprint",
        IMP,
        '        "advances": sorted(\n'
        "            [str(advance.kit_id), advance.before.value, advance.after.value, canon(advance.stamp)]\n"
        "            for advance in advances\n"
        "        ),",
        '        "advances": [],',
        "kit_progressed_between",
    ),
    (
        "adv-2. the before-status falls out of the descriptor's fingerprint",
        IMP,
        "            [str(advance.kit_id), advance.before.value, advance.after.value, canon(advance.stamp)]",
        "            [str(advance.kit_id), advance.after.value, canon(advance.stamp)]",
        "still_eligible_move",
    ),
    (
        "adv-3. the explicit-status yield is off",
        IMP,
        "                    if kit.id in explicit_status_ids:\n                        continue",
        "                    if False:\n                        continue",
        "do_not_both_stamp_one_kit",
    ),
    (
        "adv-4. ship eligibility widens to every status",
        IMP,
        "                    if newly_shipped is not None and after in SHIP_ELIGIBLE:",
        "                    if newly_shipped is not None:",
        "preview_names_the_ship_advance",
    ),
    (
        "adv-5. a correction counts as a transition again",
        IMP,
        "        change = next((c for c in row.changes if c.field == column), None)\n        if change is None or change.before:\n            return None",
        "        change = next((c for c in row.changes if c.field == column), None)\n        if change is None:\n            return None",
        "never_advances_a_regressed",
    ),
    (
        "adv-6. the preview stops counting the advances",
        IMP,
        "            kits_advanced=len(self.advances),",
        "            kits_advanced=0,",
        "preview_names_the_ship_advance",
    ),
    # adv-7 re-anchored by #77: the aggregate fan-out check now sits between
    # `_plan_spawns` and `_plan_advances` in `build()`, so the two-line anchor split.
    (
        "adv-7. the advances are never planned at all",
        IMP,
        "        self._plan_advances()",
        "        pass  # neutered",
        "ship_by_import_advances",
    ),
    # --- #77 / PR #141: the aggregate fan-out ceiling; one mutant per fix site. ------
    # --- Prefix note: `fan-` was rejected — `-k fan-` substring-matches "fan-out" ----
    # --- in strt-7's label; `cap-` matches nothing else here. ------------------------
    (
        "cap-1. the aggregate ceiling is off",
        ORD,
        "    if total > MAX_TOTAL_FANOUT:",
        "    if False:",
        "cannot_derive_more_kits",
    ),
    (
        "cap-2. entry stops asking the aggregate",
        ORD,
        "    require_total_fanout(_stated_kit_units(data.items))",
        "    pass",
        "cannot_derive_more_kits",
    ),
    (
        "cap-3. the edit stops asking the aggregate",
        ORD,
        "    require_total_fanout(_stated_kit_units(data.items or ()))",
        "    pass",
        "cannot_state_the_order_past",
    ),
    (
        "cap-4. the import plan stops asking the aggregate",
        IMP,
        "        try:\n"
        "            require_total_fanout(\n"
        "                sum(spawn.count for spawn in self.spawns),\n"
        '                label="the kits this import would create from order lines",\n'
        "            )\n"
        "        except InvalidInputError as exc:\n"
        "            # The service that owns the ceiling also owns the condition: the\n"
        "            # diagnostic borrows the raise's own code and params\n"
        "            # (`order.fanout_limit`), which the #25 raise-site audit already\n"
        "            # holds to the fixture.\n"
        "            self.blocking.append(_borrowed_diagnostic(exc))",
        "        pass",
        "import_cannot_spawn_past",
    ),
    (
        "cap-5. catalog lines count toward the fan-out",
        ORD,
        "    return sum(line.quantity for line in lines if line.item_type is ItemType.KIT)",
        "    return sum(line.quantity for line in lines)",
        "catalog_lines_do_not_count_toward",
    ),
    (
        "cap-6. the boundary moves down one",
        ORD,
        "    if total > MAX_TOTAL_FANOUT:",
        "    if total >= MAX_TOTAL_FANOUT:",
        "cannot_derive_more_kits",
    ),
    (
        "cap-7. the import counts spawn descriptors instead of kits",
        IMP,
        "                sum(spawn.count for spawn in self.spawns),",
        "                len(self.spawns),",
        "import_cannot_spawn_past",
    ),
    # --- #87 / PR #143: a catalog line may not join a received order; one mutant ----
    # --- per condition. rcv-2's anchor is widened with its unique neighbour because -
    # --- the bare if-line also appears in _check_catalog_targets. -------------------
    (
        "rcv-1. the line-join guard is off",
        INV,
        "    _check_lines_joining_received_orders(rows, by_id=by_id, replace_all=replace_all)",
        "    pass  # neutered",
        "cannot_join_a_received_order",
    ),
    (
        "rcv-2. kit lines are caught too",
        INV,
        '        if item_type is None or item_type is ItemType.KIT:\n            continue\n        parent = by_id["orders"].get(row.values.get("order_id"))',
        '        if item_type is None:\n            continue\n        parent = by_id["orders"].get(row.values.get("order_id"))',
        "new_kit_line_still_joins",
    ),
    (
        "rcv-3. the doomed database is consulted under replace_all",
        INV,
        "    if replace_all:\n        return",
        "    if False:\n        return",
        "restores_from_an_archive",
    ),
    (
        "rcv-4. updates are caught along with creates",
        INV,
        "        if row.action is not RowAction.CREATE:\n            continue",
        "        if row.action is RowAction.ERROR:\n            continue",
        "still_updates_by_import",
    ),
    (
        "rcv-5. pending parents are refused too",
        INV,
        "        if parent is None or parent.received_at is None:\n            continue",
        "        if parent is None:\n            continue",
        "joining_a_pending_order_stays_legal",
    ),
    (
        "rcv-6. a parent the upload itself creates is dereferenced",
        INV,
        "        if parent is None or parent.received_at is None:\n            continue",
        "        if parent.received_at is None:\n            continue",
        "created_received_order_with_a_catalog_line",
    ),
    # --- #61 / PR #149: upgrade-application withdrawal (wdr-). The kill for
    # wdr-7 is the end-state assert seeing ['withdrawn', 'withdrawn'] — no
    # StaleDataError is raised; the empty DELETE is only a SAWarning (measured
    # in the PR #149 round 1 review; the PR thread carries the correction). ---
    (
        "wdr-1. restore flag ignored (always restores)",
        UPG,
        "    if restore_stock:",
        "    if True:",
        "withdraw_without_restore_keeps_stock_spent",
    ),
    (
        "wdr-2. restore flag inverted (never restores)",
        UPG,
        "    if restore_stock:",
        "    if not restore_stock:",
        "withdraw_with_restore_returns_the_whole_quantity",
    ),
    (
        "wdr-3. restores one instead of quantity_used",
        UPG,
        "            upgrade.name, upgrade.quantity_on_hand + application.quantity_used",
        "            upgrade.name, upgrade.quantity_on_hand + 1",
        "withdraw_with_restore_returns_the_whole_quantity",
    ),
    (
        "wdr-4. pairing check off",
        UPG,
        "    if upgrade_id is not None and application.upgrade_id != upgrade_id:",
        "    if False:",
        "withdraw_under_the_wrong_upgrade_is_404",
    ),
    (
        "wdr-5. ceiling guard bypassed on restore",
        UPG,
        """        upgrade.quantity_on_hand = guard_stock_ceiling(
            upgrade.name, upgrade.quantity_on_hand + application.quantity_used
        )""",
        "        upgrade.quantity_on_hand = upgrade.quantity_on_hand + application.quantity_used",
        "withdraw_restore_past_int4_ceiling_refused",
    ),
    (
        "wdr-6. application row never deleted",
        UPG,
        "    await session.delete(application)",
        "    pass  # neutered",
        "withdraw_with_restore_returns_the_whole_quantity or line_quantity_decrease_unblocked_after_withdrawal",
    ),
    (
        "wdr-7. write gate skipped by the withdrawal",
        UPG,
        """    await acquire_write_gate(session)
    application = await session.get(UpgradeApplication, application_id)""",
        "    application = await session.get(UpgradeApplication, application_id)",
        "concurrent_double_withdraw_restores_stock_once",
    ),
    (
        "wdr-8. missing-application guard off",
        UPG,
        """    if application is None:
        raise NotFoundError(
            f"upgrade application {application_id} not found",
            code=error_codes.UPGRADE_APPLICATION_NOT_FOUND,
            params={"application_id": application_id},
        )""",
        """    if False:
        raise NotFoundError(
            f"upgrade application {application_id} not found",
            code=error_codes.UPGRADE_APPLICATION_NOT_FOUND,
            params={"application_id": application_id},
        )""",
        "withdraw_unknown_application_is_404",
    ),
    (
        "wdr-9. REST restore_stock gains a default",
        INVR,
        """    restore_stock: bool,
    session: SessionDep,
):
    \"\"\"Withdraw a recorded application""",
        """    session: SessionDep,
    restore_stock: bool = False,
):
    \"\"\"Withdraw a recorded application""",
        "withdraw_without_the_restore_choice_is_422",
    ),
    (
        "wdr-10. applications listed newest first",
        UPG,
        "        .order_by(UpgradeApplication.applied_at, UpgradeApplication.id)",
        "        .order_by(UpgradeApplication.applied_at.desc(), UpgradeApplication.id)",
        "kit_applications_listed_oldest_first",
    ),
    (
        "wdr-11. MCP get_kit stops embedding applications",
        MCP,
        "        applications = await upgrades_service.list_kit_applications(session, parsed)",
        "        applications = []",
        "get_kit_embeds_upgrade_applications",
    ),
    # --- #54 / PR #151: data-bearing migration mutants (mig-). These mutate the
    # MIGRATIONS, not the app — the harness's clean-tree check covers alembic/
    # for exactly this reason. mig-2/mig-3 kill because the target migration's
    # own CHECK creation refuses the unconverted rows (the round-2 review read
    # that as a valid semantic kill, value asserts as the backstop); a mutant
    # that orphans a bindparam kills every walk at the first step and proves
    # nothing — mig-6 inverts the WHERE instead (PR #151 body, the lesson). ---
    (
        "mig-1. received_at backfill removed",
        VERS / "20260806_6cbd8315df95_orders_received_at.py",
        '    op.execute("UPDATE orders SET received_at = order_date")',
        "    pass  # neutered",
        "received_at_backfills",
    ),
    (
        "mig-2. in_hand merge UPDATE removed",
        VERS / "20260806_9d78b6148c30_merge_in_hand_into_backlog.py",
        "    op.execute(\"UPDATE kits SET status = 'backlog' WHERE status = 'in_hand'\")",
        "    pass  # neutered",
        "in_hand_merges",
    ),
    (
        "mig-3. snapshot AUD backfill removed",
        VERS / "20260810_2b293c6fd496_neutral_reference_currency_on_order_.py",
        """    op.execute(
        "UPDATE order_items SET converted_currency_code = 'AUD' "
        "WHERE converted_price_minor IS NOT NULL"
    )""",
        "    pass  # neutered",
        "converted_snapshot",
    ),
    (
        "mig-4. tool cost loses the exponent",
        VERS / "20260811_24ee4c9024e4_tool_reference_cost_carries_its_currency.py",
        'f"SET unit_cost_reference_minor = ROUND(unit_cost_reference * {factor})::bigint, "',
        'f"SET unit_cost_reference_minor = ROUND(unit_cost_reference)::bigint, "',
        "tool_cost_scales",
    ),
    (
        "mig-5. display refusal demands both states",
        VERS / "20260821_2c97a5ced66a_display_items_catalog_type_126.py",
        "    if rows or lines:",
        "    if rows and lines:",
        "display_downgrade_refuses",
    ),
    (
        "mig-6. tool downgrade WHERE inverted (relabels foreign)",
        VERS / "20260811_24ee4c9024e4_tool_reference_cost_carries_its_currency.py",
        '"WHERE unit_cost_reference_currency = :code"',
        '"WHERE unit_cost_reference_currency != :code"',
        "tool_cost_scales",
    ),
    (
        "mig-7. snapshot downgrade keeps foreign amounts",
        VERS / "20260810_2b293c6fd496_neutral_reference_currency_on_order_.py",
        """    op.execute(
        "UPDATE order_items SET converted_price_minor = NULL "
        "WHERE converted_currency_code IS DISTINCT FROM 'AUD'"
    )""",
        "    pass  # neutered",
        "converted_snapshot",
    ),
    # --- #67 / PR #154: silent kit lines (o67-). An id-bearing kit line may
    # omit `kit`; what a client cannot state it cannot revert. ---
    (
        "o67-1. schema override loses the id branch",
        SCH,
        "            if self.kit is None and self.id is None:",
        "            if self.kit is None:",
        "kit_omitted or update_order_kit_omitted",
    ),
    (
        "o67-2. service forgets details can be absent",
        ORD,
        "        if details is not None and line_kits:",
        "        if line_kits:",
        "kit_omitted_line_edit",
    ),
    (
        "o67-3. clone gate off",
        ORD,
        "            if details is None:",
        "            if False:",
        "kit_omitted_quantity_growth",
    ),
    (
        "o67-4. clone drops the scale",
        ORD,
        "                    scale=reference.scale,",
        "                    scale=None,",
        "kit_omitted_quantity_growth",
    ),
    (
        "o67-5. clone always spawns pre_ordered",
        ORD,
        "                    else KitStatus.ORDERED,",
        "                    else KitStatus.PRE_ORDERED,",
        "kit_omitted_quantity_growth",
    ),
    # --- #63 / PR #156: the dangling-reversal tolerance (d63-). delete_order
    # alone may shrug at a missing stored reference; everything else refuses. ---
    (
        "d63-1. delete_order stays strict (fix off)",
        ORD,
        "        await _undo_line_dispatch(session, item, received, missing_ok=True)",
        "        await _undo_line_dispatch(session, item, received)",
        "undo_skips_a_dangling",
    ),
    (
        "d63-2. everything tolerant",
        ORD,
        "        if missing_ok:",
        "        if True:",
        "receiving_a_dangling or retargeting_a_dangling",
    ),
    (
        "d63-3. the skip forgets to log",
        ORD,
        """            logger.warning(
                "skipping stock reversal for a dangling %s reference %s (%+d): the "
                "row is gone and its stock went with it — undoing the order entry "
                "wholesale (#63)",
                item_type,
                ref_id,
                delta,
            )
            return""",
        "            return",
        "undo_skips_a_dangling",
    ),
    (
        "d63-4. dispatch drops the passthrough",
        ORD,
        "            session, item.item_type, item.catalog_ref_id, -item.quantity, missing_ok=missing_ok",
        "            session, item.item_type, item.catalog_ref_id, -item.quantity",
        "undo_skips_a_dangling",
    ),
    (
        "d63-5. line removal turns tolerant",
        ORD,
        """    await _undo_line_dispatch(session, item, received)
    await session.delete(item)""",
        """    await _undo_line_dispatch(session, item, received, missing_ok=True)
    await session.delete(item)""",
        "removing_a_dangling",
    ),
    # --- #23 / PR #159: the instance-settings singleton (stg-). stg-1..18 rode
    # the branch; stg-19..23 are the round-1 remedies, one per fixed site (the
    # shared ASCII currency shape, the Intl-true locale shapes, variant sorting).
    # stg-5's kill is the pg_blocking_pids holder->updater edge — a decoy
    # advisory waiter parked elsewhere must NOT satisfy it (round 1 proved the
    # count-based observation could be); stg-17 mutates a MIGRATION's seed, under
    # the same clean-tree cover as the mig- set. ---
    (
        "stg-1. replace_all stops matching the singleton",
        IMP,
        "                if (not replace_all or spec.singleton) and row.action is not RowAction.ERROR:",
        "                if not replace_all and row.action is not RowAction.ERROR:",
        "replace_all_updates_the_settings or replace_all_without_the_sheet",
    ),
    (
        "stg-2. singleton rows take the replace_all CREATE path",
        IMP,
        "                if spec.singleton:\n",
        "                if False:\n",
        "replace_all_updates_the_settings or replace_all_without_the_sheet",
    ),
    (
        "stg-3. replace_all counts the singleton among its deletions",
        IMP,
        "                key: len(rows)\n                for key, rows in self.existing.items()\n                if rows and not SPEC_BY_KEY[key].singleton",
        "                key: len(rows)\n                for key, rows in self.existing.items()\n                if rows",
        "replace_all_updates_the_settings",
    ),
    (
        "stg-4. replace_all truncates the settings row",
        IMP,
        '    "upgrade_applications, retailers, orders, order_items"\n)',
        '    "upgrade_applications, retailers, orders, order_items, instance_settings"\n)',
        "replace_all_without_the_sheet_leaves_settings_alone or replace_all_updates_the_settings",
    ),
    (
        "stg-5. settings update skips the write gate",
        SET,
        "    await acquire_write_gate(session)\n    row = await session.get(InstanceSettings, SINGLETON_ROW_ID, with_for_update=True)",
        "    row = await session.get(InstanceSettings, SINGLETON_ROW_ID, with_for_update=True)",
        "waits_its_turn_on_the_write_gate",
    ),
    (
        "stg-6. explicit null slides through to the row",
        SET,
        "        if value is None:",
        "        if False:",
        "explicit_null_is_refused",
    ),
    (
        "stg-7. PATCH values skip the canonicalisers",
        SET,
        "        validator = _VALIDATORS.get(field)",
        "        validator = None",
        "values_are_canonicalised or invalid_values_are_refused",
    ),
    (
        "stg-8. any well-formed tag is an interface language",
        SET,
        "    if value not in SUPPORTED_INTERFACE_LANGUAGES:",
        "    if False:",
        "invalid_values_are_refused or invalid_cells_are_row_errors",
    ),
    (
        "stg-9. time zones stop being membership-checked",
        SET,
        "    if found is None:",
        "    if False:",
        "invalid_values_are_refused or invalid_cells_are_row_errors",
    ),
    (
        "stg-10. meta answers from a constant, not the row",
        META,
        "        reference_currency=await instance_settings.reference_currency(session),",
        '        reference_currency="AUD",',
        "meta_reads_the_row",
    ),
    (
        "stg-11. a new snapshot's default currency is hardcoded",
        ORD,
        "    return line.converted_price_minor, (line.converted_currency_code or reference)",
        '    return line.converted_price_minor, (line.converted_currency_code or "AUD")',
        "new_conversion_snapshots_default",
    ),
    (
        "stg-12. the edit path's snapshot fallback is hardcoded",
        ORD,
        "        line.converted_currency_code or item.converted_currency_code or reference",
        '        line.converted_currency_code or item.converted_currency_code or "AUD"',
        "edit_that_adds_a_snapshot",
    ),
    (
        "stg-13. the MCP order default is hardcoded",
        MCP,
        "            currency_code=currency_code or await settings_service.reference_currency(session),",
        '            currency_code=currency_code or "AUD",',
        "omitted_currency_reads_the_settings_row",
    ),
    (
        "stg-14. the importer's blank-currency fill is hardcoded",
        IMP,
        "        values[currency_column] = reference_currency",
        '        values[currency_column] = "AUD"',
        "stales_the_hash or stamps_the_instance_currency",
    ),
    (
        "stg-15. the starter sheet's blank-currency fill is hardcoded",
        STARTER,
        '        currency = (row.get("currency") or "").strip().upper() or reference_currency',
        '        currency = (row.get("currency") or "").strip().upper() or "AUD"',
        "starter_sheet_priced_without_a_currency",
    ),
    (
        "stg-16. the spec forgets the table is a singleton",
        SPEC,
        "    singleton=True,",
        "    singleton=False,",
        "replace_all_updates_the_settings or every_column_the_database_requires",
    ),
    (
        "stg-17. the migration seed ignores the configured currency",
        VERS / "20260827_f9979ec7b9cb_instance_settings_singleton_23.py",
        "        ).bindparams(reference_currency=get_settings().reference_currency)",
        '        ).bindparams(reference_currency="AUD")',
        "instance_settings_seeds_one_env_configured_row",
    ),
    (
        "stg-18. the export loads no settings row",
        EXP,
        '        "instance_settings": list((await session.scalars(select(InstanceSettings))).all()),',
        '        "instance_settings": [],',
        "the_archive_exports_the_settings_row",
    ),
    (
        "stg-19. parse_currency judges letters with isalpha again (round 1, P2)",
        SPEC,
        "    return require_currency_code(value)",
        "    value = value.upper()\n"
        "    if len(value) != 3 or not value.isalpha():\n"
        "        raise ValueError(f\"'{raw}' is not a 3-letter ISO 4217 currency code\")\n"
        "    return value",
        "unicode_letter_code_is_refused_on_every_currency_column",
    ),
    (
        "stg-20. repeated variants slide through (round 1, P3)",
        SET,
        "        if len(set(variants)) != len(variants):",
        "        if False:",
        "invalid_values_are_refused or locale_shapes",
    ),
    (
        "stg-21. four-letter language subtags come back (round 1, P3)",
        SET,
        '    r"^(?P<language>[A-Za-z]{2,3}|[A-Za-z]{5,8})"',
        '    r"^(?P<language>[A-Za-z]{2,8})"',
        "invalid_values_are_refused or locale_shapes",
    ),
    (
        "stg-22. the PATCH currency entry stops shape-testing (round 1, P2)",
        SET,
        '    "reference_currency": require_currency_code,',
        '    "reference_currency": lambda raw: raw.strip().upper(),',
        "invalid_values_are_refused",
    ),
    (
        "stg-23. variants stored in input order, not UTS 35 order (round 1)",
        SET,
        "        parts.extend(sorted(variants))",
        "        parts.extend(variants)",
        "values_are_canonicalised or locale_shapes",
    ),
    # --- #25 / PR #169: the error envelope (env-). env-1..7 rode the branch;
    # env-8/env-9 are the round-1 remedies (the parser-stage 400 handler and
    # the raise-site params audit — env-9 is the exact mutant Codex ran and
    # watched survive before the audit existed). Kills live in
    # tests/test_error_envelope.py; the -k names the assertion that names
    # the defect. ---
    (
        "env-1. a site's code names the wrong condition",
        KITS,
        'kit = await session.get(Kit, kit_id)\n    if kit is None:\n        raise NotFoundError(\n            f"kit {kit_id} not found",\n            code=error_codes.KIT_NOT_FOUND,',
        'kit = await session.get(Kit, kit_id)\n    if kit is None:\n        raise NotFoundError(\n            f"kit {kit_id} not found",\n            code=error_codes.ORDER_NOT_FOUND,',
        "404_carries_the_full_envelope",
    ),
    (
        "env-2. the handler drops the code key",
        MAIN,
        'content={"detail": exc.detail, "code": exc.code, "params": jsonable_encoder(exc.params)},',
        'content={"detail": exc.detail, "params": jsonable_encoder(exc.params)},',
        "404_carries_the_full_envelope",
    ),
    (
        "env-3. request validation mislabels itself",
        MAIN,
        '"code": error_codes.REQUEST_VALIDATION,',
        '"code": "request.invalid",',
        "422_from_request_validation",
    ),
    (
        "env-4. the catalog stock writer drops its params",
        CAT,
        'code=error_codes.STOCK_INSUFFICIENT,\n                params={\n                    "name": row.name,\n                    "on_hand": row.quantity_on_hand,\n                    "requested": -delta,\n                },',
        "code=error_codes.STOCK_INSUFFICIENT,",
        "409_with_params_names_the_stock or every_raise_site_supplies",
    ),
    (
        "env-5. DomainError swallows params",
        EXC,
        "self.params: dict[str, object] = dict(params or {})",
        "self.params: dict[str, object] = {}",
        "404_carries_the_full_envelope or 409_with_params_names_the_stock",
    ),
    (
        "env-6. MCP leaks the code into the sentence",
        MCP,
        "raise ToolError(str(exc)) from exc",
        'raise ToolError(f"{exc.code}: {exc}") from exc',
        "tool_error_is_the_bare_sentence",
    ),
    (
        "env-7. a registry constant drifts from the fixture",
        EC,
        'KIT_NOT_FOUND = "kit.not_found"',
        'KIT_NOT_FOUND = "kit.missing"',
        "fixture_and_module_hold_the_same_codes or 404_carries_the_full_envelope",
    ),
    (
        "env-8. parser-stage 400s lose the envelope",
        MAIN,
        "    if exc.status_code == 400:",
        "    if False:",
        "multipart_with_no_boundary or unreadable_multipart_body",
    ),
    (
        "env-9. a shared-code writer drops its declared params",
        ORD,
        'code=error_codes.STOCK_INSUFFICIENT,\n            params={"name": row.name, "on_hand": row.quantity_on_hand, "requested": -delta},',
        "code=error_codes.STOCK_INSUFFICIENT,",
        "every_raise_site_supplies_its_codes_declared_params",
    ),
    # --- #26: the import-preview diagnostics (queued on PR #171, measured 5/5
    # --- killed there with a scratch runner; anchors re-checked at fold-in) --------
    (
        "nd-1. refuse() records the diagnostic but not the ERROR action",
        IMP,
        "        self.action = RowAction.ERROR\n        self.errors.append(diagnostic)",
        "        self.errors.append(diagnostic)",
        "test_a_borrowed_code_is_the_live_writers_own",
    ),
    (
        "nd-2. the blocked apply drops the structured diagnostics from params",
        IMP,
        '            params={\n                "count": len(plan.blocking_errors),\n'
        '                "diagnostics": [\n'
        '                    diagnostic.model_dump(mode="json") for diagnostic in plan.blocking_errors\n'
        "                ],\n            },",
        '            params={"count": len(plan.blocking_errors)},',
        "test_a_blocked_apply_is_a_structured_conflict",
    ),
    (
        "nd-3. the fingerprint starts reading diagnostic wording",
        IMP,
        '                        "changes": [\n'
        "                            [c.field, c.before, canon(row.values.get(c.field))] for c in row.changes\n"
        "                        ],",
        '                        "changes": [\n'
        "                            [c.field, c.before, canon(row.values.get(c.field))] for c in row.changes\n"
        "                        ],\n"
        '                        "diagnostics": [d.detail for d in [*row.errors, *row.messages]],',
        "test_rewording_every_diagnostic_leaves_the_plan_hash_alone",
    ),
    (
        "nd-4. the stray-column warning stops deduplicating",
        IMP,
        "                if diagnostic not in self.warnings:\n"
        "                    self.warnings.append(diagnostic)",
        "                self.warnings.append(diagnostic)",
        "test_plan_surfaces_carry_diagnostics_and_the_stray_column_dedups_by_value",
    ),
    (
        "nd-5. the starter-sheet problem loses its source row",
        STARTER,
        '        params={"row": source_row, **exc.params},',
        "        params={**exc.params},",
        "test_a_starter_row_problem_borrows_the_code_and_names_the_row",
    ),
    # --- #114: naive CSV datetimes in the instance zone (queued on PR #173,
    # --- measured 3/3 killed there with a scratch runner; anchors re-checked
    # --- at fold-in) -----------------------------------------------------------
    (
        "tz-1. the planner attaches UTC instead of the instance zone",
        IMP,
        "                    value = value.replace(tzinfo=self.naive_zone)",
        "                    value = value.replace(tzinfo=UTC)",
        "test_a_naive_date_reads_as_midnight_in_the_instance_zone",
    ),
    (
        "tz-2. the parser resumes folding naive input to UTC",
        SPEC,
        "    # nothing downstream of parsing sees a naive value. An explicit offset in\n"
        "    # the cell always wins — it is never reinterpreted.\n"
        "    return parsed",
        "    # nothing downstream of parsing sees a naive value. An explicit offset in\n"
        "    # the cell always wins — it is never reinterpreted.\n"
        "    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)",
        "test_a_naive_date_reads_as_midnight_in_the_instance_zone",
    ),
    (
        "tz-3. the guard stops sparing explicit offsets",
        IMP,
        "                if isinstance(value, datetime) and value.tzinfo is None:",
        "                if isinstance(value, datetime):",
        "test_an_explicit_offset_is_never_reinterpreted",
    ),
    # --- #178: the order-ambiguity code split and the exact-params diagnostic
    # --- audit (queued on PR #180, measured 5/5 killed there by hand, plus the
    # --- two review-round bridge probes; anchors re-checked at fold-in). oma-2
    # --- mutates the shared registry FIXTURE and oma-4/5 the audit itself —
    # --- the clean-tree check covers both paths since this fold-in. -----------
    (
        "oma-1. order ambiguity wears the generic code",
        IMP,
        "code=error_codes.IMPORT_ORDER_MATCH_AMBIGUOUS,",
        "code=error_codes.IMPORT_MATCH_AMBIGUOUS,",
        "test_order_ambiguity_by_retailer_and_order_number",
    ),
    (
        "oma-2. registry declaration loses matched_by",
        FIX,
        '    "import.order_match_ambiguous": {\n'
        '      "params": [\n'
        '        "count",\n'
        '        "matched_by"\n'
        "      ]\n"
        "    },",
        '    "import.order_match_ambiguous": {\n'
        '      "params": [\n'
        '        "count"\n'
        "      ]\n"
        "    },",
        "test_import_diagnostic_sites_send_exactly_their_declared_params",
    ),
    (
        "oma-3. order ambiguity drops matched_by",
        IMP,
        'params={"count": len(matches), "matched_by": label},',
        'params={"count": len(matches)},',
        "test_order_ambiguity_by_date_and_line_fingerprint",
    ),
    (
        "oma-4. audit blind to undeclared params",
        TEE,
        "        extra = params_keys - declared",
        "        extra = set()",
        "test_the_diagnostic_audit_detects_each_violation_class",
    ),
    (
        "oma-5. audit blind to omitted params",
        TEE,
        "        missing = declared - params_keys",
        "        missing = set()",
        "test_the_diagnostic_audit_detects_each_violation_class",
    ),
    # The two #180 review-round probes (round-1 P3-1's negative controls),
    # promoted to tracked cases: a raise-side extra on a borrowed code must die
    # on the bridge runtime matrix, which is the only control on the two
    # audit-exempt bridges.
    (
        "oma-6. borrowed large-quantity raise grows an undeclared extra",
        ORD,
        '            params={"quantity": quantity, "maximum": MAX_LINE_QUANTITY},',
        '            params={"quantity": quantity, "maximum": MAX_LINE_QUANTITY, "unrendered": "probe"},',
        "test_the_borrowed_bridge_matrix_covers_the_large_quantity_and_fanout_codes"
        " or test_a_starter_row_problem_borrows_the_code_and_names_the_row",
    ),
    (
        "oma-7. borrowed fan-out raise grows an undeclared extra",
        ORD,
        '            params={"total": total, "maximum": MAX_TOTAL_FANOUT},',
        '            params={"total": total, "maximum": MAX_TOTAL_FANOUT, "unrendered": "probe"},',
        "test_the_borrowed_bridge_matrix_covers_the_large_quantity_and_fanout_codes",
    ),
    # --- #186 (M6-1): the ingress guard — queued on PR #196 as `ing-` (19 tuples at the
    # --- reviewed head plus 7 for the Codex round's three P3s, all killed there by
    # --- a scratch runner), relabelled `ingr-` here because `-k ing-` substring-
    # --- matches wdr-8's "missing-application"; anchors re-checked at fold-in (ingr-15's original
    # --- anchor, the bare-`*` check, was replaced by the round-1 grammar, so it
    # --- now removes the validation call outright; ingr-22 restores the old raw
    # --- check on the same site). ingr-25/26 are the first cases against a SHELL
    # --- file — the clean-tree check covers ENVSH since this fold-in. -----------
    (
        "ingr-1. origin rule skips POST",
        ING,
        'SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})',
        'SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "POST"})',
        "hostile_origin",
    ),
    (
        "ingr-2. Host check dropped",
        ING,
        "        if not self.policy.host_allowed(host, server[0] if server else None):",
        "        if False and not self.policy.host_allowed(host, server[0] if server else None):",
        "hostile_host",
    ),
    (
        "ingr-3. every peer is internal",
        ING,
        "        return ip_address(client[0]).is_loopback",
        "        return True or ip_address(client[0]).is_loopback",
        "readyz",
    ),
    (
        "ingr-4. FastMCP guard switched off",
        MAIN,
        "        host_origin_protection=True,",
        "        host_origin_protection=False,",
        "mcp_guard or mcp_child",
    ),
    (
        "ingr-5. MCP child keeps slash redirects",
        MAIN,
        "    mcp_app.router.redirect_slashes = False\n",
        "    mcp_app.router.redirect_slashes = True\n",
        "never_redirects",
    ),
    (
        "ingr-6. parent keeps slash redirects",
        MAIN,
        "        redirect_slashes=False,",
        "        redirect_slashes=True,",
        "non_canonical",
    ),
    (
        "ingr-7. loopback-to-loopback origin rule dropped",
        ING,
        "        if is_loopback_host(origin_host(origin)) and is_loopback_host(host):\n            return True",
        "        if False:\n            return True",
        "loopback_origin",
    ),
    (
        "ingr-8. same-origin equality dropped",
        ING,
        '        return normalized == normalize_origin(f"{scheme}://{host}")',
        "        return False",
        "same_origin",
    ),
    (
        "ingr-9. canonical origin not listed",
        ING,
        "        if canonical_origin is not None:\n            allowed_origins.append(canonical_origin)",
        "        if False:\n            allowed_origins.append(canonical_origin)",
        "canonical_origin",
    ),
    (
        "ingr-10. WEB_BIND not added",
        ING,
        "            extra_hosts.append(bind)",
        "            pass",
        "web_bind or policy_derivation",
    ),
    (
        "ingr-11. forwarded trust ignored",
        ING,
        "        if not self.is_trusted_proxy(peer):\n            return peer",
        "        if False:\n            return peer",
        "forwarded_client",
    ),
    (
        "ingr-12. Referer fallback removed",
        ING,
        "                if referer is not None:\n                    origin = origin_of_referer(referer)",
        "                if False:\n                    origin = origin_of_referer(referer)",
        "referer",
    ),
    (
        "ingr-13. unspecified bind treated as a name",
        HOSTS,
        "        return ip_address(host).is_unspecified\n    except ValueError:\n        return False",
        "        return False and ip_address(host).is_unspecified\n    except ValueError:\n        return False",
        "unspecified or policy_derivation or web_bind",
    ),
    (
        "ingr-14. 421 names the wrong setting",
        ING,
        "                error_codes.INGRESS_HOST_NOT_ALLOWED,\n                HOST_SETTING,",
        "                error_codes.INGRESS_HOST_NOT_ALLOWED,\n                ORIGIN_SETTING,",
        "hostile_host",
    ),
    (
        "ingr-15. ALLOWED_HOSTS validation removed",
        CFG,
        '            validate_host_pattern(entry, setting="ALLOWED_HOSTS", allow_wildcard=True)',
        "            pass",
        "wildcard or port_qualified",
    ),
    (
        "ingr-16. forwarded address overwrites the raw peer",
        ING,
        '            scope.setdefault("state", {})[CLIENT_ADDRESS_KEY] = self.policy.resolve_client_address(\n                peer, forwarded\n            )',
        '            resolved = self.policy.resolve_client_address(peer, forwarded)\n            scope.setdefault("state", {})[CLIENT_ADDRESS_KEY] = resolved\n            if resolved:\n                scope["client"] = (resolved, 0)',
        "raw_peer or forge",
    ),
    (
        "ingr-17. null Origin admitted",
        ING,
        "        normalized = normalize_origin(origin)\n        if any(",
        '        normalized = normalize_origin(origin)\n        if normalized == "null":\n            return True\n        if any(',
        "null_origin",
    ),
    (
        "ingr-18. host match ignores the list",
        ING,
        "    return any(fnmatchcase(host, normalize_host(pattern)) for pattern in patterns)",
        "    return True",
        "hostile_host or lan_name",
    ),
    (
        "ingr-19. PUBLIC_BASE_URL host not allowed",
        ING,
        '            extra_hosts.append(normalize_host(parsed.hostname or ""))',
        "            pass",
        "public_base_url or policy_derivation",
    ),
    (
        "ingr-20. terminal DNS dot kept on the app side",
        HOSTS,
        '    return host.removesuffix(".")',
        "    return host",
        "terminal_dot or dotted or server_names_equal",
    ),
    (
        "ingr-21. loopback class excluded from binds again",
        ING,
        "        if not is_unspecified_host(bind) and bind not in _LOOPBACK_NORMALIZED:",
        "        if not is_unspecified_host(bind) and not is_loopback_host(bind):",
        "alternate_loopback or explicit_bind or server_names_equal",
    ),
    (
        "ingr-22. ALLOWED_HOSTS judged on the raw spelling again",
        CFG,
        '            validate_host_pattern(entry, setting="ALLOWED_HOSTS", allow_wildcard=True)',
        '            if entry.strip("*") == "":\n                raise ValueError("ALLOWED_HOSTS bare *")',
        "wildcard_equivalents or port_qualified",
    ),
    (
        "ingr-23. PUBLIC_BASE_URL host unvalidated",
        CFG,
        '        validate_host_pattern(parsed.hostname, setting="PUBLIC_BASE_URL", allow_wildcard=False)',
        "        pass",
        "every_host_producing",
    ),
    (
        "ingr-24. dotted names withheld from FastMCP",
        ING,
        '                names.append(f"{host}.")',
        "                pass",
        "dotted_name_passes_on_mcp or policy_derivation",
    ),
    (
        "ingr-25. generator keeps the terminal dot (sh)",
        ENVSH,
        '    name="${name%.}"                                      # one terminal DNS dot, as the API\n',
        "",
        "server_names_equal or generator_drops",
    ),
    (
        "ingr-26. generator drops loopback binds (sh)",
        ENVSH,
        '    ""|0.0.0.0|::|"[::]") ;;                              # binds everything, names nothing',
        '    ""|0.0.0.0|::|"[::]"|127.*) ;;',
        "server_names_equal",
    ),
    # --- #187 / PR #198 (M6-2): the auth foundation — queued on the PR as `auth-` --
    # --- (15 tuples at round 2 plus 8 at round 3, all killed there by hand); auth-5
    # --- was retired at round 3 when `response_profile_for` was removed — auth-16 is
    # --- its successor, so the numbering keeps the gap. Anchors re-checked at fold-in
    # --- against `6604658`: none had moved. auth-24 onward are the round-1 set the PR
    # --- body queued by name only — the principal algebra, the dependency's 401/403
    # --- branches, the classifications, `plan_requires_admin`, the owner seed, the
    # --- tool scope map, the generated nginx rejections — written and measured at
    # --- fold-in. Every behavioural kill runs against `create_app(authorization=
    # --- True)`: the shipped app is unenforced until #188. auth-39/40 mutate the auth
    # --- MIGRATION under the mig- set's clean-tree cover. ----------------------------
    (
        "auth-1. stamp only when no header is present (the setdefault behaviour)",
        DEP,
        "    value = final_cache_control(profile, existing)\n    if value is None:\n        return\n",
        "    value = final_cache_control(profile, existing)\n    if value is None or existing:\n        return\n",
        "replaces_every_handler or carries_no_store_over",
    ),
    (
        "auth-2. only a lowercase cache-control key is removed",
        DEP,
        '    message["headers"] = [(k, v) for k, v in raw if k.lower() != _CACHE_CONTROL] + [',
        '    message["headers"] = [(k, v) for k, v in raw if k != _CACHE_CONTROL] + [',
        "capitalised",
    ),
    (
        "auth-3. nothing kept beside no-store",
        DEP,
        'KEPT_BESIDE_NO_STORE = frozenset({"no-transform"})',
        "KEPT_BESIDE_NO_STORE = frozenset()",
        "replaces_every_handler or carries_no_store_over",
    ),
    (
        "auth-4. a declared cache directive is dropped",
        DEP,
        "    if not profile.no_store:\n        return required\n",
        "    if not profile.no_store:\n        return None\n",
        "declared_cache_directive",
    ),
    (
        "auth-6. dispatch-entry conflict dropped",
        REG,
        '                self.conflicts.append(f"{label} shares dispatch entry {pattern} with {other}")',
        "                pass",
        "one_dispatch_entry or renamed_path_parameter or wildcard_route",
    ),
    (
        "auth-7. dispatch pattern keeps parameter names",
        REG,
        '    return _PATH_PARAMETER.sub("{}", path)',
        "    return path",
        "renamed_path_parameter",
    ),
    (
        "auth-8. shared-endpoint conflict dropped",
        REG,
        '            self.conflicts.append(f"{label} shares its endpoint with {self._by_endpoint[endpoint]}")',
        "            pass",
        "one_endpoint_on_two_routes",
    ),
    (
        "auth-9. an unknown route type is skipped",
        REG,
        '            raise UndeclaredRouteError(\n                "route policy registry cannot enumerate a "',
        '            continue\n            raise UndeclaredRouteError(\n                "route policy registry cannot enumerate a "',
        "unrecognised_route_type",
    ),
    (
        "auth-10. a nested mount is not descended",
        REG,
        "            sub_routes = route.routes\n            if sub_routes:",
        "            sub_routes = route.routes if not mounted else []\n            if sub_routes:",
        "added_under_the_mount",
    ),
    (
        "auth-11. every mounted route declared as the transport",
        REG,
        '    if route.path == "/mcp/":\n        return MCP_TRANSPORT_POLICY',
        "    if True:\n        return MCP_TRANSPORT_POLICY",
        "added_under_the_mount or bare_asgi_mount",
    ),
    (
        "auth-12. transport declares PUT",
        REG,
        '    frozenset({"GET", "POST", "DELETE"}),\n    _NO_STORE,\n    spellings=frozenset({"/mcp/", "/mcp"}),',
        '    frozenset({"GET", "POST", "DELETE", "PUT"}),\n    _NO_STORE,\n    spellings=frozenset({"/mcp/", "/mcp"}),',
        "accepts_exactly_the_declared_methods",
    ),
    (
        "auth-13. no_store beside cache allowed",
        REG,
        "        if self.no_store and self.cache is not None:\n            raise ValueError(",
        "        if False:\n            raise ValueError(",
        "cannot_be_no_store_and_cacheable",
    ),
    (
        "auth-14. /healthz gains POST",
        MAIN,
        '    app.add_api_route("/healthz", healthz, methods=["GET"], include_in_schema=False)',
        '    app.add_api_route("/healthz", healthz, methods=["GET", "POST"], include_in_schema=False)',
        "rest_surface_matches_the_snapshot or 405_exactly",
    ),
    (
        "auth-15. no-store becomes no-cache",
        REG,
        '        if self.no_store:\n            return "no-store"',
        '        if self.no_store:\n            return "no-cache"',
        "replaces_every_handler or status_axis",
    ),
    (
        "auth-16. mounted routes never bound",
        DEP,
        "    for mounted in index.mounted_routes:\n        policy = index.mounted_by_endpoint.get(mounted.endpoint)",
        "    for mounted in ():\n        policy = index.mounted_by_endpoint.get(mounted.endpoint)",
        "carries_no_store_over or mounted_route_is_bound or refuses_undeclared_verbs",
    ),
    (
        "auth-17. the binding does not stamp",
        DEP,
        '            if message["type"] == "http.response.start":\n                _stamp_cache_control(message, self.policy.response)\n            await send(message)\n\n        if self.policy.methods',
        "            if False:\n                _stamp_cache_control(message, self.policy.response)\n            await send(message)\n\n        if self.policy.methods",
        "replaces_every_handler or carries_no_store_over",
    ),
    (
        "auth-18. the binding's verb gate removed",
        DEP,
        '        if self.policy.methods and scope["method"] not in self.policy.methods:',
        '        if False and scope["method"] not in self.policy.methods:',
        "refuses_undeclared_verbs or accepts_exactly_the_declared_methods",
    ),
    (
        "auth-19. the refusal message drifts from the SDK's",
        DEP,
        'error=ErrorData(code=INVALID_REQUEST, message="Method Not Allowed"),',
        'error=ErrorData(code=INVALID_REQUEST, message="Method not allowed"),',
        "refusal_is_the_sdk_protocol_error",
    ),
    (
        "auth-20. Allow sorted instead of the SDK's order",
        DEP,
        '    return ", ".join(ordered + sorted(declared - set(_METHOD_ORDER)))',
        '    return ", ".join(sorted(declared))',
        "refusal_is_the_sdk_protocol_error or refuses_undeclared_verbs",
    ),
    (
        "auth-21. the profile middleware never added",
        MAIN,
        "        bind_route_policies(app, route_index)\n        app.add_middleware(ResponseProfileMiddleware, index=route_index)\n\n    app.add_exception_handler",
        "        bind_route_policies(app, route_index)\n\n    app.add_exception_handler",
        "middleware_is_innermost or no_store_on_a_collection_read",
    ),
    # auth-22 MOVES the add_middleware call to the tail of create_app — after the
    # two ingress guards, so the profile middleware lands outermost. The PR-body
    # tuple only appended a second copy there and left the inner one in place, and
    # that survived at fold-in (the inner copy still stamps; the position pin still
    # holds): the round-3 hand run had made two edits. One anchor now spans both
    # sites, so the harness's single replacement is the fault that was measured.
    (
        "auth-22. the profile middleware added last (outermost)",
        MAIN,
        "        app.add_middleware(ResponseProfileMiddleware, index=route_index)\n\n"
        "    app.add_exception_handler(DomainError, domain_error_handler)\n"
        "    app.add_exception_handler(StarletteHTTPException, http_exception_envelope)\n"
        "    app.add_exception_handler(RequestValidationError, request_validation_handler)\n\n"
        "    # Outermost last: the guard answers a hostile Host before anything else\n"
        "    # runs, and the forwarded-client resolver sees only requests that passed it.\n"
        "    app.add_middleware(ForwardedClientMiddleware, policy=policy)\n"
        "    app.add_middleware(HostOriginGuardMiddleware, policy=policy)\n"
        "    return app",
        "\n    app.add_exception_handler(DomainError, domain_error_handler)\n"
        "    app.add_exception_handler(StarletteHTTPException, http_exception_envelope)\n"
        "    app.add_exception_handler(RequestValidationError, request_validation_handler)\n\n"
        "    app.add_middleware(ForwardedClientMiddleware, policy=policy)\n"
        "    app.add_middleware(HostOriginGuardMiddleware, policy=policy)\n"
        "    if authorization:\n"
        "        app.add_middleware(ResponseProfileMiddleware, index=route_index)\n"
        "    return app",
        "middleware_is_innermost",
    ),
    (
        "auth-23. transport declares CONNECT",
        REG,
        '    frozenset({"GET", "POST", "DELETE"}),\n    _NO_STORE,\n    spellings=frozenset({"/mcp/", "/mcp"}),',
        '    frozenset({"GET", "POST", "DELETE", "CONNECT"}),\n    _NO_STORE,\n    spellings=frozenset({"/mcp/", "/mcp"}),',
        "accepts_exactly_the_declared_methods or refuses_undeclared_verbs",
    ),
    # --- the round-1 set, written at fold-in ------------------------------------------
    (
        "auth-24. write no longer implies read",
        PRIN,
        "        if scope is Scope.READ and Scope.WRITE in self.scopes:\n            return True",
        "        if False:\n            return True",
        "write_only_scope_set_reads_through_the_implication",
    ),
    (
        "auth-25. admin implies read",
        PRIN,
        "        if scope is Scope.READ and Scope.WRITE in self.scopes:",
        "        if scope is Scope.READ and (Scope.WRITE in self.scopes or Scope.ADMIN in self.scopes):",
        "write_implies_read_admin_implies_nothing or write_only_scope_set_reads_through_the_implication",
    ),
    (
        "auth-26. the owner drops instance:admin",
        PRIN,
        "        scopes=frozenset({Scope.READ, Scope.WRITE, Scope.ADMIN}),",
        "        scopes=frozenset({Scope.READ, Scope.WRITE}),",
        "settings_patch_is_admin_only or permits_matches_the_scope_algebra",
    ),
    # The bare scopes line also appears in `mcp()`; the return line makes it the pat
    # factory's.
    (
        "auth-27. a write token gains instance:admin",
        PRIN,
        "    scopes = {Scope.READ, Scope.WRITE} if write else {Scope.READ}\n    return Principal(kind=PrincipalKind.PAT,",
        "    scopes = {Scope.READ, Scope.WRITE, Scope.ADMIN} if write else {Scope.READ}\n    return Principal(kind=PrincipalKind.PAT,",
        "settings_patch_is_admin_only or permits_matches_the_scope_algebra",
    ),
    (
        "auth-28. anon on a scoped route is 403, not 401",
        DEP,
        "    if principal.kind is PrincipalKind.ANON:\n        raise UnauthenticatedError(_UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED)\n    if not principal.has_scope(scope):",
        "    if not principal.has_scope(scope):",
        "reads_need_a_read_scope or anonymous_read_is_the_unauthenticated_envelope",
    ),
    (
        "auth-29. the scope check dropped",
        DEP,
        "    if not principal.has_scope(scope):\n        raise ForbiddenError(_FORBIDDEN, code=error_codes.AUTH_FORBIDDEN)\n    return principal",
        "    return principal",
        "a_write_needs_write_scope or settings_patch_is_admin_only",
    ),
    (
        "auth-30. the anonymous family enforced",
        DEP,
        "    if credential == CredentialPolicy.ANONYMOUS:\n        return principal\n    if credential == CredentialPolicy.INTERNAL:",
        "    if credential == CredentialPolicy.INTERNAL:",
        "liveness_is_anonymous",
    ),
    (
        "auth-31. readiness no longer passed to its own peer guard",
        DEP,
        "        # Readiness self-guards on the raw peer; let it answer its own 404.\n        return principal",
        "        pass",
        "readiness_answers_the_loopback_peer",
    ),
    (
        "auth-32. PATCH /settings classified write",
        REG,
        "        credential = CredentialPolicy.READ if is_safe else CredentialPolicy.ADMIN",
        "        credential = CredentialPolicy.READ if is_safe else CredentialPolicy.WRITE",
        "settings_patch_is_admin_only or sensitive_routes_are_classified_as_intended",
    ),
    # The route self-guards on the peer, so only the classification pin can see
    # these two today; #188's flip makes the docs one behavioural.
    (
        "auth-33. readiness declared anonymous",
        REG,
        '            10, CredentialPolicy.INTERNAL, route.methods, spellings=frozenset({"internal"})',
        '            10, CredentialPolicy.ANONYMOUS, route.methods, spellings=frozenset({"internal"})',
        "sensitive_routes_are_classified_as_intended",
    ),
    (
        "auth-34. schema and docs declared anonymous",
        REG,
        "            11, CredentialPolicy.READ, route.methods, _NO_STORE, spellings=frozenset({root})",
        "            11, CredentialPolicy.ANONYMOUS, route.methods, _NO_STORE, spellings=frozenset({root})",
        "sensitive_routes_are_classified_as_intended",
    ),
    (
        "auth-35. a mutating tool declared read",
        REG,
        '    "create_kit": Scope.WRITE,',
        '    "create_kit": Scope.READ,',
        "every_mutating_tool_holds_write",
    ),
    (
        "auth-36. replace_all no longer needs admin",
        IMP,
        "    if plan.mode is ImportMode.REPLACE_ALL:\n        return True\n    return any(",
        "    return any(",
        "replace_all_always_requires_admin",
    ),
    (
        "auth-37. any table's UPDATE needs admin",
        IMP,
        "        table.table == INSTANCE_SETTINGS.key\n        and any(row.action is RowAction.UPDATE for row in table.rows)",
        "        any(row.action is RowAction.UPDATE for row in table.rows)",
        "collection_only_merge_does_not_require_admin",
    ),
    (
        "auth-38. a settings sheet's presence needs admin",
        IMP,
        "        and any(row.action is RowAction.UPDATE for row in table.rows)",
        "        and any(True for row in table.rows)",
        "unchanged_settings_sheet_does_not_require_admin or add_only_skips_a_settings_change",
    ),
    (
        "auth-39. owner seeded claimed",
        AUTH_MIG,
        '    op.execute(sa.text("INSERT INTO owner (id, claimed_at) VALUES (1, NULL)"))',
        '    op.execute(sa.text("INSERT INTO owner (id, claimed_at) VALUES (1, now())"))',
        "owner_is_seeded_unclaimed_and_singular",
    ),
    (
        "auth-40. owner not seeded",
        AUTH_MIG,
        '    op.execute(sa.text("INSERT INTO owner (id, claimed_at) VALUES (1, NULL)"))',
        "    pass  # neutered",
        "owner_is_seeded_unclaimed_and_singular",
    ),
    (
        "auth-41. the /openapi.json alias rejection dropped",
        REG,
        '    ApiAliasRejection("/openapi.json", exact=True, family=11),\n',
        "",
        "root_canonical_live_route_is_covered or template_region_equals_the_registry_render",
    ),
    (
        "auth-42. the generated rejection answers 403",
        REG,
        '        lines.append(f"{indent}    return 404;")',
        '        lines.append(f"{indent}    return 403;")',
        "template_region_equals_the_registry_render",
    ),
    # --- #188 (M6-3) local owner auth — the m63- set from PR #200 (Codex round 1, f3:
    # m63-1, -2 and -4 survived the tests as first written; the re-anchored tests
    # kill them on the named control — the compare_digest call list, the
    # verifier's DUMMY_HASH argument, a pinned claimed_at) ------------------------
    (
        "m63-1. CSRF compared with ==",
        CRED,
        "    return hmac.compare_digest(presented, csrf_token_for(raw_session_token))",
        "    return presented == csrf_token_for(raw_session_token)",
        "csrf_token_is_bound",
    ),
    (
        "m63-2. verify_password(None) short-circuits before Argon2",
        CRED,
        "    try:\n        return _hasher.verify(encoded if encoded is not None else DUMMY_HASH, password)",
        "    if encoded is None:\n        return False\n    try:\n        return _hasher.verify(encoded if encoded is not None else DUMMY_HASH, password)",
        "dummy_hash",
    ),
    (
        "m63-3. opaque tokens compared with ==",
        CRED,
        "    return hmac.compare_digest(digest(presented), expected_digest)",
        "    return digest(presented) == expected_digest",
        "opaque_tokens",
    ),
    (
        "m63-4. recovery re-stamps claimed_at unconditionally",
        AUTH_SVC,
        "    if owner.claimed_at is None:\n        owner.claimed_at = _now()\n    await _replace_credential",
        "    owner.claimed_at = _now()\n    await _replace_credential",
        "recovery_reset_password_claims_and_revokes",
    ),
    (
        "m63-5. recovery never claims an unclaimed instance",
        AUTH_SVC,
        "    if owner.claimed_at is None:\n        owner.claimed_at = _now()\n    await _replace_credential",
        "    if owner.claimed_at is not None:\n        owner.claimed_at = _now()\n    await _replace_credential",
        "recovery_on_an_unclaimed",
    ),
    (
        "m63-6. CSRF never enforced",
        DEP,
        "    if request.method in _SAFE_METHODS or not principal.cookie_borne:\n        return",
        "    if True:\n        return",
        "without_the_csrf_token or without_an_origin or multipart_import",
    ),
    (
        "m63-7. bulk revocation not audited",
        AUTH_SVC,
        "    await audit.record_event(\n        session,\n        audit.SESSIONS_REVOKED,",
        "    if False:\n        await audit.record_event(\n        session,\n        audit.SESSIONS_REVOKED,",
        "recovery",
    ),
    (
        "m63-8. cookie mode never announced",
        MAIN,
        "            sessions.announce_cookie_mode(config)",
        "            pass",
        "cookie_mode",
    ),
    (
        "m63-9. the plain-http warning demoted to info",
        SESS,
        '    log.warning(\n        "Session cookie mode: %s is NOT Secure',
        '    log.info(\n        "Session cookie mode: %s is NOT Secure',
        "cookie_mode",
    ),
    (
        "m63-10. a login success does not reset the budget",
        AUTH_SVC,
        "    budget.reset()\n    if credentials.password_needs_rehash",
        "    if credentials.password_needs_rehash",
        "throttle_then_a_success_resets",
    ),
    # --- #189 (M6-4, PR #202): personal access tokens — the pat- set. The token
    # format and the shared bearer helper (the dummy compare, revoked/expired,
    # last-used, the audit rows), the resolver's strict presented-and-failed
    # 401 (malformed, fall-through, the committed audit row, the query string),
    # the family-3 bearer refusal, the family-6 classification, the MCP
    # verifier and tool-scope middleware (the seam order, the scope grant), the
    # mount built with the verifier, the 401 challenge, and the two review-round
    # fixes (pat-24: the value normalised in the helper; pat-25: rejected form
    # credentials are 403). Hand-run on the branch across six Codex rounds, all
    # killed; folded in here after merge (`f685c30`). ----------------------------
    (
        "pat-1. an unknown id skips the compare (no dummy digest)",
        TOK_SVC,
        "    expected = row.secret_hash if row is not None else token_format.DUMMY_DIGEST\n    matched = credentials.tokens_match(raw, expected)\n",
        "    matched = row is not None and credentials.tokens_match(raw, row.secret_hash)\n",
        "do_the_same_compare",
    ),
    (
        "pat-2. a revoked token still resolves",
        TOK_SVC,
        "    if row.revoked_at is not None:\n        await audit.record_event(",
        "    if False and row.revoked_at is not None:\n        await audit.record_event(",
        "use_after_revoke or same_401_on_every_route",
    ),
    (
        "pat-3. expiry compared the wrong way",
        TOK_SVC,
        "    if row.expires_at is not None and now >= row.expires_at:",
        "    if row.expires_at is not None and now < row.expires_at:",
        "expired or future_expiry",
    ),
    (
        "pat-4. admin scope mintable",
        TOK_SVC,
        "    if not granted or not granted <= token_format.GRANTABLE_SCOPES:",
        "    if not granted:",
        "no_admin_and_no_unknown",
    ),
    (
        "pat-5. write no longer implies read in the column",
        TOK_FMT,
        "    if Scope.WRITE in granted:\n        granted.add(Scope.READ)\n",
        "",
        "stored_grant_is_canonical",
    ),
    (
        "pat-6. a malformed Authorization header is anon",
        RESOLVER,
        "    if presented is token_format.MALFORMED:\n        raise UnauthenticatedError(\n            _BEARER_INVALID,\n            code=error_codes.AUTH_BEARER_INVALID,\n            challenge=INVALID_TOKEN_CHALLENGE,\n        )\n",
        "    if presented is token_format.MALFORMED:\n        return anonymous()\n",
        "same_401_on_every_route",
    ),
    (
        "pat-7. a failed bearer falls through to anon",
        RESOLVER,
        "        await session.commit()\n        raise UnauthenticatedError(\n            _BEARER_INVALID,\n            code=error_codes.AUTH_BEARER_INVALID,\n            challenge=INVALID_TOKEN_CHALLENGE,\n        )\n    return resolution.principal\n",
        "        await session.commit()\n        return anonymous()\n    return resolution.principal\n",
        "beside_a_cookie or same_401_on_every_route",
    ),
    (
        "pat-8. the use-after-revoke audit row is rolled back with the 401",
        RESOLVER,
        "        await session.commit()\n        raise UnauthenticatedError(",
        "        raise UnauthenticatedError(",
        "use_after_revoke_is_audited_even",
    ),
    (
        "pat-9. a query-string token is a credential",
        RESOLVER,
        "    presented = token_format.bearer_from_headers(request.headers)\n",
        '    presented = token_format.bearer_from_headers(request.headers) or request.query_params.get(\n        "access_token"\n    )\n',
        "query_string",
    ),
    (
        "pat-10. the dependency ignores bearer_refused",
        DEP,
        "    if policy.bearer_refused and principal.bearer_borne:",
        "    if False:",
        "refused_on_the_auth_actions",
    ),
    (
        "pat-11. the registry never sets bearer_refused",
        REG,
        "            bearer_refused=(family == 3),",
        "            bearer_refused=False,",
        "refused_on_the_auth_actions",
    ),
    (
        "pat-12. token management is a family-5 write",
        REG,
        "        return RoutePolicy(\n            6, CredentialPolicy.ADMIN, route.methods, _NO_STORE, spellings=api_spelling\n        )\n",
        "        return RoutePolicy(\n            5, CredentialPolicy.WRITE, route.methods, _NO_STORE, spellings=api_spelling\n        )\n",
        "cannot_manage_tokens or rest_surface_matches",
    ),
    (
        "pat-13. the tool-scope check is skipped",
        MCP_AUTH,
        "        if not principal.has_scope(required):",
        "        if False:",
        "every_write_tool_refuses or tool_scope_over_http",
    ),
    (
        "pat-14. an HTTP request without a token falls back to the seam",
        MCP_AUTH,
        "        if _http_request_in_flight():\n            raise ToolError(_UNAUTHENTICATED)\n",
        "",
        "open_mount_still_refuses",
    ),
    (
        "pat-15. the verifier grants every scope",
        MCP_AUTH,
        "                scopes=[scope.value for scope in Scope if scope in principal.scopes],",
        "                scopes=[scope.value for scope in Scope],",
        "tool_scope_over_http",
    ),
    (
        "pat-16. the mount is built without the verifier",
        MAIN,
        "        auth=PersonalAccessTokenVerifier() if authorization else None,",
        "        auth=None,",
        "takes_a_bearer_and_never_a_cookie or carries_no_store_over",
    ),
    (
        "pat-17. no WWW-Authenticate on the 401 envelope",
        MAIN,
        '    if isinstance(exc, UnauthenticatedError) and exc.challenge:\n        headers["WWW-Authenticate"] = exc.challenge\n',
        "",
        "anonymous_401_carries or same_401_on_every_route",
    ),
    (
        "pat-18. the mint audit row carries the secret",
        TOK_SVC,
        '        detail=f"token={row.id} scopes={row.scopes}",',
        '        detail=f"token={raw} scopes={row.scopes}",',
        "audited_without_the_secret or leaves_no_secret",
    ),
    (
        "pat-19. revoke re-stamps an already-revoked row",
        TOK_SVC,
        "    if row.revoked_at is None:\n        row.revoked_at = _now()\n",
        "    row.revoked_at = _now()\n",
        "revoke_is_idempotent",
    ),
    (
        "pat-20. the bearer scheme is case-sensitive",
        TOK_FMT,
        '    if scheme.lower() != "bearer" or not value:',
        '    if scheme != "Bearer" or not value:',
        "only_a_bearer_header",
    ),
    (
        "pat-21. last_used_at is never touched",
        TOK_SVC,
        "    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_WRITE_INTERVAL:\n        row.last_used_at = now\n",
        "",
        "last_used_is_touched",
    ),
    (
        "pat-22. every verified token is a write token",
        MCP_AUTH,
        "        return pat(write=Scope.WRITE in scopes, subject=token.client_id, via=VIA_BEARER)",
        "        return pat(write=True, subject=token.client_id, via=VIA_BEARER)",
        "tool_scope_over_http",
    ),
    (
        "pat-23. the transport route keeps FastMCP's declared methods",
        MAIN,
        "                route.methods = None  # type: ignore[attr-defined]",
        "                pass",
        "mounted_surface_matches or accepts_exactly_the_declared or carries_no_store_over",
    ),
    (
        "pat-24. the shared helper no longer strips the presented value (round 1, f1)",
        TOK_SVC,
        "    raw = raw.strip()\n",
        "",
        "header_form",
    ),
    (
        "pat-25. a rejected form credential is 401 again (round 2, f4)",
        MAIN,
        "    CredentialRejectedError: 403,\n",
        "    CredentialRejectedError: 401,\n",
        "every_401_carries or wrong_password_is_403 or wrong_setup_token_is_403",
    ),
    # The #204 (f13-) set: the pre-routing gate (§5.5 family 13), folded from PR
    # #205. f13-1…13 hand-run on the branch; f13-14/15 added when CI Integration
    # caught the family-8 namespace miss. f13-6's only witness is the
    # resolution-count test (Codex round 1, f2: the audit-row test cannot see
    # it — a revoked token is refused at the gate); f13-11 is structural.
    (
        "f13-1. the gate passes everything through",
        PRE,
        "        if outcome.kind in (Dispatch.MOUNT, Dispatch.PROTOCOL):\n            await self.app(scope, receive, send)\n            return\n",
        "        if True:\n            await self.app(scope, receive, send)\n            return\n",
        "is_401_for_anon or resolver_s_401",
    ),
    (
        "f13-2. no match is not refused",
        PRE,
        "    if outcome.kind is Dispatch.NONE:\n        return True\n",
        "    if outcome.kind is Dispatch.NONE:\n        return False\n",
        "unrouted_path_is_401_for_anon",
    ),
    (
        "f13-3. a partial match admits INTERNAL (405 names /readyz)",
        PRE,
        "        else {CredentialPolicy.ANONYMOUS, CredentialPolicy.PROTOCOL}\n",
        "        else {CredentialPolicy.ANONYMOUS, CredentialPolicy.PROTOCOL, CredentialPolicy.INTERNAL}\n",
        "wrong_verb_on_a_scoped_path_is_401_for_anon or decided_by_policy",
    ),
    (
        "f13-4. a full match no longer admits INTERNAL (loopback /readyz → 401)",
        PRE,
        "        {CredentialPolicy.ANONYMOUS, CredentialPolicy.INTERNAL, CredentialPolicy.PROTOCOL}\n        if outcome.kind is Dispatch.FULL",
        "        {CredentialPolicy.ANONYMOUS, CredentialPolicy.PROTOCOL}\n        if outcome.kind is Dispatch.FULL",
        "readiness_is_still_decided or decided_by_policy",
    ),
    (
        "f13-5. an endpoint the index does not know fails open",
        PRE,
        "        if policy is None or policy.credential not in admitted:",
        "        if policy is not None and policy.credential not in admitted:",
        "decided_by_policy",
    ),
    (
        "f13-6. the dependency ignores the stashed principal (resolves twice)",
        DEP,
        "    principal = getattr(request.state, REQUEST_PRINCIPAL_ATTR, None)\n    if principal is None:",
        "    principal = None\n    if principal is None:",
        "resolved_by_the_gate or one_audit_row",
    ),
    (
        "f13-7. the gate's refusal drops Cache-Control",
        PRE,
        "        if cache_control is not None:",
        "        if cache_control is None:",
        "unrouted_path_is_401_for_anon",
    ),
    (
        "f13-8. the early return keys on NONE, not MOUNT (a cookie is resolved under /mcp)",
        PRE,
        "        if outcome.kind in (Dispatch.MOUNT, Dispatch.PROTOCOL):\n            await self.app",
        "        if outcome.kind in (Dispatch.NONE, Dispatch.PROTOCOL):\n            await self.app",
        "resolved_by_the_gate or unrouted_path_is_401_for_anon",
    ),
    (
        "f13-9. the dispatch table adds HEAD beside GET the way Starlette's Route would",
        PRE,
        "entries.append(_Leaf(regex=regex, methods=entry.methods, endpoint=entry.endpoint))",
        "entries.append(_Leaf(regex=regex, methods=entry.methods | ({'HEAD'} if 'GET' in entry.methods else set()), endpoint=entry.endpoint))",
        "agree_on_every_declared_route",
    ),
    (
        "f13-10. a failed bearer is refused with the bare challenge, not the resolver's",
        PRE,
        "            await self._refuse(request, exc, scope, receive, send)\n            return\n        setattr",
        "            await self._refuse(request, UnauthenticatedError(_UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED, challenge=BEARER_CHALLENGE), scope, receive, send)\n            return\n        setattr",
        "resolver_s_401",
    ),
    (
        "f13-11. the gate and the profile layer swap positions",
        MAIN,
        "            render=domain_error_handler,\n        )\n",
        "            render=domain_error_handler,\n        )\n        app.user_middleware.reverse()\n",
        "sits_between or profile_middleware_is_innermost",
    ),
    (
        "f13-12. the dependency's fallback resolution removed",
        DEP,
        "    if principal is None:\n        principal = await resolve_principal(request, session)",
        "    if False:\n        principal = await resolve_principal(request, session)",
        "denies_without_the_gate",
    ),
    (
        "f13-13. a partial match considers only the first route on the path",
        PRE,
        "    for endpoint in outcome.endpoints:\n        policy = index.policy_for(endpoint)",
        "    for endpoint in outcome.endpoints[:1]:\n        policy = index.policy_for(endpoint)",
        "decided_by_policy",
    ),
    (
        "f13-14. the protocol-namespace pass-through disabled (the first head's family-8 miss)",
        PRE,
        "        if any(route_path.startswith(prefix) for prefix in PROTOCOL_NAMESPACES):",
        "        if False and any(route_path.startswith(prefix) for prefix in PROTOCOL_NAMESPACES):",
        "protocol_namespace or decided_by_policy or agree_on_every",
    ),
    (
        "f13-15. the early return keeps MOUNT only (a principal is resolved under /.well-known/)",
        PRE,
        "        if outcome.kind in (Dispatch.MOUNT, Dispatch.PROTOCOL):\n            await self.app",
        "        if outcome.kind is Dispatch.MOUNT:\n            await self.app",
        "resolved_by_the_gate",
    ),
    # --- #191 (M6-6, PR #209): browser OIDC — the oidc- set. The id_token claim
    # --- contract (`validate_id_token_claims`), the login transaction and its binding
    # --- cookie, the `(issuer, subject)` binding, the mode gate, the rebind, and — from
    # --- the Codex rounds — a session being authority only in the mode that minted it
    # --- (`session.auth_mode`, the resolver, the start-up sweep) and the NumericDate
    # --- domain. oidc-4…20 hand-run on the branch; 21…38 from round 1 (two P2s), 39
    # --- from round 2 (a P3). oidc-1/2/3/11 anchored on the joserfc registry the round
    # --- replaced and are superseded by 23/22/27/26; oidc-13 (HS256 on the allowlist)
    # --- is equivalent — the JWKS holds no symmetric key — and stays out; oidc-20 and
    # --- oidc-25 re-anchored at fold-in. oidc-30's kill is a 500 at the callback's
    # --- required 302, accepted by Codex round 2 as a semantic regression. -----------
    (
        "oidc-4. binding cookie not checked",
        OIDC_SVC,
        "        or binding is None\n        or not credentials.tokens_match(binding, row.binding_hash)\n",
        "",
        "callback_needs_a_live_transaction",
    ),
    (
        "oidc-5. transaction never spent",
        OIDC_SVC,
        "    row.used_at = now\n    claiming, nonce, verifier",
        "    claiming, nonce, verifier",
        "callback_needs_a_live_transaction",
    ),
    (
        "oidc-6. expiry not checked",
        OIDC_SVC,
        "        or now >= row.expires_at\n",
        "",
        "expired_transaction_is_refused",
    ),
    (
        "oidc-7. binding compares subject only",
        OIDC_SVC,
        "    if (owner.oidc_issuer, owner.oidc_subject) != (provider.issuer, subject):",
        "    if owner.oidc_subject != subject:",
        "binding_is_the_issuer_too",
    ),
    (
        "oidc-8. unbound = unclaimed only",
        OIDC_SVC,
        "    return owner.claimed_at is None or owner.oidc_subject is None",
        "    return owner.claimed_at is None",
        "rebind_revokes_every_session",
    ),
    (
        "oidc-9. bind without the token having matched",
        OIDC_SVC,
        "        if not claiming:\n            raise await _refuse(",
        "        if False:\n            raise await _refuse(",
        "unbound_owner_without_the_token_at_start",
    ),
    (
        "oidc-10. setup token never required at start",
        OIDC_SVC,
        "        if setup_token is None or not setup_state.matches(setup_token):",
        "        if False:",
        "start_on_an_unbound_instance_needs_the_setup_token",
    ),
    (
        "oidc-12. provider error still exchanges",
        OIDC_SVC,
        "    if error is not None or not code:",
        "    if not code:",
        "owner_cancelling_at_the_provider",
    ),
    (
        "oidc-14. rebind keeps sessions",
        OIDC_SVC,
        '    revoked = await auth_service.revoke_all_sessions(\n        session, target="recovery rebind-oidc", client_address="host"\n    )',
        "    revoked = 0",
        "rebind_revokes_every_session",
    ),
    (
        "oidc-15. refused stranger still gets a session",
        OIDC_SVC,
        "        await session.commit()\n        raise OidcLoginRefused(CallbackError.IDENTITY_REFUSED)",
        "        await session.commit()",
        "different_identity_is_refused",
    ),
    (
        "oidc-16. discovery issuer mismatch accepted",
        OIDC_SVC,
        "            if issuer != self.issuer:",
        "            if False:",
        "discovery_document_with_another_issuer",
    ),
    (
        "oidc-17. mode gate inverted",
        AUTH_ROUTER,
        "    if (provider is not None) != oidc:",
        "    if (provider is None) != oidc:",
        "password_routes_are_404_in_oidc_mode",
    ),
    (
        "oidc-18. modes undeclared on the OIDC pair",
        REG,
        'OIDC_MODE_ROUTES: frozenset[str] = frozenset({"/auth/oidc/start", "/auth/oidc/callback"})',
        "OIDC_MODE_ROUTES: frozenset[str] = frozenset()",
        "registry_declares_the_mode_axis",
    ),
    (
        "oidc-19. callback Location built from the request",
        AUTH_ROUTER,
        "    response = RedirectResponse(provider.home_url, status_code=302)",
        "    response = RedirectResponse(str(request.base_url), status_code=302)",
        "callback_redirects_to_public_base_url",
    ),
    (
        "oidc-20. setup token consumed at start, not at the bind",
        OIDC_SVC,
        "        setup_state.consume()\n        raw, session_row = auth_service.new_session_row(now, auth_mode=AuthMode.OIDC)\n",
        "        raw, session_row = auth_service.new_session_row(now, auth_mode=AuthMode.OIDC)\n",
        "first_login_with_the_setup_token_binds_the_owner",
    ),
    (
        "oidc-21. azp not checked",
        OIDC_SVC,
        '    if "azp" in claims and claims["azp"] != client_id:\n        raise refused("azp", "is not this client")\n',
        "",
        "azp-other",
    ),
    (
        "oidc-22. aud membership instead of exactly this client",
        OIDC_SVC,
        "        or set(audiences) != {client_id}\n",
        "        or client_id not in audiences\n",
        "extra-audience-own-azp",
    ),
    (
        "oidc-23. nonce matched by membership (the registry's semantics)",
        OIDC_SVC,
        "    if not isinstance(token_nonce, str) or token_nonce != nonce:\n",
        "    if nonce not in ([token_nonce] if isinstance(token_nonce, str) else (token_nonce or [])):\n",
        "nonce-list",
    ),
    (
        "oidc-24. iat optional",
        OIDC_SVC,
        '    if not _numeric_date(iat):\n        raise refused("iat", "is missing or not a NumericDate")\n    if iat > clock + leeway:\n',
        '    if iat is not None and not _numeric_date(iat):\n        raise refused("iat", "is missing or not a NumericDate")\n    if iat is not None and iat > clock + leeway:\n',
        "iat-missing",
    ),
    (
        "oidc-25. bool accepted as a NumericDate",
        OIDC_SVC,
        "    if isinstance(value, bool):\n        return False\n    if isinstance(value, int):\n        return True\n",
        "    if isinstance(value, int):\n        return True\n",
        "iat-bool",
    ),
    (
        "oidc-26. sub not checked by the validator",
        OIDC_SVC,
        '    sub = claims.get("sub")\n    if not isinstance(sub, str) or not sub:\n        raise refused("sub", "is missing or not a string")\n',
        "",
        "no-subject",
    ),
    (
        "oidc-27. iss matched by membership",
        OIDC_SVC,
        "    if not isinstance(iss, str) or iss != issuer:\n",
        "    if iss != issuer and not (isinstance(iss, list) and issuer in iss):\n",
        "issuer-list",
    ),
    (
        "oidc-28. exp leeway applied the wrong way",
        OIDC_SVC,
        "    if exp < clock - leeway:\n",
        "    if exp < clock + leeway:\n",
        "claim_validator_holds_the_clock_leeway",
    ),
    (
        "oidc-29. nbf not checked",
        OIDC_SVC,
        '    if "nbf" in claims:\n        nbf = claims["nbf"]\n        if not _numeric_date(nbf):\n            raise refused("nbf", "is not a NumericDate")\n        if nbf > clock + leeway:\n            raise refused("nbf", "is in the future")\n',
        "",
        "nbf-future",
    ),
    (
        "oidc-30. exp type not checked",
        OIDC_SVC,
        '    if not _numeric_date(exp):\n        raise refused("exp", "is missing or not a NumericDate")\n',
        '    if exp is None:\n        raise refused("exp", "is missing or not a NumericDate")\n',
        "exp-string",
    ),
    (
        "oidc-31. resolver ignores the session's mode",
        AUTH_SVC,
        "    if row is None or row.revoked_at is not None or row.auth_mode != auth_mode:\n",
        "    if row is None or row.revoked_at is not None:\n",
        "local_mode_session_is_not_the_owner_in_oidc_mode",
    ),
    (
        "oidc-32. sweep revokes every mode's sessions",
        AUTH_SVC,
        "        .where(SessionRow.revoked_at.is_(None), SessionRow.auth_mode != auth_mode)\n",
        "        .where(SessionRow.revoked_at.is_(None))\n",
        "restart_in_the_same_mode_signs_nobody_out",
    ),
    (
        "oidc-33. sweep touches instead of revoking",
        AUTH_SVC,
        '        .values(revoked_at=_now())\n    )\n    revoked = result.rowcount or 0\n    if revoked:\n        await audit.record_event(\n            session,\n            audit.SESSIONS_REVOKED,\n            target="startup",',
        '        .values(last_used_at=_now())\n    )\n    revoked = result.rowcount or 0\n    if revoked:\n        await audit.record_event(\n            session,\n            audit.SESSIONS_REVOKED,\n            target="startup",',
        "starting_in_the_other_mode_revokes",
    ),
    (
        "oidc-34. lifespan never sweeps",
        MAIN,
        "                await auth_service.revoke_sessions_of_other_modes(\n                    session, auth_mode=auth_mode_of(app_)\n                )\n",
        "",
        "starting_in_the_other_mode_revokes",
    ),
    (
        "oidc-35. the OIDC bind mints a local-mode session",
        OIDC_SVC,
        "        setup_state.consume()\n        raw, session_row = auth_service.new_session_row(now, auth_mode=AuthMode.OIDC)\n",
        "        setup_state.consume()\n        raw, session_row = auth_service.new_session_row(now, auth_mode=AuthMode.LOCAL)\n",
        "first_login_with_the_setup_token_binds_the_owner",
    ),
    (
        "oidc-36. the local claim mints an OIDC-mode session",
        AUTH_SVC,
        "    owner.claimed_at = now\n    raw, row = new_session_row(now, auth_mode=AuthMode.LOCAL)\n",
        "    owner.claimed_at = now\n    raw, row = new_session_row(now, auth_mode=AuthMode.OIDC)\n",
        "local_mode_session_is_not_the_owner_in_oidc_mode",
    ),
    (
        "oidc-37. mode_changed audit row not written",
        AUTH_SVC,
        '        await audit.record_event(\n            session,\n            audit.AUTH_MODE_CHANGED,\n            target="startup",\n            detail=f"auth_mode={auth_mode} sessions_revoked={revoked}",\n            client_address="host",\n        )\n',
        "",
        "starting_in_the_other_mode_revokes",
    ),
    (
        "oidc-38. auth_mode_of inverted",
        MODE,
        "    if getattr(app.state, OIDC_PROVIDER_ATTR, None) is not None:\n        return AuthMode.OIDC\n    return AuthMode.LOCAL\n",
        "    if getattr(app.state, OIDC_PROVIDER_ATTR, None) is None:\n        return AuthMode.OIDC\n    return AuthMode.LOCAL\n",
        "first_login_with_the_setup_token_binds_the_owner",
    ),
    (
        "oidc-39. non-finite floats accepted as NumericDates",
        OIDC_SVC,
        "    return isinstance(value, float) and math.isfinite(value)\n",
        "    return isinstance(value, float)\n",
        "exp-nan",
    ),
    # --- #192 (M6-7): MCP OAuth — the moa- set ------------------------------------------
    # The proxy's policy on FastMCP's extension points (app/auth/mcp_oauth.py), the
    # family-8 registry declarations, the pre-routing gate's namespace rule, the
    # principal mapping and the settings contract. Every kill runs against an
    # OIDC-mode app built in-process with the fake provider (tests/oidc_fake.py).
    (
        "moa-1. the synthesised upstream-id client admitted",
        MCP_OAUTH,
        "        if client_id == self._upstream_client_id:\n            # The synthesised",
        "        if False:\n            # The synthesised",
        "synthesised_upstream_id_client_is_refused",
    ),
    (
        "moa-2. a DCR client not wrapped in the registration binding",
        MCP_OAUTH,
        "        return BoundDCRClient(**client.model_dump(), allow_unregistered_redirect_uris=False)",
        "        return client",
        "allowlist_narrows_registration_and_keeps_the_registration_binding",
    ),
    (
        "moa-3. the registration check inside BoundDCRClient removed",
        MCP_OAUTH,
        "        if redirect_uri is not None and self.cimd_document is None:\n            if not _matches_registered_redirect_uri(redirect_uri, self.redirect_uris):",
        "        if False:\n            if not _matches_registered_redirect_uri(redirect_uri, self.redirect_uris):",
        "allowlist_narrows_registration_and_keeps_the_registration_binding",
    ),
    (
        "moa-4. the owner check at issuance skipped",
        MCP_OAUTH,
        "            if verdict.binding is None:\n                # Consume the code first",
        "            if False:\n                # Consume the code first",
        "stranger_is_refused_at_the_token_endpoint or unbound_instance_issues_nothing",
    ),
    (
        "moa-5. the binding comparison always passes",
        MCP_OAUTH,
        '        if bound != (provider.issuer, subject):\n            return OwnerVerdict(None, "identity", subject)',
        '        if False:\n            return OwnerVerdict(None, "identity", subject)',
        "stranger_is_refused_at_the_token_endpoint or rebind_refuses_an_issued_token",
    ),
    (
        "moa-6. the grant no longer bounded by the upstream token's expiry",
        MCP_OAUTH,
        '        bounds a grant."""\n        return True',
        '        bounds a grant."""\n        return False',
        "upstream_token_bounds_a_grant_the_provider_cannot_refresh",
    ),
    (
        "moa-7. a personal access token no longer routed to its verifier on the mount",
        MCP_OAUTH,
        '        if token.startswith(f"{token_format.TOKEN_KIND}_"):',
        "        if False:",
        "personal_access_token_still_works_on_the_mount_in_oidc_mode",
    ),
    (
        "moa-8. the mcp grant mapped read-only",
        MCP_AUTH,
        '        return mcp(write=True, subject=token.claims.get("sub"))',
        '        return mcp(write=False, subject=token.claims.get("sub"))',
        "owner_links_a_client_and_the_token_drives_the_tools or mcp_kind_maps_to_the_fixed_scopes",
    ),
    (
        "moa-9. any kind maps to the mcp principal",
        MCP_AUTH,
        "    if kind == PrincipalKind.MCP.value:\n        return mcp(",
        "    if True:\n        return mcp(",
        "mcp_kind_maps_to_the_fixed_scopes_and_nothing_else_is_a_principal",
    ),
    (
        "moa-10. the identity refusal not audited as one",
        MCP_OAUTH,
        "            await self._record(\n                audit.MCP_IDENTITY_REFUSED,",
        "            await self._record(\n                audit.OIDC_LOGIN_FAILED,",
        "stranger_is_refused_at_the_token_endpoint",
    ),
    (
        "moa-11. the grant not audited as one",
        MCP_OAUTH,
        "            await self._record(\n                audit.MCP_GRANT_ISSUED,",
        "            await self._record(\n                audit.OIDC_LOGIN_FAILED,",
        "owner_links_a_client_and_the_token_drives_the_tools",
    ),
    (
        "moa-12. authorize does not resolve the upstream endpoints",
        MCP_OAUTH,
        # Re-anchored in round 7 (the docstring `authorize` gained sits between the
        # `def` line and the `try:` the old anchor spanned).
        "        try:\n            await self._resolve_upstream()\n        except UnavailableError as exc:\n            raise AuthorizeError(",
        "        try:\n            pass\n        except UnavailableError as exc:\n            raise AuthorizeError(",
        "provider_down_at_authorize_is_temporarily_unavailable",
    ),
    (
        "moa-13. a provider outage at authorize escapes as an exception",
        MCP_OAUTH,
        '        except UnavailableError as exc:\n            raise AuthorizeError(\n                error="temporarily_unavailable", error_description=_PROVIDER_UNAVAILABLE\n            ) from exc',
        "        except UnavailableError as exc:\n            raise exc",
        "provider_down_at_authorize_is_temporarily_unavailable",
    ),
    (
        "moa-14. the callback does not resolve the upstream endpoints",
        MCP_OAUTH,
        "    async def _handle_idp_callback(self, request: Request):\n        try:\n            await self._resolve_upstream()",
        "    async def _handle_idp_callback(self, request: Request):\n        try:\n            pass",
        "process_whose_start_missed_the_provider",
    ),
    (
        "moa-15. the refresh exchange does not resolve the upstream endpoints",
        MCP_OAUTH,
        '        try:\n            await self._resolve_upstream()\n        except UnavailableError as exc:\n            raise TokenError("invalid_request", _PROVIDER_UNAVAILABLE) from exc',
        '        try:\n            pass\n        except UnavailableError as exc:\n            raise TokenError("invalid_request", _PROVIDER_UNAVAILABLE) from exc',
        "process_whose_start_missed_the_provider",
    ),
    (
        "moa-17. the child's well-known aliases not pruned",
        MCP_OAUTH,
        '        if not (isinstance(route, Route) and route.path.startswith("/.well-known/"))',
        "        if True",
        "mounted_surface_in_oidc_mode_matches_its_snapshot",
    ),
    (
        "moa-18. the protocol routes keep the SDK's own method metadata",
        MCP_OAUTH,
        "        if isinstance(route, Route) and MCP_MOUNT + route.path in MCP_OAUTH_ROUTES:\n            route.methods = None",
        "        if False:\n            route.methods = None",
        "each_protocol_route_accepts_exactly_its_declared_verbs",
    ),
    (
        "moa-19. the bare OpenID document installed at the root",
        MCP_OAUTH,
        "        if route.path not in DISCOVERY_ROUTES:\n            continue",
        "        if False:\n            continue",
        "mounted_surface_in_oidc_mode_matches_its_snapshot or three_root_documents_name_this_instance",
    ),
    (
        "moa-20. the local-mode stub answers 200",
        MCP_OAUTH,
        "            status_code=404,\n        )\n        await response(scope, receive, send)",
        "            status_code=200,\n        )\n        await response(scope, receive, send)",
        "every_family_8_path_is_404_in_local_mode",
    ),
    (
        "moa-21. no protocol routes registered in local mode",
        MCP_OAUTH,
        "    return [Route(_child_path(path), endpoint=NotInThisMode(path)) for path in MCP_OAUTH_ROUTES]",
        "    return []",
        "mounted_surface_matches_the_snapshot or every_family_8_path_is_404_in_local_mode",
    ),
    (
        "moa-22. the storage key is the signing key",
        MCP_OAUTH,
        "    return base64.urlsafe_b64encode(derived)",
        "    return base64.urlsafe_b64encode(signing_key)",
        "storage_key_differs_from_the_signing_key",
    ),
    (
        "moa-23. the audit rows name the wrong route",
        MCP_OAUTH,
        '        self, event: str, *, detail: str, principal=None, target: str = f"{MCP_MOUNT}/token"',
        '        self, event: str, *, detail: str, principal=None, target: str = f"{MCP_MOUNT}/authorize"',
        "id_token_that_fails_the_claim_contract_issues_nothing or owner_links_a_client",
    ),
    (
        "moa-24. discovery declared no-store",
        REG,
        '    path: _protocol(path, ("GET", "HEAD", "OPTIONS"), ProtocolRole.DISCOVERY, _PUBLIC_DISCOVERY)',
        '    path: _protocol(path, ("GET", "HEAD", "OPTIONS"), ProtocolRole.DISCOVERY)',
        "three_root_documents_name_this_instance or every_transaction_and_credential_response",
    ),
    (
        "moa-25. the authorization endpoint declared with PUT",
        REG,
        '        f"{MCP_MOUNT}/authorize", ("GET", "POST"), ProtocolRole.AUTHORIZATION',
        '        f"{MCP_MOUNT}/authorize", ("GET", "POST", "PUT"), ProtocolRole.AUTHORIZATION',
        "each_protocol_route_accepts_exactly_its_declared_verbs",
    ),
    (
        "moa-26. the gate resolves a principal under the protocol namespace",
        PRE,
        "        if any(route_path.startswith(prefix) for prefix in PROTOCOL_NAMESPACES):\n            # Family 8's namespace is the protocol's, route or no route (#192):",
        "        if False:\n            # Family 8's namespace is the protocol's, route or no route (#192):",
        "discovery_resolves_no_principal or gate_and_the_router_agree",
    ),
    (
        "moa-27. a scoped route admitted under the protocol namespace",
        REG,
        "            and policy.credential != CredentialPolicy.PROTOCOL\n            and any(leaf.path.startswith(prefix) for prefix in PROTOCOL_NAMESPACES)",
        "            and False",
        "non_protocol_route_under_the_protocol_namespace_fails_the_build",
    ),
    (
        "moa-28. a discovery route's verbs not pinned",
        REG,
        "        if route.methods != declared.methods:\n            raise UndeclaredRouteError(",
        "        if False:\n            raise UndeclaredRouteError(",
        "discovery_route_serving_other_verbs_than_declared_fails_the_build",
    ),
    (
        "moa-29. the signing key optional in OIDC mode",
        CFG,
        '                ("MCP_OAUTH_SIGNING_KEY", self.mcp_oauth_signing_key),\n',
        "",
        "oidc_mode_requires_the_signing_key_and_an_https_or_loopback_base_url",
    ),
    (
        "moa-30. a plain-http LAN base URL admitted in OIDC mode",
        CFG,
        '        if parsed.scheme != "https" and parsed.hostname not in MCP_OAUTH_PLAIN_HTTP_HOSTS:',
        "        if False:",
        "oidc_mode_requires_the_signing_key_and_an_https_or_loopback_base_url",
    ),
    (
        "moa-31. the signing key's shape not checked",
        CFG,
        '        if not re.fullmatch(r"[0-9a-f]{64}", value):',
        "        if False:",
        "oidc_mode_requires_the_signing_key_and_an_https_or_loopback_base_url",
    ),
    (
        "moa-32. the nonce check no longer skippable — the proxy's tokens refused",
        OIDC_SVC,
        '    if nonce is None:\n        return\n    token_nonce = claims.get("nonce")',
        '    token_nonce = claims.get("nonce")',
        "owner_links_a_client_and_the_token_drives_the_tools",
    ),
    (
        "moa-33. the nonce check skipped for the browser login too",
        OIDC_SVC,
        '    if nonce is None:\n        return\n    token_nonce = claims.get("nonce")',
        '    if True:\n        return\n    token_nonce = claims.get("nonce")',
        "id_token_that_fails_a_check_opens_no_session and nonce",
    ),
    # --- Codex #212 round 1: the grant as one state machine (f1–f5) ------------------
    (
        "moa-34. revocation leaves the grant record (the presented token stays live)",
        MCP_OAUTH,
        "                    grant = await self._upstream_token_store.get(key=mapping.upstream_token_id)\n                    await self._upstream_token_store.delete(key=mapping.upstream_token_id)",
        "                    grant = await self._upstream_token_store.get(key=mapping.upstream_token_id)",
        "successful_revocation_kills_every_credential_of_the_grant",
    ),
    (
        "moa-35. the provider not asked to revoke its refresh token",
        MCP_OAUTH,
        "        await self._revoke_upstream(grant)",
        "        pass",
        "successful_revocation_kills_every_credential_of_the_grant",
    ),
    (
        "moa-36. revocation audited as issuance",
        MCP_OAUTH,
        "            audit.MCP_GRANT_REVOKED,\n            principal=mcp_principal(write=True, subject=handle[1].subject),",
        "            audit.MCP_GRANT_ISSUED,\n            principal=mcp_principal(write=True, subject=handle[1].subject),",
        "successful_revocation_kills_every_credential_of_the_grant",
    ),
    (
        "moa-37. no transition takes its lock (two redemptions of a code mint)",
        MCP_OAUTH,
        "        await self._lock.__aenter__()\n        self._declared = _transition_in_flight.set(self._transition)",
        "        self._lock._session = get_sessionmaker()()\n        self._declared = _transition_in_flight.set(self._transition)",
        "two_redemptions_of_one_authorization_code_yield_one_grant",
    ),
    (
        "moa-38. no transition takes its lock (two redemptions of a refresh token mint)",
        MCP_OAUTH,
        "        await self._lock.__aenter__()\n        self._declared = _transition_in_flight.set(self._transition)",
        "        self._lock._session = get_sessionmaker()()\n        self._declared = _transition_in_flight.set(self._transition)",
        "two_redemptions_of_one_refresh_token_yield_one_successor_lineage",
    ),
    (
        "moa-39. the lock key is the handle itself, as a SQL parameter (the code in the log)",
        MCP_OAUTH,
        '                "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), CAST(:key AS integer))"\n            ),\n            {"namespace": GRANT_LOCK_NAMESPACE, "key": _lock_key(self._handle)},',
        '                "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), hashtext(CAST(:key AS text)))"\n            ),\n            {"namespace": GRANT_LOCK_NAMESPACE, "key": self._handle},',
        "full_link_and_tool_run_leaves_no_secret_in_the_logs",
    ),
    (
        "moa-40. the per-request owner check skipped (a rebind changes nothing)",
        MCP_OAUTH,
        "        if not await self._owner_check.still_bound(binding):\n            log.warning",
        "        if False:\n            log.warning",
        "rebind_refuses_an_issued_token_at_the_next_request",
    ),
    (
        "moa-41. the rebind check on a refresh skipped",
        MCP_OAUTH,
        "        if not await self._owner_check.still_bound(carried):",
        "        if False:",
        "rebind_refuses_the_refresh_token_too",
    ),
    (
        "moa-42. a refresh's new id_token carried forward unverified",
        MCP_OAUTH,
        "        if isinstance(id_token, str) and _digest(id_token) == established.id_token_digest:\n            binding = established",
        "        if True:\n            binding = established",
        "refresh_response_becomes_the_grant_only_once_it_is_verified",
    ),
    (
        "moa-43. the consent handler does not resolve the upstream endpoints",
        MCP_OAUTH,
        "    async def _handle_consent(self, request: Request):",
        "    async def _handle_consent_unused(self, request: Request):",
        "restart_between_the_consent_page_and_its_approval",
    ),
    (
        "moa-44. the endpoint properties read the placeholder even once resolved",
        MCP_OAUTH,
        "        return metadata.authorization_endpoint if metadata is not None else UNRESOLVED_ENDPOINT",
        "        return UNRESOLVED_ENDPOINT",
        "upstream_authorization_request_is_built_from_configuration",
    ),
    (
        "moa-45. the registration body guard not installed",
        MAIN,
        "        prune_child_well_known(mcp_app)\n        guard_registration_body(mcp_app)",
        "        prune_child_well_known(mcp_app)",
        "registration_body_that_is_not_client_metadata_is_the_dcr_400",
    ),
    (
        "moa-46. a protocol route's failure not stamped with the profile",
        DEP,
        "            if not started:\n                await JSONResponse",
        "            if False:\n                await JSONResponse",
        "exception_under_a_protocol_route_still_carries_the_profile",
    ),
    (
        "moa-48. an unhandled 500 on a REST route without the profile",
        MAIN,
        '        content={"detail": "Internal Server Error"},\n        headers={"Cache-Control": "no-store"},',
        '        content={"detail": "Internal Server Error"},',
        "no_store_on_an_unhandled_500_too",
    ),
    (
        "moa-47. a revoked refresh token's own hash entry left behind",
        MCP_OAUTH,
        "        if isinstance(token, RefreshToken):\n            # Its own hash entry",
        "        if False:\n            # Its own hash entry",
        "successful_revocation_kills_every_credential_of_the_grant",
    ),
    # --- Codex #212 round 2: the grant record as the unit of authority (f6–f7) ---------
    (
        "moa-49. the gate takes the binding off the client's tokens, not the record",
        MCP_OAUTH,
        "            current = await self._inner.get(key=key)\n            if current is None or current.owner is None:\n                raise _GrantEnded()\n            established = current.owner",
        "            established = transition.binding",
        "binding_verified_on_a_transparent_refresh_carries_to_the_next_exchange",
    ),
    (
        "moa-50. revocation not under the grant's lock (a refresh in flight recreates the record)",
        MCP_OAUTH,
        "                async with _GrantLock(mapping.upstream_token_id):",
        "                if True:",
        "refresh_in_flight_cannot_recreate_a_grant_that_revocation_removed",
    ),
    (
        "moa-51. the transparent refresh not a transition of the grant (the SDK's own runs)",
        MCP_OAUTH,
        "    async def _try_transparent_refresh(\n        self, upstream_token_set: UpstreamTokenSet\n    ) -> UpstreamTokenSet:",
        "    async def _try_transparent_refresh_unused(\n        self, upstream_token_set: UpstreamTokenSet\n    ) -> UpstreamTokenSet:",
        "transparent_refresh_that_finds_the_grant_gone or (becomes_the_grant_only_once and transparent and stranger)",
    ),
    (
        "moa-52. load_access_token ignores what the transition learned (the SDK's fallback answers)",
        MCP_OAUTH,
        "        if validated is None or transition.outcome is not None:",
        "        if validated is None:",
        "transparent_refresh_that_finds_the_grant_gone",
    ),
    (
        "moa-53. a refused refresh response leaves the grant standing",
        MCP_OAUTH,
        '        if verdict.reason != "unavailable":',
        "        if False:",
        "becomes_the_grant_only_once and stranger",
    ),
    (
        "moa-54. the upstream ending audited as a client revocation",
        MCP_OAUTH,
        '                detail=f"client={transition.client_id} ended_by={ENDED_BY_UPSTREAM}",',
        '                detail=f"client={transition.client_id} presented=refresh_token",',
        "becomes_the_grant_only_once and forged",
    ),
    (
        "moa-55. the verified binding not written to the record (every refresh finds an unbound grant)",
        MCP_OAUTH,
        "        record.owner = binding\n",
        "        record.owner = None\n",
        "refresh_issues_a_new_pair_through_the_provider",
    ),
    (
        "moa-56. a new id_token stored unverified (the record's binding taken for it)",
        MCP_OAUTH,
        "            verdict = await self._proxy._owner_check.check(id_token)\n            if verdict.binding is None:\n                raise _GrantRefused(verdict)\n            if (verdict.binding.issuer",
        '            verdict = OwnerVerdict(established, "ok", established.subject)\n            if verdict.binding is None:\n                raise _GrantRefused(verdict)\n            if (verdict.binding.issuer',
        "becomes_the_grant_only_once and explicit and forged",
    ),
    # --- Codex #212 round 3: revocation's own lookup; the grant's identity (f9–f10) ------
    (
        "moa-57. revocation's lookup is the bearer's (the /revoke route not rebuilt over it)",
        MCP_OAUTH,
        "        routes = super().get_routes(mcp_path)\n        revocation = GrantRevocation(",
        "        routes = super().get_routes(mcp_path)\n        return routes\n        revocation = GrantRevocation(",
        "locates_its_grant_without_asking_the_provider and access_token",
    ),
    (
        "moa-58. the lookup consults the owner row (a grant the row no longer names cannot be ended)",
        MCP_OAUTH,
        '        jti = payload["jti"]\n        if await self._jti_mapping_store.get(key=jti) is None:\n            return None\n',
        '        jti = payload["jti"]\n        if not await self._owner_check.still_bound(binding):\n            return None\n        if await self._jti_mapping_store.get(key=jti) is None:\n            return None\n',
        "end_a_grant_the_owner_row_no_longer_names and access_token",
    ),
    (
        "moa-59. the gate adopts a candidate that names the owner now, not the grant's identity",
        MCP_OAUTH,
        "            if (verdict.binding.issuer, verdict.binding.subject) != (\n                established.issuer,\n                established.subject,\n            ):",
        "            if False:",
        "keeps_the_identity_that_authorized_the_grant",
    ),
    (
        "moa-60. the lookup's shell carries no client binding (the handler's ownership check never matches)",
        MCP_OAUTH,
        "        return AccessToken(\n            token=_reference(token),\n            client_id=client_id,",
        '        return AccessToken(\n            token=_reference(token),\n            client_id="",',
        "successful_revocation_kills_every_credential_of_the_grant and access_token",
    ),
    # --- Codex #212 round 4: one downstream client contract (f11–f13) -------------------------
    (
        "moa-61. the registration response left as the SDK built it (a secret advertised over a public client)",
        MCP_OAUTH,
        '        client_info.token_endpoint_auth_method = "none"\n        client_info.client_secret = None\n        client_info.client_secret_expires_at = None\n',
        "        pass\n",
        "every_dynamic_registration_is_a_public_client and client_secret_post",
    ),
    (
        "moa-62. the revocation form requires a secret again (the public form is 400)",
        MCP_OAUTH,
        "    token: str\n    token_type_hint:",
        "    token: str\n    client_secret: str\n    token_type_hint:",
        "every_dynamic_registration_is_a_public_client and absent",
    ),
    (
        "moa-63. the revocation authenticator is the SDK's plain one (private_key_jwt refused at /revoke)",
        MCP_OAUTH,
        "        if self._cimd_manager is None:  # pragma: no cover — CIMD is always on here",
        "        if True:  # pragma: no cover — CIMD is always on here",
        "cimd_client_authenticates_as_its_document_says and private_key_jwt",
    ),
    (
        "moa-64. a revocation assertion's audience is the token endpoint",
        MCP_OAUTH,
        "            self._client_authenticator(REVOCATION_PATH),\n        )\n        token = TokenHandler(",
        "            self._client_authenticator(TOKEN_PATH),\n        )\n        token = TokenHandler(",
        "private_key_jwt_client_is_refused_without_a_valid_assertion and revoke and wrong_audience",
    ),
    (
        "moa-65. the revocation handler skips the client-ownership check",
        MCP_OAUTH,
        "        if token is not None and token.client_id == client.client_id:",
        "        if token is not None:",
        "client_cannot_revoke_another_clients_grant",
    ),
    (
        "moa-66. a failed client authentication at /revoke answers 200",
        MCP_OAUTH,
        '            return PydanticJSONResponse(\n                status_code=401,\n                content=RevocationRefused(error="invalid_client", error_description=exc.message),',
        '            return PydanticJSONResponse(\n                status_code=200,\n                content=RevocationRefused(error="invalid_client", error_description=exc.message),',
        "private_key_jwt_client_is_refused_without_a_valid_assertion and revoke and absent",
    ),
    # --- Codex #212 round 5: discovery says the contract; the hint is advice (f14–f15) ------
    (
        "moa-67. discovery left as the SDK built it (the AS document not rebuilt over the contract)",
        MCP_OAUTH,
        '            elif isinstance(route, Route) and route.path.startswith(\n                "/.well-known/oauth-authorization-server"\n            ):',
        "            elif False:",
        "discovery_advertises_exactly_the_admitted_client_authentication",
    ),
    (
        "moa-68. the revocation endpoint's methods advertised as the SDK's shared-secret pair",
        MCP_OAUTH,
        "        metadata.revocation_endpoint_auth_methods_supported = list(CLIENT_AUTH_METHODS)",
        '        metadata.revocation_endpoint_auth_methods_supported = ["client_secret_post", "client_secret_basic"]',
        "discovery_advertises_exactly_the_admitted_client_authentication and openid",
    ),
    (
        "moa-69. no assertion algorithm advertised beside a JWT method",
        MCP_OAUTH,
        "        metadata.token_endpoint_auth_signing_alg_values_supported = list(\n            CLIENT_ASSERTION_ALGORITHMS\n        )",
        "        metadata.token_endpoint_auth_signing_alg_values_supported = None",
        "discovery_advertises_exactly_the_admitted_client_authentication and oauth-authorization",
    ),
    (
        "moa-70. the hint a requirement again (an unknown value is a 400)",
        MCP_OAUTH,
        "    token: str\n    token_type_hint: str | None = None",
        '    token: str\n    token_type_hint: Literal["access_token", "refresh_token"] | None = None',
        "hint_is_advice_and_either_half_ends_the_grant and unknown_type",
    ),
    # --- Codex #212 round 6: the protocol boundary, field by field (f16–f19) ------------------
    (
        "moa-71. the claim contract not applied (the SDK's authenticator alone judges the assertion)",
        MCP_OAUTH,
        # Re-anchored in round 8: the authenticator owns admission end to end now
        # (f29/f30), so "the SDK's alone" is the claim contract skipped in it.
        "                validate_client_assertion_claims(assertion, now=time.time())\n",
        "                pass\n",
        "claim_that_fails_the_contract_is_refused_first and nbf_future",
    ),
    (
        "moa-72. nbf not enforced",
        MCP_OAUTH,
        "    if not_before is not None and not_before > now + CLIENT_ASSERTION_SKEW:",
        "    if False:",
        "assertion_not_yet_valid_is_the_same_assertion_later and revoke",
    ),
    (
        "moa-73. jti not required to be a string (a list reaches the SDK's dictionary key)",
        MCP_OAUTH,
        '    for name in ("iss", "sub", "jti"):',
        '    for name in ("iss", "sub"):',
        "claim_that_fails_the_contract_is_refused_first and jti_list",
    ),
    (
        "moa-74. a boolean taken for a NumericDate",
        MCP_OAUTH,
        # Re-anchored in round 7 (f21 moved the finiteness check onto the range line).
        "    if isinstance(value, bool) or not isinstance(value, (int, float)):",
        "    if not isinstance(value, (int, float)):",
        "claim_that_fails_the_contract_is_refused_first and iat_bool",
    ),
    (
        "moa-75. a null redirect list not refused (FastMCP's localhost default invented)",
        MCP_OAUTH,
        "        if not client_info.redirect_uris:\n            raise RegistrationError(",
        "        if False:\n            raise RegistrationError(",
        "registration_response_describes_the_stored_client and null_redirects",
    ),
    (
        # Repaired in round 7 (f25): the previous replacement closed the `get`
        # call and left the `put`'s outer `)` behind — a SyntaxError at import,
        # counted as killed by nothing. The tuple below keeps the constructor's
        # closing parentheses by binding the two arguments to a name instead.
        "moa-76. the stored client not the admitted contract (FastMCP's record left standing)",
        MCP_OAUTH,
        "        await self._client_store.put(\n            key=client_info.client_id,\n            value=ProxyDCRClient(",
        "        _unwritten = (\n            client_info.client_id,\n            ProxyDCRClient(",
        "registration_response_describes_the_stored_client and display",
    ),
    (
        "moa-77. a repeated parameter not refused (the SDK's last value wins again)",
        MCP_OAUTH,
        "        if repeated:\n            return (",
        "        if False:\n            return (",
        "repeated_token_parameter_is_refused and client_id",
    ),
    (
        "moa-78. empty values not treated as omitted",
        MCP_OAUTH,
        '        pairs = [(name, value) for name, value in pairs if value != ""]',
        "        pairs = list(pairs)",
        "empty_value_is_an_omitted_one",
    ),
    (
        "moa-79. an omitted code_challenge_method left to the SDK's S256 default",
        MCP_OAUTH,
        '            pairs.append(("code_challenge_method", "plain"))',
        "            pass",
        "pkce_must_be_declared_s256 and absent",
    ),
    (
        "moa-80. the unregistered-client guidance left pointing at the pruned child alias",
        MCP_OAUTH,
        '        if "authorization_server_metadata" in body:\n            body["authorization_server_metadata"] = self._discovery_url',
        '        if False:\n            body["authorization_server_metadata"] = self._discovery_url',
        "unregistered_client_is_pointed_at_the_root_discovery_document",
    ),
    # --- Codex #212 round 7 (f20–f22, f24, f26, and the call-14 qualification):
    # --- admission, decoding, cardinality and the SDK hand-off together. -------
    (
        "moa-81. the media type read by a case-sensitive prefix, any other body passed through",
        MCP_OAUTH,
        "            if media_type.strip().lower() != FORM_MEDIA_TYPE:\n                await self._refuse(",
        '            if not media_type.startswith("application/x-www-form-urlencoded"):\n                await self.app(scope, self._replay(body), send)\n                return\n            if False:\n                await self._refuse(',
        "body_representation and mixed_case",
    ),
    (
        "moa-82. the NumericDate range not applied (the float conversion overflows)",
        MCP_OAUTH,
        "    if not (-NUMERIC_DATE_BOUND <= value <= NUMERIC_DATE_BOUND):",
        "    if not (-NUMERIC_DATE_BOUND <= value <= NUMERIC_DATE_BOUND) and False:",
        "claim_that_fails_the_contract_is_refused_first and exp_huge",
    ),
    (
        "moa-83. resource counted under the repetition rule again",
        MCP_OAUTH,
        "            name for name, count in counts.items() if count > 1 and name != RESOURCE_PARAMETER",
        "            name for name, count in counts.items() if count > 1",
        "resource_indicator_is_a_set and identical",
    ),
    (
        "moa-84. a set with a foreign target handed to the SDK as its first value (the wrong repair)",
        MCP_OAUTH,
        "        chosen = foreign[0] if foreign else resources[0]",
        "        chosen = resources[0]",
        "resource_indicator_is_a_set and authorize and foreign_last",
    ),
    (
        "moa-85. a foreign target at /token handed to the SDK, which reads the field and judges nothing",
        MCP_OAUTH,
        "        if foreign and self.endpoint == TOKEN_PATH:",
        "        if False:",
        "resource_indicator_is_a_set and token and foreign_only",
    ),
    (
        "moa-86. a second client authentication mechanism beside an assertion admitted",
        MCP_OAUTH,
        # Re-anchored in round 8 (the header inventory moved in front; f29).
        '        if presented and form.get("client_secret"):\n            raise AuthenticationError(',
        "        if False:\n            raise AuthenticationError(",
        "second_mechanism_beside_an_assertion and secret",
    ),
    (
        "moa-87. an assertion from a client not registered for private_key_jwt accepted unread",
        MCP_OAUTH,
        # Re-anchored in round 8 (dispatch by the snapshot's method; f30).
        "            if presented:\n                raise AuthenticationError(",
        "            if False:\n                raise AuthenticationError(",
        "assertion_from_a_client_not_registered_for_it and dcr",
    ),
    (
        "moa-88. the 401 to an HTTP-authenticating client without its challenge",
        MCP_OAUTH,
        "            if response.status_code == 401 and scheme is not None:",
        "            if False:",
        "second_mechanism_beside_an_assertion and basic",
    ),
    (
        "moa-89. jwks and jwks_uri admitted together",
        MCP_OAUTH,
        "        if client_info.jwks is not None and client_info.jwks_uri is not None:\n            raise RegistrationError(",
        "        if False:\n            raise RegistrationError(",
        "registration_response_describes_the_stored_client and both_key_sources",
    ),
    (
        "moa-90. invalid_target left to the SDK's vocabulary (server_error on the redirect)",
        MCP_OAUTH,
        # Re-anchored in round 8: the refusal is the proxy's own now (f27), so the
        # vocabulary mutant is its code.
        '                    error="invalid_target",\n                    error_description="this server issues tokens for its own resource only",',
        '                    error="server_error",\n                    error_description="this server issues tokens for its own resource only",',
        "resource_indicator_is_a_set and authorize and foreign_first",
    ),
    (
        "moa-91. a resource that does not parse handed to the SDK",
        MCP_OAUTH,
        "        if any(verdict is None for verdict in verdicts.values()):",
        "        if False:",
        "resource_indicator_is_a_set and authorize and unparseable",
    ),
    # --- Codex #212 round 8 (f27–f30): admitted once — recognised fields, every
    # --- credential occurrence, one client snapshot, the resource on the whole URI.
    (
        "moa-92. a fragment not refused (the normaliser's erasure again)",
        MCP_OAUTH,
        '    if "#" in value:\n        raise ValueError("a resource indicator must not include a fragment (RFC 8707 §2)")',
        '    if False:\n        raise ValueError("a resource indicator must not include a fragment (RFC 8707 §2)")',
        "resource_is_compared_on_the_whole_uri and token and fragment",
    ),
    (
        "moa-93. the path compared without its parameters",
        MCP_OAUTH,
        '    return parsed.scheme, parsed.netloc, parsed.path.rstrip("/")',
        '    return parsed.scheme, parsed.netloc, parsed.path.split(";", 1)[0].rstrip("/")',
        "resource_is_compared_on_the_whole_uri and token and path_parameter",
    ),
    (
        "moa-94. the owned resource decision not applied at /authorize (FastMCP's looser one decides)",
        MCP_OAUTH,
        "            if not accepted:\n                return construct_redirect_uri(",
        "            if False:\n                return construct_redirect_uri(",
        "resource_is_compared_on_the_whole_uri and authorize and path_parameter",
    ),
    (
        "moa-95. unknown parameters counted under the repetition rule",
        MCP_OAUTH,
        "        pairs = [(name, value) for name, value in pairs if name in self.recognised]",
        "        pairs = list(pairs)",
        "unknown_parameter_is_ignored and token",
    ),
    (
        "moa-96. an Authorization header ignored when no assertion is presented",
        MCP_OAUTH,
        "        if header_attempts:\n            raise AuthenticationError(",
        "        if header_attempts and presented:\n            raise AuthenticationError(",
        "http_authentication_attempt_is_refused and dcr and token and Basic",
    ),
    (
        "moa-97. only the first Authorization occurrence inventoried",
        MCP_OAUTH,
        '        header_attempts = request.headers.getlist("authorization")',
        '        header_attempts = [h for h in [request.headers.get("authorization", "")] if h]',
        "every_authorization_occurrence_counts and empty_first",
    ),
    (
        "moa-98. the client looked up a second time before dispatch",
        MCP_OAUTH,
        '        method = client.token_endpoint_auth_method\n        if method == "private_key_jwt":',
        '        client = await self.provider.get_client(client_id) or client\n        method = client.token_endpoint_auth_method\n        if method == "private_key_jwt":',
        "one_snapshot_per_request and none_then_private",
    ),
    (
        "moa-99. the challenge read from the first Authorization occurrence only",
        MCP_OAUTH,
        '    for header in request.headers.getlist("authorization"):',
        '    for header in [request.headers.get("authorization", "")]:',
        "every_authorization_occurrence_counts and empty_first",
    ),
    # --- Codex #212 round 9 (f31–f32): parsing is not validation; the inline key
    # --- set's contract in front of the SDK's extraction. ------------------------
    (
        "moa-100. the URI grammar not applied (urlsplit as validation again)",
        MCP_OAUTH,
        "    if not ABSOLUTE_URI.fullmatch(value):\n        raise ValueError(",
        "    if False:\n        raise ValueError(",
        "resource_is_compared_on_the_whole_uri and token and bad_percent",
    ),
    (
        "moa-101. the inline key set handed to the SDK's extraction unchecked",
        MCP_OAUTH,
        "            verifying = with_usable_inline_keys(client)",
        "            verifying = client",
        "malformed_inline_key_set and token and null_entry",
    ),
    (
        "moa-102. unusable entries not dropped from the set (RFC 7517 §5.1 not applied)",
        MCP_OAUTH,
        "    usable = [key for key in keys if isinstance(key, dict)]",
        "    usable = list(keys)",
        "malformed_inline_key_set and revoke and null_beside_key",
    ),
    (
        "moa-103. the filtered copy not handed to the validator",
        MCP_OAUTH,
        "    if len(usable) == len(keys):\n        return client\n    return client.model_copy(",
        "    if True:\n        return client\n    return client.model_copy(",
        "malformed_inline_key_set and token and null_beside_key",
    ),
]


pytestmark = pytest.mark.anyio


async def test_review_full_archive_with_local_quantity_drift_still_merges(client):
    """A coherent backup can be older than the populated instance it is merged into.

    The local copy has legitimately reduced this line from two kits to one through
    the Orders service.  Re-importing the older full archive has to restore both the
    old quantity and the kit that service edit removed.  This is the state where the
    `reconciled` marker matters: without it, the refusal compares the archive's two
    post-write kits with the local line's still-stored quantity of one.
    """
    from tests.test_order_invariants import kit_line, make_order, rest_line
    from tests.test_portability import apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    backup = (await client.get("/export/archive")).content

    changed = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [rest_line(order["items"][0], quantity=1)]},
    )
    assert changed.status_code == 200, changed.text
    assert len(changed.json()["items"][0]["kits"]) == 1

    plan = await preview(client, backup)
    assert plan["blocking_errors"] == [], plan
    restored = await apply(client, backup)
    assert restored.status_code == 200, restored.text
    line = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert line["quantity"] == 2
    assert len(line["kits"]) == 2


async def test_review_starter_sheet_reimport_ignores_local_kit_note_drift(client):
    """The starter sheet supplies a line quantity but no `kits.csv` move.

    Re-importing it after the spawned kit has acquired local-only detail must stay
    importable and must not flatten that detail merely to make the old sheet agree.
    """
    from app.services.portability import starter_sheet
    from tests.test_portability import apply, make_csv, preview

    content = make_csv(
        starter_sheet.STARTER_SHEET_HEADER,
        [
            {
                "kit_name": "Gouf Custom",
                "grade": "HG",
                "quantity": "1",
                "retailer": "Hobby Link Japan",
                "order_date": "2026-05-02",
                "order_number": "GB-STARTER",
                "unit_price": "19.99",
                "currency": "AUD",
                "received": "no",
            }
        ],
    )
    assert (await apply(client, content, filename="starter-sheet.csv")).status_code == 200
    kit = (await client.get("/kits")).json()[0]
    changed = await client.patch(f"/kits/{kit['id']}", json={"build_notes": "local note"})
    assert changed.status_code == 200, changed.text

    plan = await preview(client, content, filename="starter-sheet.csv")
    assert plan["blocking_errors"] == [], plan
    reapplied = await apply(client, content, filename="starter-sheet.csv")
    assert reapplied.status_code == 200, reapplied.text
    assert (await client.get(f"/kits/{kit['id']}")).json()["build_notes"] == "local note"


async def test_review_replace_all_result_does_not_depend_on_stored_line(client):
    """#45's boundary: the same replace-all upload must get the same preview before
    and after the row it will truncate is removed.

    The upload deliberately uses one id for a stored kit line and an arriving tool
    line.  Its two kits point at that arriving line.  Whether that graph should be
    accepted or diagnosed is a policy question about the upload; the old row may not
    decide it.  On the current head the stored line leaks through the allegedly dead
    lookup, and `_attached_after` adds its two soon-to-be-truncated kits to the two
    arriving ones.
    """
    import uuid

    from tests.test_order_invariants import archive, kit_line, make_order, order_row
    from tests.test_portability import preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    stored_line = order["items"][0]
    tool_id = str(uuid.uuid4())
    content = archive(
        {
            "retailers": ["id", "name"],
            "tools": ["id", "name", "category", "quantity_on_hand"],
            "orders": [
                "id",
                "retailer_id",
                "order_date",
                "order_number",
                "currency_code",
                "received_at",
            ],
            "order_items": [
                "id",
                "order_id",
                "item_type",
                "catalog_ref_id",
                "quantity",
                "unit_price_minor",
                "currency_code",
            ],
            "kits": ["id", "name", "grade", "order_item_id"],
        },
        retailers=[{"id": retailer["id"], "name": retailer["name"]}],
        tools=[
            {
                "id": tool_id,
                "name": "Nippers",
                "category": "cutting",
                "quantity_on_hand": "0",
            }
        ],
        orders=[order_row(order, retailer)],
        order_items=[
            {
                "id": stored_line["id"],
                "order_id": order["id"],
                "item_type": "tool",
                "catalog_ref_id": tool_id,
                "quantity": "2",
                "unit_price_minor": "1000",
                "currency_code": "JPY",
            }
        ],
        kits=[
            {
                "id": str(uuid.uuid4()),
                "name": f"Uploaded kit {number}",
                "grade": "HG",
                "order_item_id": stored_line["id"],
            }
            for number in (1, 2)
        ],
    )

    with_stored = await preview(client, content, mode="replace_all")
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    without_stored = await preview(client, content, mode="replace_all")

    def kit_errors(plan):
        table = next(table for table in plan["tables"] if table["table"] == "kits")
        # Whole diagnostics, codes and params included — the point is the two
        # plans agree, so compare everything the wire carries (#26).
        return [row["errors"] for row in table["rows"]]

    assert kit_errors(with_stored) == kit_errors(without_stored), {
        "with_stored": kit_errors(with_stored),
        "without_stored": kit_errors(without_stored),
    }
    assert with_stored["blocking_errors"] == without_stored["blocking_errors"]
    assert all(
        errors and "is a tool line" in errors[0]["detail"] for errors in kit_errors(without_stored)
    )


async def test_review_partial_line_without_quantity_does_not_authorize_a_kit_move(client):
    """Cross both ends of a move with both partial-line action shapes.

    Merely mentioning an order item is not the instruction that authorizes fan-out;
    stating its quantity is.  The current code marks both an UNCHANGED and an UPDATE
    row as reconciled before asking whether `quantity` was present.  The "onto" half
    also reaches `_plan_removals`, which correctly declines to remove anything on an
    unstated quantity, after which the refusal incorrectly skips the line.
    """
    from tests.test_order_invariants import archive, kit_line, make_order
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    observed = []
    sequence = 0
    for direction in ("onto", "off"):
        for line_changes in (False, True):
            sequence += 1
            order = await make_order(
                client,
                retailer,
                [kit_line(1)],
                number=f"HLJ-PARTIAL-{sequence}",
            )
            item = order["items"][0]
            if direction == "onto":
                subject = (
                    await client.post(
                        "/kits",
                        json={"name": "Loose Gouf", "grade": "HG", "status": "backlog"},
                    )
                ).json()
                parent = item["id"]
            else:
                subject = item["kits"][0]
                parent = ""

            content = archive(
                {
                    "order_items": [
                        "id",
                        "order_id",
                        "item_type",
                        "unit_price_minor",
                    ],
                    "kits": ["id", "name", "grade", "order_item_id"],
                },
                order_items=[
                    {
                        "id": item["id"],
                        "order_id": order["id"],
                        "item_type": "kit",
                        "unit_price_minor": "2801" if line_changes else "2800",
                    }
                ],
                kits=[
                    {
                        "id": subject["id"],
                        "name": subject["name"],
                        "grade": "HG",
                        "order_item_id": parent,
                    }
                ],
            )
            plan = await preview(client, content)
            response = await apply(client, content)
            stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
            observed.append(
                (
                    direction,
                    "update" if line_changes else "unchanged",
                    actions(plan, "order_items")[0],
                    actions(plan, "kits")[0],
                    response.status_code,
                    len(stored["kits"]),
                )
            )

    assert observed == [
        (direction, line_action, line_action, "error", 409, 1)
        for direction in ("onto", "off")
        for line_action in ("unchanged", "update")
    ], observed


async def test_review_kits_cannot_attach_to_a_catalog_order_line(client):
    """The attachment target has a type as well as an id.

    REST and MCP never expose `order_item_id` on a kit write, and only kit order
    lines spawn kits.  Import currently resolves the foreign key and then explicitly
    skips non-kit targets in the new refusal, so both an UPDATE and a CREATE can make
    a catalog purchase line claim kits it never bought.
    """
    from tests.test_order_invariants import (
        archive,
        consumable_line,
        make_consumable,
        make_order,
    )
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"], quantity=1)])
    catalog_line = order["items"][0]
    loose = (
        await client.post(
            "/kits",
            json={"name": "Loose Gouf", "grade": "HG", "status": "backlog"},
        )
    ).json()

    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        kits=[
            {
                "id": loose["id"],
                "name": loose["name"],
                "grade": "HG",
                "order_item_id": catalog_line["id"],
            },
            {
                "id": "",
                "name": "New Zaku",
                "grade": "HG",
                "order_item_id": catalog_line["id"],
            },
        ],
    )
    plan = await preview(client, content)
    response = await apply(client, content)
    kits = (await client.get("/kits")).json()

    observed = (
        actions(plan, "kits"),
        response.status_code,
        sorted(kit["order_item_id"] for kit in kits),
    )
    assert observed == (["error", "error"], 409, [None]), observed


async def test_review_refused_move_does_not_leave_a_removal_in_the_plan(client):
    """The refusal runs after reconciliation has already planned destructive work.

    Moving A's kit onto B while restating only B's quantity makes B give up its own
    kit.  The later both-ends check then refuses the move because A would be empty.
    Once that row is ERROR, B's removal was derived from a move that cannot land and
    must not remain in the preview or its fingerprint.
    """
    from tests.test_order_invariants import archive, kit_line, line_row, make_order
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(
        client,
        retailer,
        [kit_line(1, name="Source Zaku"), kit_line(1, name="Destination Gouf")],
    )
    source, destination = order["items"]
    moved = source["kits"][0]
    original_kit_ids = {source["kits"][0]["id"], destination["kits"][0]["id"]}
    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[line_row(order, destination, quantity="1")],
        kits=[
            {
                "id": moved["id"],
                "name": moved["name"],
                "grade": "HG",
                "order_item_id": destination["id"],
            }
        ],
    )

    plan = await preview(client, content)
    response = await apply(client, content)
    observed = (
        actions(plan, "kits"),
        plan["derived"]["kits_removed"],
        response.status_code,
        {kit["id"] for kit in (await client.get("/kits")).json()} == original_kit_ids,
    )
    assert observed == (["error"], 0, 409, True), observed


async def test_review_add_only_uses_stored_line_not_skipped_upload(client):
    """A skipped order-items row describes nothing that will land.

    The stored line says quantity one.  The add-only upload says two, but that row
    is SKIP, then creates a second attached kit.  Reading the skipped row would
    make the count look reconciled while applying only the kit create, leaving the
    stored quantity at one.
    """
    from tests.test_order_invariants import archive, kit_line, line_row, make_order
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]
    content = archive(
        {"kits": ["name", "grade", "order_item_id"]},
        order_items=[line_row(order, item, quantity="2")],
        kits=[{"name": "Extra", "grade": "HG", "order_item_id": item["id"]}],
    )

    plan = await preview(client, content, mode="add_only")
    response = await apply(client, content, mode="add_only")
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    observed = (
        actions(plan, "order_items"),
        actions(plan, "kits"),
        response.status_code,
        stored["quantity"],
        len(stored["kits"]),
    )
    assert observed == (["skip"], ["error"], 409, 1, 1), observed


async def test_review_a_progressed_kit_cannot_trade_away_its_order_provenance(client):
    """Keeping the line's count does not make every provenance move safe.

    REST order edits refuse to delete a progressed spawned kit, and KitUpdate does
    not expose order_item_id.  A kits sheet can currently detach that same kit and
    attach a fresh replacement in one upload: the line still holds one kit, so the
    count-only refusal accepts it, but the progressed kit's purchase record is
    gone.  Cross both a kit already building and one made building by the same row.
    """
    from tests.test_order_invariants import archive, kit_line, make_order
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    observed = []
    for variant in ("already progressed", "progressed by upload"):
        order = await make_order(
            client,
            retailer,
            [kit_line(1, name=f"{variant} original")],
            number=variant,
        )
        line = order["items"][0]
        original = line["kits"][0]
        delete_before = None
        if variant == "already progressed":
            changed = await client.patch(f"/kits/{original['id']}", json={"status": "building"})
            assert changed.status_code == 200, changed.text
            original = changed.json()
            delete_before = (await client.delete(f"/orders/{order['id']}")).status_code
            assert delete_before == 409, "the Orders service protects this kit"

        content = archive(
            {"kits": ["id", "name", "grade", "status", "order_item_id"]},
            kits=[
                {
                    "id": original["id"],
                    "name": original["name"],
                    "grade": "HG",
                    "status": "building",
                    "order_item_id": "",
                },
                {
                    "id": "",
                    "name": f"{variant} replacement",
                    "grade": "HG",
                    "status": "ordered",
                    "order_item_id": line["id"],
                },
            ],
        )
        plan = await preview(client, content)
        response = await apply(client, content)
        stored_original = (await client.get(f"/kits/{original['id']}")).json()
        stored_line = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
        delete_after = None
        if variant == "already progressed":
            delete_after = (await client.delete(f"/orders/{order['id']}")).status_code
        observed.append(
            (
                variant,
                actions(plan, "kits"),
                bool(plan["blocking_errors"]),
                response.status_code,
                stored_original["status"] == original["status"],
                stored_original["order_item_id"] == line["id"],
                [kit["id"] for kit in stored_line["kits"]] == [original["id"]],
                delete_before,
                delete_after,
            )
        )

    unsafe = [
        result
        for result in observed
        if not (
            result[2]  # preview blocked
            and result[3] == 409
            and result[4]  # a rejected row did not also move the status
            and result[5]  # the purchase provenance stayed on the original kit
            and result[6]  # the line still owns that original, not a replacement
            and (result[0] != "already progressed" or result[7:] == (409, 409))
        )
    ]
    assert unsafe == [], observed


async def test_review_a_planned_upgrade_application_protects_its_kit_from_removal(client):
    """Removal safety has to read the post-write graph, not just stored evidence.

    The shared matrix covers an upgrade application already in the database.  A
    new application is processed later in this same import, so `kit_progressed`
    cannot see it while `_plan_removals` chooses a victim.  Apply creates the
    application and then deletes its kit; ON DELETE CASCADE erases the row the
    preview said would be created.  There is another unprogressed kit available,
    so the correct plan can remove that one instead of refusing the import.
    """
    from tests.test_order_invariants import archive, kit_line, line_row, make_order
    from tests.test_portability import actions, apply, preview, read_archive

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    line = order["items"][0]
    protected = line["kits"][-1]  # current removal order chooses newest first
    other = line["kits"][0]
    upgrade = (
        await client.post(
            "/upgrades",
            json={
                "name": "Metal thruster",
                "manufacturer": "Kotobukiya",
                "quantity_on_hand": 4,
            },
        )
    ).json()

    content = archive(
        {
            "upgrade_applications": [
                "id",
                "upgrade_id",
                "kit_id",
                "quantity_used",
            ]
        },
        order_items=[line_row(order, line, quantity="1")],
        upgrade_applications=[
            {
                "id": "",
                "upgrade_id": upgrade["id"],
                "kit_id": protected["id"],
                "quantity_used": "1",
            }
        ],
    )

    plan = await preview(client, content)
    response = await apply(client, content)
    exported = read_archive((await client.get("/export/archive")).content)
    remaining_ids = {kit["id"] for kit in (await client.get("/kits")).json()}
    observed = (
        actions(plan, "order_items"),
        actions(plan, "upgrade_applications"),
        plan["derived"]["kits_removed"],
        response.status_code,
        protected["id"] in remaining_ids,
        other["id"] in remaining_ids,
        [row["kit_id"] for row in exported["upgrade_applications"]],
    )
    assert observed == (
        ["update"],
        ["create"],
        1,
        200,
        True,
        False,
        [protected["id"]],
    ), observed


async def test_review_a_planned_photo_protects_its_kit_from_removal(client):
    """The other later-table half of the same post-write progression rule."""
    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.models import KitPhoto
    from tests.test_order_invariants import archive, kit_line, line_row, make_order
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    line = order["items"][0]
    protected = line["kits"][-1]
    other = line["kits"][0]
    content = archive(
        {"kit_photos": ["id", "kit_id", "file_path"]},
        order_items=[line_row(order, line, quantity="1")],
        kit_photos=[
            {
                "id": "",
                "kit_id": protected["id"],
                "file_path": "kits/protected/front.jpg",
            }
        ],
    )

    plan = await preview(client, content)
    response = await apply(client, content)
    async with get_sessionmaker()() as session:
        photo_parents = [str(value) for value in await session.scalars(select(KitPhoto.kit_id))]
    remaining_ids = {kit["id"] for kit in (await client.get("/kits")).json()}
    observed = (
        actions(plan, "order_items"),
        actions(plan, "kit_photos"),
        plan["derived"]["kits_removed"],
        response.status_code,
        protected["id"] in remaining_ids,
        other["id"] in remaining_ids,
        photo_parents,
    )
    assert observed == (
        ["update"],
        ["create"],
        1,
        200,
        True,
        False,
        [protected["id"]],
    ), observed


async def test_review_rating_this_upload_writes_protects_provenance(client):
    """Exercise planned rating without status, stored evidence, or a count refusal.

    The source line is restated, not written, so it authorises nothing; a
    replacement kit created on it keeps its count at one so the move is not
    refused for leaving it empty. Only the provenance rule can refuse this.
    """
    from tests.test_order_invariants import archive, kit_line, line_row, make_order
    from tests.test_portability import apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    source = await make_order(client, retailer, [kit_line(1)], number="RATING-SOURCE")
    destination = await make_order(
        client, retailer, [kit_line(1, name="Gouf")], number="RATING-DEST"
    )
    source_line = source["items"][0]
    destination_line = destination["items"][0]
    moved = source_line["kits"][0]

    content = archive(
        {"kits": ["id", "name", "grade", "rating", "order_item_id"]},
        order_items=[
            line_row(source, source_line, quantity="1"),
            line_row(destination, destination_line, quantity="2", kit_name="Gouf"),
        ],
        kits=[
            {
                "id": moved["id"],
                "name": moved["name"],
                "grade": moved["grade"],
                "rating": "5",
                "order_item_id": destination_line["id"],
            },
            {
                "id": "",
                "name": "Replacement",
                "grade": "HG",
                "rating": "",
                "order_item_id": source_line["id"],
            },
        ],
    )
    plan = await preview(client, content)
    response = await apply(client, content)
    stored = (await client.get(f"/kits/{moved['id']}")).json()
    kits_plan = next(t for t in plan["tables"] if t["table"] == "kits")
    moved_row = next(r for r in kits_plan["rows"] if r["matched_id"] == moved["id"])
    observed = (
        moved_row["action"],
        any("building or complete, rated" in d["detail"] for d in moved_row["errors"]),
        response.status_code,
        stored["rating"],
        stored["order_item_id"],
    )
    assert observed == ("error", True, 409, None, source_line["id"]), observed


@pytest.mark.parametrize("child", ["upgrade_applications", "kit_photos"])
async def test_review_a_planned_child_move_protects_its_new_kit_from_removal(client, child):
    """A child UPDATE can make a second kit progressed just as surely as CREATE.

    Seed one child on a loose kit, then move that existing row by explicit id onto
    the newest kit of a quantity-two order while the same archive reduces the line
    to one.  The child UPDATE is written before planned removals run.  If the new
    parent is not in the post-write protection set, the result reports the update
    and then ON DELETE CASCADE erases it with the chosen kit.
    """
    import uuid

    from app.db import get_sessionmaker
    from app.models import KitPhoto, UpgradeApplication
    from tests.test_order_invariants import archive, kit_line, line_row, make_order
    from tests.test_portability import actions, apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    line = order["items"][0]
    safe, destination = line["kits"]
    source = (
        await client.post(
            "/kits", json={"name": f"{child} source", "grade": "HG", "status": "backlog"}
        )
    ).json()
    child_id = str(uuid.uuid4())

    if child == "upgrade_applications":
        upgrade = (
            await client.post(
                "/upgrades",
                json={
                    "name": "Moved thruster",
                    "manufacturer": "Kotobukiya",
                    "quantity_on_hand": 4,
                },
            )
        ).json()
        application = (
            await client.post(
                f"/upgrades/{upgrade['id']}/apply",
                json={"kit_id": source["id"], "quantity": 1},
            )
        ).json()
        child_id = application["id"]
        first = None
        moved_row = {
            "id": child_id,
            "upgrade_id": upgrade["id"],
            "kit_id": destination["id"],
            "quantity_used": "1",
        }
        model = UpgradeApplication
    else:
        first = archive(
            {"kit_photos": ["id", "kit_id", "file_path"]},
            kit_photos=[
                {
                    "id": child_id,
                    "kit_id": source["id"],
                    "file_path": "kits/moved/front.jpg",
                }
            ],
        )
        moved_row = {
            "id": child_id,
            "kit_id": destination["id"],
            "file_path": "kits/moved/front.jpg",
        }
        model = KitPhoto

    if first is not None:
        assert (await apply(client, first)).status_code == 200
    second = archive(
        {child: list(moved_row)},
        order_items=[line_row(order, line, quantity="1")],
        **{child: [moved_row]},
    )
    plan = await preview(client, second)
    response = await apply(client, second)

    async with get_sessionmaker()() as session:
        stored_child = await session.get(model, uuid.UUID(child_id))
        stored_parent = str(stored_child.kit_id) if stored_child is not None else None
    survivors = {kit["id"] for kit in (await client.get("/kits")).json()}
    spent_stock = None
    if child == "upgrade_applications":
        spent_stock = next(
            row["quantity_on_hand"]
            for row in (await client.get("/upgrades")).json()
            if row["id"] == upgrade["id"]
        )
    observed = (
        actions(plan, "order_items"),
        actions(plan, child),
        plan["derived"]["kits_removed"],
        response.status_code,
        destination["id"] in survivors,
        safe["id"] in survivors,
        stored_parent,
        spent_stock,
    )
    assert observed == (
        ["update"],
        ["update"],
        1,
        200,
        True,
        False,
        destination["id"],
        3 if child == "upgrade_applications" else None,
    ), observed


async def test_review_a_planned_child_move_protects_its_new_kits_provenance(client):
    """The same omitted child UPDATE also reaches the provenance consumer.

    Move an already-applied upgrade from a loose source onto an order-spawned kit,
    detach that kit, and attach a fresh replacement so the line count remains one.
    Only the post-write child makes the departing kit protected; no count check or
    stored progression evidence can refuse on its behalf.
    """
    import uuid

    from app.db import get_sessionmaker
    from app.models import UpgradeApplication
    from tests.test_order_invariants import archive, kit_line, make_order
    from tests.test_portability import apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    line = order["items"][0]
    departing = line["kits"][0]
    source = (
        await client.post(
            "/kits", json={"name": "Application source", "grade": "HG", "status": "backlog"}
        )
    ).json()
    upgrade = (
        await client.post(
            "/upgrades",
            json={
                "name": "Applied thruster",
                "manufacturer": "Kotobukiya",
                "quantity_on_hand": 2,
            },
        )
    ).json()
    application = (
        await client.post(
            f"/upgrades/{upgrade['id']}/apply",
            json={"kit_id": source["id"], "quantity": 1},
        )
    ).json()

    content = archive(
        {
            "kits": ["id", "name", "grade", "order_item_id"],
            "upgrade_applications": ["id", "upgrade_id", "kit_id", "quantity_used"],
        },
        kits=[
            {
                "id": departing["id"],
                "name": departing["name"],
                "grade": departing["grade"],
                "order_item_id": "",
            },
            {
                "id": "",
                "name": "Replacement",
                "grade": "HG",
                "order_item_id": line["id"],
            },
        ],
        upgrade_applications=[
            {
                "id": application["id"],
                "upgrade_id": upgrade["id"],
                "kit_id": departing["id"],
                "quantity_used": "1",
            }
        ],
    )
    plan = await preview(client, content)
    response = await apply(client, content)
    stored_departing = (await client.get(f"/kits/{departing['id']}")).json()
    async with get_sessionmaker()() as session:
        stored_application = await session.get(UpgradeApplication, uuid.UUID(application["id"]))
        application_parent = (
            str(stored_application.kit_id) if stored_application is not None else None
        )
    delete_status = None
    if response.status_code == 200:
        delete_status = (await client.delete(f"/orders/{order['id']}")).status_code
    observed = (
        bool(plan["blocking_errors"]),
        response.status_code,
        stored_departing["order_item_id"],
        application_parent,
        delete_status,
    )
    assert observed == (True, 409, line["id"], source["id"], None), observed


@pytest.mark.parametrize("mode", ["merge", "add_only", "replace_all"])
async def test_review_a_new_line_refuses_more_uploaded_kits_than_its_quantity(client, mode):
    """A CREATE line has no stored target, but a detected surplus is still an error.

    Two explicit kits and quantity one contradict each other.  There is no stored
    victim to remove, so the planner must refuse the upload rather than return from
    `_plan_removals` and apply the contradiction unchanged.
    """
    import uuid

    from tests.test_order_invariants import archive, kit_line, make_order, order_row
    from tests.test_portability import apply, preview

    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)], number=f"NEW-{mode}")
    line_id = str(uuid.uuid4())
    tables = {
        "order_items": [
            {
                "id": line_id,
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "2800",
                "currency_code": "JPY",
                "kit_name": "Uploaded Zaku",
                "kit_grade": "HG",
            }
        ],
        "kits": [
            {
                "id": str(uuid.uuid4()),
                "name": f"Uploaded Zaku {number}",
                "grade": "HG",
                "order_item_id": line_id,
            }
            for number in (1, 2)
        ],
    }
    if mode == "replace_all":
        tables = {
            "retailers": [{"id": retailer["id"], "name": retailer["name"]}],
            "orders": [order_row(order, retailer)],
            **tables,
        }
    content = archive({"kits": ["id", "name", "grade", "order_item_id"]}, **tables)

    plan = await preview(client, content, mode=mode)
    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    response = await apply(client, content, mode=mode, **extra)
    stored_order = (await client.get(f"/orders/{order['id']}")).json()
    stored_line = next((item for item in stored_order["items"] if item["id"] == line_id), None)
    observed = (
        bool(plan["blocking_errors"]),
        plan["derived"]["kits_removed"],
        response.status_code,
        (stored_line["quantity"], len(stored_line["kits"])) if stored_line else None,
    )
    assert observed == (True, 0, 409, None), observed


#: Every file a case's `-k` expression may name. A literal list, not a glob: the
#: point is that a case whose expression matches nothing here is *reported*, and a
#: glob would quietly widen the search instead. Extend it when a case's tests
#: live somewhere new. It has been wrong once already — this branch's set named
#: `test_order_invariants.py`, `main`'s named `test_cell_semantics.py`, and the
#: merge kept one list under the union of both case sets, so every `cell-`
#: mutant selected zero tests and pytest's exit 5 read as a kill.
TEST_FILES = [
    "tests/test_order_invariants.py",
    "tests/test_cell_semantics.py",
    "tests/test_portability.py",
    # The fold-in of the #109/#111/#113/#115 queues widened the case set to the
    # suites those branches wrote; each file below is named by at least one
    # case's `-k` expression, and the exit-5 NONE rule is what notices if one of
    # these ever stops being.
    "tests/test_name_uniqueness.py",
    "tests/test_name_matching.py",
    "tests/test_receipt_dates.py",
    "tests/test_build_dates.py",
    "tests/test_series.py",
    "tests/test_mcp_order_edit.py",
    "tests/test_ship_dates.py",
    # The #129 (dsp-) and #130 (cat-) fold-in — same rule as above: each file is
    # named by at least one case's `-k` expression.
    "tests/test_inventory.py",
    "tests/test_orders.py",
    "tests/test_write_surface_parity.py",
    "tests/test_catalog_categories.py",
    "tests/test_mcp_catalog_create.py",
    # The #149 (wdr-) fold-in: wdr-11's tests live in test_mcp.py, and wdr-6
    # names a second kill site in test_order_lifecycle.py (review P3-1).
    "tests/test_mcp.py",
    "tests/test_order_lifecycle.py",
    # The #169 (env-) fold-in: every env- kill lives here.
    "tests/test_error_envelope.py",
    # The #151 (mig-) fold-in.
    "tests/test_migration_data.py",
    # The #156 (d63-) fold-in.
    "tests/test_integrity.py",
    # The #159 (stg-) fold-in — the instance-settings singleton (#23). The
    # reference-currency suite joined because stg-14's and stg-19's kills live
    # there since the round-1 class sweep.
    "tests/test_settings.py",
    "tests/test_settings_portability.py",
    "tests/test_reference_currency.py",
    # The #26 (nd-) fold-in: every nd- kill lives here.
    "tests/test_import_diagnostics.py",
    # The #114 (tz-) fold-in.
    "tests/test_naive_csv_dates.py",
    # The #186 (ingr-) fold-in: every ingr- kill lives here, the sh ones included.
    "tests/test_ingress.py",
    # The #187 (auth-) fold-in: the four auth modules — each named by at least one
    # auth- expression (the generation suite by auth-41/42). The session-level
    # migration walk in conftest is what applies the auth-39/40 migration mutants.
    "tests/test_route_policy.py",
    "tests/test_auth_tables.py",
    "tests/test_authorization.py",
    "tests/test_ingress_generation.py",
    # The #188 (m63-) fold-in: every m63- kill lives here.
    "tests/test_auth_local.py",
    # The #189 (pat-) fold-in: the token suite; pat-12/16/23 also kill in
    # test_route_policy.py / test_authorization.py, listed above.
    "tests/test_auth_tokens.py",
    # The #204 (f13-) fold-in: every f13- kill lives here, bar f13-11's second
    # witness in test_authorization.py (already listed).
    "tests/test_auth_unrouted.py",
    "tests/test_auth_oidc.py",
    # The #192 (moa-) set: MCP OAuth — every moa- kill lives here or in the
    # route-policy / unrouted / oidc suites above; moa-61…66 (the client
    # contract, Codex round 4) kill in the wire-level contract suite.
    "tests/test_mcp_oauth.py",
    "tests/test_mcp_oauth_clients.py",
]

#: pytest's exit status when collection found tests but `-k` deselected them all.
#: Non-zero, and not a failure — a harness that reads "anything but 0" as a kill
#: reports a mutant nothing ran against as killed. Same trap as an empty
#: parametrize being a skip (`.agents/lessons.md`), one layer further out.
NO_TESTS_SELECTED = 5


def run(expr: str) -> tuple[int, str]:
    if expr.startswith("review_"):
        targets = ["-p", "tests.conftest", "mutation_test.py"]
    else:
        targets = list(TEST_FILES)
    proc = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            *targets,
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
        # str(FIX): oma-2 mutates the shared registry fixture over in
        # frontend/, which "app tests alembic" never covered — a failed restore
        # there was invisible before this fold-in.
        # str(ENVSH): ingr-25/26 mutate the nginx server-name generator, a shell
        # file under frontend/ — same reason.
        ["git", "status", "--porcelain", "app", "tests", "alembic", str(FIX), str(ENVSH)],
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
        print("app/, tests/, alembic/, the shared error-codes fixture or the nginx server-")
        print("name generator has uncommitted changes — commit or stash first, so that a")
        print("restore that doesn't happen is")
        print("visible rather than mixed in with your edits.")
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
        # The unmutated selection has to PASS before the mutant means anything
        # (#117 review, P3-1): a broken environment — a test DB migrated past
        # this tree's alembic head, a stale fixture — fails every selection
        # before the named assertion runs, and "any non-zero exit is a kill"
        # counted exactly that as 63 kills once. This also subsumes the NONE
        # check: exit 5 on a clean tree means the expression selects nothing.
        base_code, base_summary = run(expr)
        if base_code == NO_TESTS_SELECTED:
            print(
                f"NONE  {label}\n        -> -k {expr!r} selected no test in {', '.join(TEST_FILES)}"
            )
            failures.append(label)
            continue
        if base_code != 0:
            print(f"SICK  {label}\n        -> unmutated selection did not pass: {base_summary}")
            failures.append(label)
            continue
        backup = tempfile.mktemp()
        shutil.copy(path, backup)
        try:
            path.write_text(original.replace(old, new))
            code, summary = run(expr)
        finally:
            shutil.copy(backup, path)
        if code == 0:
            print(f"GREEN {label}\n        -> {summary}")
            failures.append(label)
            continue
        # A kill is a test FAILURE on the named assertion — pytest exit 1 with a
        # summary saying "failed" and no errors. A mutant that stops the file
        # importing, or breaks collection, produces errors, not failures, and an
        # error proves the mutant is a syntax accident rather than a semantic
        # fault the suite caught (#117 review, P3-1: cell-4 was "killed" by an
        # IndentationError for its whole life).
        killed = code == 1 and "failed" in summary and "error" not in summary
        if killed:
            print(f"RED   {label}\n        -> {summary}")
        else:
            print(f"ERROR {label}\n        -> exit {code}: {summary}")
            failures.append(label)
    if not tree_is_clean():
        print("\nWARNING: the tree is dirty after the run — a restore failed. `git diff`.")
        return 2
    if failures:
        print("\nFAILURES (surviving, sick, none, or error — each one a finding):")
        print(*(f"  - {label}" for label in failures), sep="\n")
        return 1
    print(f"\nall {len(selected)} mutants were killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
twice, that a line's quantity matches the kits attached to it. Nothing here is an
access control; the application has no authentication at all yet (milestone 6).

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
        '        f"receipt was a mistake, delete the order — that reverses the stock it applied — "',
        '        f"receipt was a mistake, ask someone — "',
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
        "    def _error_rows(rows: list[_Row], message: str) -> None:\n"
        "        for row in rows:\n"
        "            row.action = RowAction.ERROR\n"
        "            row.error = message",
        "    @staticmethod\n"
        "    def _error_rows(rows: list[_Row], message: str) -> None:\n"
        "        for row in rows:\n"
        "            row.error = message",
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
        '    if not cleaned:\n        raise InvalidInputError("name cannot be blank")',
        "    pass",
        "whitespace_only or rename_to_blank or blank_retailer",
    ),
    (
        "n6a. clean_name stops stripping",
        NAMES,
        '        raise InvalidInputError("name cannot be blank")\n    return cleaned\n',
        '        raise InvalidInputError("name cannot be blank")\n    return name\n',
        "different-padded or Gundam_Base or creates_it_stripped or padded-input",
    ),
    (
        "n6b. require_unique_name hands back the raw name",
        NAMES,
        "        )\n    return cleaned\n",
        "        )\n    return name\n",
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
        '                f"{model.__tablename__} have no category column, so they cannot be filtered by one"\n'
        "            )",
        "            pass  # neutered",
        "refuses_category_asks_that_have_no_answer",
    ),
    (
        "cat-14. vocabulary's no-column refusal off",
        CAT,
        "        raise InvalidInputError(\n"
        '            f"{model.__tablename__} have no category column, so there is no "\n'
        '            "category vocabulary to list"\n'
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
        "                        f\"category '{value}' will be stored as '{vocab[key]}', \"\n"
        '                        "matching the spelling already in use"\n'
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
        "            self.blocking.append(str(exc))",
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
        return [row["error"] for row in table["rows"]]

    assert kit_errors(with_stored) == kit_errors(without_stored), {
        "with_stored": kit_errors(with_stored),
        "without_stored": kit_errors(without_stored),
    }
    assert with_stored["blocking_errors"] == without_stored["blocking_errors"]
    assert all(error and "is a tool line" in error for error in kit_errors(without_stored))


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
        "building or complete, rated" in (moved_row["error"] or ""),
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

"""Behaviour scenarios, shared with plamotrack-ios (#307).

The golden archive (#303) pins the archive's *shape*; it cannot see an archive
that is well-formed but carries the result of a rule copied wrong. A scenario
pins *behaviour*: a starting collection, the operations run on it, and the
collection it must leave behind or the refusal it must get. This file runs every
scenario in `tests/fixtures/scenarios/*.json` against the service layer; the
iOS app runs the same files against its Swift domain layer, so a rule the two
implement differently fails on at least one side.

The format is `scenario.schema.json` beside the files, and the prose is in
`.agents/testing-and-review.md` → "Behaviour scenarios". In short:

- `given` is the starting collection in the archive's table and column names,
  typed JSON, ids as handles (`@orders:hlj`). It is inserted directly — not
  imported — so an importer defect cannot turn every scenario red.
- each step calls one service function; it expects `ok` or a refusal
  `{kind, code, params}`, `params` compared on the keys `api-error-codes.json`
  declares for the code (what the wire contract promises; a raise may send more).
- `then` compares each listed table whole (row count, then each expected row
  matched by `id` or by its listed fields, listed fields only); every table it
  does not list must be exactly as `given` left it. `"unchanged"` is the lot.
- `"@now"` matches an instant inside the scenario's run: the services read the
  clock inline, so there is nothing to freeze. An exact instant goes in `args`.
"""

import csv
import io
import json
import re
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from sqlalchemy import select

from app.db import session_scope
from app.exceptions import ConflictError, DomainError, InvalidInputError, NotFoundError
from app.models import InstanceSettings
from app.models.enums import ItemType
from app.schemas.catalog import (
    ConsumableCreate,
    ConsumableUpdate,
    DisplayItemCreate,
    DisplayItemUpdate,
    ToolCreate,
    ToolUpdate,
    UpgradeCreate,
    UpgradeUpdate,
)
from app.schemas.kits import KitUpdate
from app.schemas.orders import OrderCreate, OrderUpdate, RetailerCreate, RetailerUpdate
from app.schemas.portability import ImportMode
from app.services import catalog, kits, orders, upgrades
from app.services.portability import exporting, importing, spec

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
SCHEMA = json.loads((FIXTURES / "scenario.schema.json").read_text(encoding="utf-8"))
REGISTRY = json.loads(
    (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/__fixtures__/api-error-codes.json"
    ).read_text(encoding="utf-8")
)["codes"]

#: Handles become `uuid5(NAMESPACE, "<scenario id>/<handle>")`: stable for a
#: scenario, distinct between scenarios.
NAMESPACE = uuid.UUID("2a0c3f1e-6b7d-5e4f-8a9b-0c1d2e3f4307")
HANDLE = re.compile(r"^@[a-z_]+:[a-z0-9_-]+$")
NOW = "@now"
#: How far `@now` may sit outside the scenario's run: the database's clock (which
#: stamps some columns itself) and this process's are not the same clock.
CLOCK_SLACK = timedelta(seconds=5)

KIND = {NotFoundError: "not_found", ConflictError: "conflict", InvalidInputError: "invalid_input"}


SCHEMA_FILE = "scenario.schema.json"


def load_files() -> dict[str, dict]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(FIXTURES.glob("*.json"))
        if path.name != SCHEMA_FILE
    }


FILES = load_files()
SCENARIOS = [scenario for data in FILES.values() for scenario in data["scenarios"]]


# --- handles and values ----------------------------------------------------------


class Handles:
    """One scenario's handle -> uuid map. `bind` adds a record a step created."""

    def __init__(self, scenario_id: str):
        self.scenario_id = scenario_id
        self.bound: dict[str, uuid.UUID] = {}

    def __getitem__(self, handle: str) -> uuid.UUID:
        if handle not in self.bound:
            self.bound[handle] = uuid.uuid5(NAMESPACE, f"{self.scenario_id}/{handle}")
        return self.bound[handle]

    def bind(self, handle: str, value: uuid.UUID) -> None:
        assert handle not in self.bound, f"{handle} is already bound"
        self.bound[handle] = value

    def resolve(self, value: Any) -> Any:
        """Handles anywhere inside `value` become uuids."""
        if isinstance(value, str) and HANDLE.match(value):
            return self[value]
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        return value


def cell(value: Any) -> str:
    """A typed JSON value as the archive spells it — the vocabulary `given` and
    `then` share with the CSV (#303)."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return spec.render(value)


def same_instant(expected: str, actual: str) -> bool:
    try:
        return datetime.fromisoformat(expected) == datetime.fromisoformat(actual)
    except ValueError:
        return False


# --- seeding ----------------------------------------------------------------------


def model_values(table: str, row: dict, handles: Handles) -> dict[str, Any]:
    """An archive-shaped row as model attributes, through the archive's own parsers."""
    table_spec = spec.SPEC_BY_KEY[table]
    values = {}
    for name, value in row.items():
        column = table_spec.column(name)
        assert column is not None and column.name == name, f"{table}.{name} isn't a column"
        assert column.persisted, f"{table}.{name} is derived — `given` holds stored columns only"
        if isinstance(value, str) and HANDLE.match(value):
            values[name] = handles[value]
            continue
        parsed = column.parse(cell(value))
        if isinstance(parsed, datetime) and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        values[name] = parsed
    return values


async def seed(given: dict, handles: Handles) -> None:
    async with session_scope() as session:
        for table_spec in spec.TABLE_SPECS:
            for row in given.get(table_spec.key, []):
                values = model_values(table_spec.key, row, handles)
                if table_spec.singleton:
                    settings = await session.get(InstanceSettings, 1)
                    for name, value in values.items():
                        setattr(settings, name, value)
                else:
                    session.add(table_spec.model(**values))
            await session.flush()


async def state() -> dict[str, dict[str, dict[str, str]]]:
    """Every portable table, rendered as the archive renders it, keyed by id."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    async with session_scope() as session:
        for table_spec in spec.TABLE_SPECS:
            rows = (await session.scalars(select(table_spec.model))).all()
            persisted = [c for c in table_spec.columns if c.persisted]
            out[table_spec.key] = {
                str(getattr(row, "id", "singleton")): {c.name: cell(c.get(row)) for c in persisted}
                for row in rows
            }
    return out


# --- operations -------------------------------------------------------------------

CATALOG = {
    "tool": (ItemType.TOOL, catalog.create_tool, ToolCreate, ToolUpdate),
    "consumable": (
        ItemType.CONSUMABLE,
        catalog.create_consumable,
        ConsumableCreate,
        ConsumableUpdate,
    ),
    "upgrade": (ItemType.UPGRADE, catalog.create_upgrade, UpgradeCreate, UpgradeUpdate),
    "display": (
        ItemType.DISPLAY,
        catalog.create_display_item,
        DisplayItemCreate,
        DisplayItemUpdate,
    ),
}


def _split(args: dict, *keys: str) -> tuple[list[Any], dict]:
    rest = dict(args)
    return [rest.pop(key) for key in keys], rest


async def _create_catalog_item(session, args):
    [item_type], fields = _split(args, "item_type")
    _, create, payload, _ = CATALOG[item_type]
    return await create(session, payload(**fields))


async def _update_catalog_item(session, args):
    [item_type, item_id], fields = _split(args, "item_type", "item_id")
    kind, _, _, payload = CATALOG[item_type]
    return await catalog.update_catalog_item(session, kind, item_id, payload(**fields))


async def _update_retailer(session, args):
    [retailer_id], fields = _split(args, "retailer_id")
    return await orders.update_retailer(session, retailer_id, RetailerUpdate(**fields))


async def _update_order(session, args):
    [order_id], fields = _split(args, "order_id")
    return await orders.update_order(session, order_id, OrderUpdate(**fields))


async def _update_kit(session, args):
    [kit_id], fields = _split(args, "kit_id")
    return await kits.update_kit(session, kit_id, KitUpdate(**fields))


def _instant(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _archive(tables: dict[str, list[dict]]) -> bytes:
    """A hand-written sheet: CSV cells as written, headers as given."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        manifest = {"format": exporting.ARCHIVE_FORMAT, "export_version": exporting.EXPORT_VERSION}
        archive.writestr(exporting.MANIFEST_NAME, json.dumps(manifest))
        for table, rows in tables.items():
            header = list(dict.fromkeys(key for row in rows for key in row))
            out = io.StringIO(newline="")
            writer = csv.DictWriter(out, fieldnames=header, lineterminator="\r\n")
            writer.writeheader()
            writer.writerows([{key: cell(value) for key, value in row.items()} for row in rows])
            archive.writestr(f"{table}.csv", out.getvalue())
    return buffer.getvalue()


async def _import_archive(_session, args):
    """Preview, then apply exactly what the preview planned — the two-step every
    caller of the importer makes. Runs its own transactions, as the router does."""
    mode = ImportMode(args["mode"])
    source = args["archive"]
    if source == "export":
        async with session_scope() as session:
            content = await exporting.export_archive(session)
    else:
        content = _archive(source["tables"])
    async with session_scope() as session:
        plan = await importing.preview_import(session, "archive.zip", content, mode)
    async with session_scope() as session:
        return await importing.apply_import(
            session, "archive.zip", content, mode, plan.plan_hash, args.get("confirm")
        )


OPS = {
    "create_retailer": lambda s, a: orders.create_retailer(s, RetailerCreate(**a)),
    "update_retailer": _update_retailer,
    "create_catalog_item": _create_catalog_item,
    "update_catalog_item": _update_catalog_item,
    "create_order": lambda s, a: orders.create_order(s, OrderCreate(**a)),
    "update_order": _update_order,
    "mark_order_shipped": lambda s, a: orders.mark_order_shipped(
        s, a["order_id"], _instant(a.get("shipped_at"))
    ),
    "receive_order": lambda s, a: orders.receive_order(
        s, a["order_id"], _instant(a.get("received_at"))
    ),
    "delete_order": lambda s, a: orders.delete_order(s, a["order_id"]),
    "update_kit": _update_kit,
    "adjust_stock": lambda s, a: catalog.adjust_stock(
        s, a["catalog_id"], a["delta"], a.get("reason")
    ),
    "apply_upgrade": lambda s, a: upgrades.apply_upgrade(
        s, a["upgrade_id"], a["kit_id"], a["quantity"]
    ),
    "withdraw_upgrade_application": lambda s, a: upgrades.withdraw_upgrade_application(
        s, a["application_id"], restore_stock=a["restore_stock"]
    ),
    "import_archive": _import_archive,
}

#: Ops that open their own transactions rather than run in the step's.
OWN_TRANSACTIONS = {"import_archive"}


async def run_step(step: dict, handles: Handles) -> tuple[Any, DomainError | None]:
    args = handles.resolve(step["args"])
    op = OPS[step["op"]]
    try:
        if step["op"] in OWN_TRANSACTIONS:
            return await op(None, args), None
        async with session_scope() as session:
            return await op(session, args), None
    except DomainError as exc:
        return None, exc


# --- comparison -------------------------------------------------------------------


class Window:
    def __init__(self):
        self.start = datetime.now(UTC) - CLOCK_SLACK
        self.end: datetime | None = None

    def close(self) -> None:
        self.end = datetime.now(UTC) + CLOCK_SLACK

    def holds(self, actual: str) -> bool:
        """Inside the run so far: a step's `result` is read while the window is
        still open, and the run's end is then the present."""
        try:
            instant = datetime.fromisoformat(actual)
        except ValueError:
            return False
        end = self.end or datetime.now(UTC) + CLOCK_SLACK
        return self.start <= instant <= end


def matches(expected: Any, actual: str, handles: Handles, window: Window) -> bool:
    if expected == NOW:
        return window.holds(actual)
    rendered = cell(handles.resolve(expected))
    return rendered == actual or same_instant(rendered, actual)


def assert_table(table: str, expected_rows: list[dict], actual: dict, handles, window) -> None:
    remaining = dict(actual)
    assert len(expected_rows) == len(actual), (
        f"{table}: expected {len(expected_rows)} rows, found {len(actual)}: {list(actual.values())}"
    )
    for expected in expected_rows:
        if "id" in expected:
            key = str(handles[expected["id"]])
            assert key in remaining, f"{table}: no row {expected['id']}"
            candidates = [key]
        else:
            candidates = list(remaining)
        found = next(
            (
                key
                for key in candidates
                if all(
                    matches(value, remaining[key].get(name, ""), handles, window)
                    for name, value in expected.items()
                )
            ),
            None,
        )
        assert found is not None, (
            f"{table}: no row matches {expected}; left: {list(remaining.values())}"
        )
        del remaining[found]


def assert_refusal(expected: dict, exc: DomainError, handles: Handles) -> None:
    assert KIND.get(type(exc)) == expected["kind"], (type(exc).__name__, exc.code, exc.detail)
    assert exc.code == expected["code"], (exc.code, exc.detail)
    declared = REGISTRY[exc.code]["params"]
    actual = {key: cell(exc.params[key]) for key in declared}
    wanted = {key: cell(handles.resolve(value)) for key, value in expected["params"].items()}
    assert actual == wanted, (exc.code, exc.detail)


def assert_result(expected: dict, result: Any, handles: Handles, window: Window) -> None:
    for name, value in expected.items():
        actual = getattr(result, name)
        if isinstance(value, dict):
            actual = {key: cell(item) for key, item in actual.items()}
            assert actual == {k: cell(v) for k, v in value.items()}, name
        else:
            assert matches(value, cell(actual), handles, window), (name, actual)


# --- the scenarios ------------------------------------------------------------------


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
async def test_scenario(scenario):
    handles = Handles(scenario["id"])
    await seed(scenario["given"], handles)
    before = await state()

    window = Window()
    for number, step in enumerate(scenario["steps"], start=1):
        result, refusal = await run_step(step, handles)
        expect = step.get("expect", "ok")
        where = f"step {number} ({step['op']})"
        if expect == "ok":
            assert refusal is None, f"{where} refused: {refusal and (refusal.code, refusal.detail)}"
            if "as" in step:
                handles.bind(step["as"], result.id)
            if "result" in step:
                assert_result(step["result"], result, handles, window)
        else:
            assert refusal is not None, f"{where} was not refused"
            assert_refusal(expect["refused"], refusal, handles)
    window.close()

    after = await state()
    listed = {} if scenario["then"] == "unchanged" else scenario["then"]["tables"]
    for table in after:
        if table in listed:
            assert_table(table, listed[table], after[table], handles, window)
        else:
            assert after[table] == before[table], f"{table} changed, and `then` doesn't list it"


# --- the files themselves ------------------------------------------------------------


def test_there_are_scenarios():
    """An empty parametrize is a skip, not a failure."""
    assert len(SCENARIOS) >= 20, len(SCENARIOS)


@pytest.mark.parametrize("name", sorted(FILES))
def test_every_file_follows_the_schema(name):
    jsonschema.validate(FILES[name], SCHEMA)


def test_no_file_repeats_a_key():
    """JSON keeps the last of two equal keys and says nothing, so a repeated key in
    an expected row is an expectation nobody can see."""

    def refuse_repeats(pairs):
        keys = [key for key, _ in pairs]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        assert not repeated, repeated
        return dict(pairs)

    for path in sorted(FIXTURES.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=refuse_repeats)


def test_scenario_ids_are_unique():
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


def test_every_refusal_states_exactly_the_declared_params():
    """What the wire contract promises for the code — no more, which a second
    implementation would owe needlessly, and no less, which would leave a key
    unchecked."""
    for scenario in SCENARIOS:
        for step in scenario["steps"]:
            expect = step.get("expect", "ok")
            if expect == "ok":
                continue
            code = expect["refused"]["code"]
            assert code in REGISTRY, (scenario["id"], code)
            assert set(expect["refused"]["params"]) == set(REGISTRY[code]["params"]), (
                scenario["id"],
                code,
            )


def test_every_op_is_run_by_a_scenario():
    """The vocabulary is the schema's; each word has a dispatcher and a scenario."""
    vocabulary = set(SCHEMA["$defs"]["step"]["properties"]["op"]["enum"])
    assert set(OPS) == vocabulary
    used = {step["op"] for scenario in SCENARIOS for step in scenario["steps"]}
    assert used == vocabulary, vocabulary - used


def test_handles_name_a_portable_table():
    tables = {s.key for s in spec.TABLE_SPECS}
    for scenario in SCENARIOS:
        for handle in re.findall(r'"(@[a-z_]+:[a-z0-9_-]+)"', json.dumps(scenario)):
            assert handle.split(":")[0][1:] in tables, (scenario["id"], handle)


def test_dates_in_given_are_canonical():
    """`given` is the archive's vocabulary: an instant carries its offset."""
    for scenario in SCENARIOS:
        for table, rows in scenario["given"].items():
            for row in rows:
                for name, value in row.items():
                    if name.endswith("_at") and value is not None:
                        assert datetime.fromisoformat(value).tzinfo is not None, (
                            scenario["id"],
                            table,
                            name,
                        )
                    if name.endswith("_date") and value is not None:
                        date.fromisoformat(value)

"""Data-bearing migrations exercised against seeded rows, in both directions (#54).

The session conftest already runs every migration base -> head against an *empty*
schema on every test run; these tests are the data half that never executed. Each
one walks the shared test database down to the revision under test's parent, seeds
the old shape by SQL, upgrades through it, asserts the transformed shape, then
downgrades again and asserts what survives. The `walk` fixture always restores
`head` on the way out — even when the test failed mid-walk — so the rest of the
suite meets the schema it expects; the ordinary between-test TRUNCATE removes the
seeded rows afterwards.

Everything is textual SQL on purpose: the ORM models describe head, and a seeded
row here is by definition not at head. Revision ids are literals, not lookups —
deriving them from the alembic graph would let a renumbering silently retarget
every test (the "never derive the test's subject from the code under test" rule).
"""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app import config
from app.db import get_sessionmaker

# The revisions under test and the parents their seeds are planted at.
INITIAL = "71ddc06de024"
RECEIVED_AT = "6cbd8315df95"
ORDER_NUMBER = "04315056a82f"
IN_HAND_MERGE = "9d78b6148c30"
CONVERTED_SNAPSHOT = "2b293c6fd496"
TOOL_COST_CURRENCY = "24ee4c9024e4"
SHIPPED_AT = "bcdb375e32d0"
DISPLAY_ITEMS = "2c97a5ced66a"
INSTANCE_SETTINGS = "f9979ec7b9cb"
AUTH_TABLES = "f1058c5de0f3"
OIDC_LOGIN = "0db6c35d0a7e"

# The current migration head, as a literal (this module keeps revision ids as
# literals on purpose — see the header). The "recovered to head" / "nothing
# moved" assertions compare against it, so a new migration bumps this one line.
HEAD = OIDC_LOGIN


def db(sql: str, **params) -> list[tuple]:
    """One statement against the test database, committed; rows for a SELECT."""

    async def go() -> list[tuple]:
        async with get_sessionmaker()() as session:
            result = await session.execute(text(sql), params)
            await session.commit()
            return [tuple(row) for row in result] if result.returns_rows else []

    return asyncio.run(go())


def column_exists(table: str, column: str) -> bool:
    return (
        db(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c",
            t=table,
            c=column,
        )[0][0]
        == 1
    )


def table_exists(table: str) -> bool:
    return (
        db(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = :t",
            t=table,
        )[0][0]
        == 1
    )


def current_revision() -> str:
    return db("SELECT version_num FROM alembic_version")[0][0]


class _Walk:
    def __init__(self, cfg: Config):
        self._cfg = cfg

    def down(self, revision: str) -> None:
        command.downgrade(self._cfg, revision)

    def up(self, revision: str) -> None:
        command.upgrade(self._cfg, revision)


def _restore_head(cfg: Config, *, body_failed: bool) -> None:
    """The way home from wherever a test stopped, without eating the evidence.

    A restore failure is recovered by rebuilding from base over the empty
    schema — but recovery and verdict are separate questions (PR #151 review,
    P2-1). When the test body already failed, the primary signal exists and
    the recovery stays silent, so a deliberate mutant kill reads as the one
    failure it is. When the body PASSED, a failure first observed here is the
    only signal — a later migration choking on rows an earlier era seeded is
    exactly what this harness exists to catch — so it is re-raised after the
    database is safe. Teardown never *downgrades* first: a downgrade can
    legitimately refuse (2c97a5ced66a), and the way home must not."""
    try:
        command.upgrade(cfg, "head")
    except Exception:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        if not body_failed:
            raise


@pytest.fixture
def walk(request):
    """Alembic movements with a guaranteed way home: teardown restores head no
    matter where the test stopped, so a failure mid-walk cannot strand the
    rest of the session on an old schema. See `_restore_head` for what happens
    when the restore itself fails. The body-failed signal is the session
    failure counter's delta across this fixture's lifetime — the call-phase
    report is processed before teardown runs, and nothing else executes in
    between."""
    cfg = Config("alembic.ini")
    failed_before = request.session.testsfailed
    try:
        yield _Walk(cfg)
    finally:
        _restore_head(cfg, body_failed=request.session.testsfailed > failed_before)


@pytest.fixture
def reference_currency_pinned_to_aud(monkeypatch):
    """24ee4c9024e4 backfills with `get_settings().reference_currency`; pin it so
    the literals in the tool-cost test hold whatever the host .env says. A real
    environment variable outranks the .env files, and clearing the lru_cache is
    what makes the migration see it. Cleared again on the way out so later
    callers re-read the true environment."""
    monkeypatch.setenv("REFERENCE_CURRENCY", "AUD")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def seed_retailer_and_order(order_date: str) -> tuple[uuid.UUID, uuid.UUID]:
    retailer_id, order_id = uuid.uuid4(), uuid.uuid4()
    db(
        "INSERT INTO retailers (id, name) VALUES (:r, :name)",
        r=retailer_id,
        name=f"Migration Test Shop {retailer_id.hex[:6]}",
    )
    db(
        "INSERT INTO orders (id, retailer_id, order_date, currency_code) "
        "VALUES (:o, :r, :d, 'AUD')",
        o=order_id,
        r=retailer_id,
        d=date.fromisoformat(order_date),  # asyncpg types the parameter as DATE
    )
    return retailer_id, order_id


# --- 6cbd8315df95: orders received_at ------------------------------------------


def test_received_at_backfills_every_order_and_advances_no_kit(walk):
    """Pre-model orders had stock applied at entry, so the migration marks them
    received as of their order_date — every row, not just the first. It does
    NOT advance the kits those orders spawned: a database crossing this revision
    can hold a received order with an `ordered` kit, which is the documented
    legacy state (docs/operations.md), left alone by design."""
    walk.down(INITIAL)
    _, order_id = seed_retailer_and_order("2026-08-01")
    _, second_order = seed_retailer_and_order("2026-08-05")
    item_id, kit_id = uuid.uuid4(), uuid.uuid4()
    db(
        "INSERT INTO order_items (id, order_id, item_type, quantity, unit_price_minor, "
        "currency_code) VALUES (:i, :o, 'kit', 1, 2999, 'AUD')",
        i=item_id,
        o=order_id,
    )
    db(
        "INSERT INTO kits (id, name, grade, status, order_item_id) "
        "VALUES (:k, 'HG Zaku II', 'HG', 'ordered', :i)",
        k=kit_id,
        i=item_id,
    )

    walk.up(RECEIVED_AT)
    # Exact-instant equality with the same cast the migration's UPDATE used —
    # both connections read the database's default timezone, so this holds in
    # any zone. (`received_at::date = order_date` does NOT: a civil date the
    # zone skipped casts to the next existing instant and reads back as the
    # next day. That case has its own test below; PR #151 review, P3-2.)
    assert db(
        "SELECT count(*) FROM orders "
        "WHERE received_at IS NULL OR received_at != order_date::timestamptz"
    ) == [(0,)]
    assert db("SELECT count(*) FROM orders") == [(2,)]
    assert db("SELECT status FROM kits WHERE id = :k", k=kit_id) == [("ordered",)]

    walk.down(INITIAL)
    assert not column_exists("orders", "received_at")
    assert db("SELECT count(*) FROM orders") == [(2,)]  # only the column went


@pytest.fixture
def database_timezone_pacific_apia():
    """ALTER DATABASE, so every NEW connection — the walk's alembic runs and
    the assertions alike, all NullPool — reads Pacific/Apia as its default
    timezone; reset on the way out. Apia crossed the date line westward at the
    end of 2011-12-29 and never had a 2011-12-30, which is the standing
    counter-example to any date -> timestamptz -> date identity claim."""
    dbname = db("SELECT current_database()")[0][0]
    db(f"ALTER DATABASE \"{dbname}\" SET timezone = 'Pacific/Apia'")
    yield
    db(f'ALTER DATABASE "{dbname}" RESET timezone')


def test_received_at_on_a_skipped_civil_date_stamps_the_next_existing_instant(
    database_timezone_pacific_apia, walk
):
    """The policy the backfill implies, stated rather than assumed (PR #151
    review, P3-2): `SET received_at = order_date` casts through the session
    timezone, and a civil date the zone skipped has no midnight to stamp —
    Postgres lands on the earliest instant that exists, which reads back as
    the NEXT day. Pinned as-is, not "fixed": the migration ran on real
    instances in 2026, and what this test records is what it does — and that
    the exact-instant assertion above is the only identity this file may
    claim."""
    walk.down(INITIAL)
    _, skipped = seed_retailer_and_order("2011-12-30")  # Apia never had this day
    _, ordinary = seed_retailer_and_order("2026-08-01")

    walk.up(RECEIVED_AT)
    assert db(
        "SELECT received_at = timestamptz '2011-12-31 00:00:00+14', received_at::date "
        "FROM orders WHERE id = :o",
        o=skipped,
    ) == [(True, date(2011, 12, 31))]
    # The in-zone control: an ordinary date keeps the naive identity even here.
    assert db(
        "SELECT received_at = order_date::timestamptz, received_at::date FROM orders WHERE id = :o",
        o=ordinary,
    ) == [(True, date(2026, 8, 1))]


def test_restore_head_reraises_when_the_test_body_gave_no_signal(monkeypatch):
    """The P2-1 regression control (PR #151 review): a forward-path failure
    first observed during the restore must survive the recovery when the test
    body passed — the reviewed head recovered silently, so a later migration
    choking on seeded rows read green. The first upgrade call is faked to fail
    (the review's data-conditional probe means editing a shipped migration
    file, which a committed test cannot do); the rebuild underneath is real
    both times, asserted by the database finishing at head."""
    calls = {"n": 0}
    real_upgrade = command.upgrade

    def failing_once(cfg, revision):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("data-conditional failure in a later migration")
        real_upgrade(cfg, revision)

    cfg = Config("alembic.ini")
    monkeypatch.setattr(command, "upgrade", failing_once)

    with pytest.raises(RuntimeError, match="data-conditional failure"):
        _restore_head(cfg, body_failed=False)
    assert current_revision() == HEAD  # recovered to head before re-raising
    assert calls["n"] == 2  # the rebuild really ran

    calls["n"] = 0
    _restore_head(cfg, body_failed=True)  # primary signal exists: swallow
    assert current_revision() == HEAD
    assert calls["n"] == 2


# --- 9d78b6148c30: merge in_hand into backlog -----------------------------------


def test_in_hand_merges_into_backlog_and_stays_merged_on_downgrade(walk):
    walk.down(ORDER_NUMBER)
    for status in ("in_hand", "backlog", "building"):
        db(
            "INSERT INTO kits (id, name, grade, status) VALUES (:k, :name, 'HG', :status)",
            k=uuid.uuid4(),
            name=f"Kit {status}",
            status=status,
        )

    walk.up(IN_HAND_MERGE)
    assert db("SELECT status, count(*) FROM kits GROUP BY status ORDER BY status") == [
        ("backlog", 2),
        ("building", 1),
    ]
    # The rewritten CHECK is load-bearing, not decorative: in_hand is refused.
    with pytest.raises(IntegrityError, match="ck_kits_kit_status"):
        db(
            "INSERT INTO kits (id, name, grade, status) VALUES (:k, 'Ghost', 'HG', 'in_hand')",
            k=uuid.uuid4(),
        )

    walk.down(ORDER_NUMBER)
    # Which backlog kits were formerly in_hand is unknowable — the data stays
    # merged; only the constraint reverts to accepting the old vocabulary.
    assert db("SELECT status, count(*) FROM kits GROUP BY status ORDER BY status") == [
        ("backlog", 2),
        ("building", 1),
    ]
    db(
        "INSERT INTO kits (id, name, grade, status) VALUES (:k, 'Old Rows', 'HG', 'in_hand')",
        k=uuid.uuid4(),
    )
    assert db("SELECT count(*) FROM kits WHERE status = 'in_hand'") == [(1,)]


# --- 2b293c6fd496: neutral reference currency on order items ---------------------


def test_converted_snapshot_renames_backfills_aud_and_drops_foreign_on_downgrade(walk):
    walk.down(IN_HAND_MERGE)
    _, order_id = seed_retailer_and_order("2026-08-01")
    with_snapshot, without_snapshot = uuid.uuid4(), uuid.uuid4()
    db(
        "INSERT INTO order_items (id, order_id, item_type, quantity, unit_price_minor, "
        "currency_code, converted_price_aud_minor) VALUES "
        "(:a, :o, 'kit', 1, 5800, 'JPY', 11200), (:b, :o, 'kit', 1, 4999, 'AUD', NULL)",
        a=with_snapshot,
        b=without_snapshot,
        o=order_id,
    )

    walk.up(CONVERTED_SNAPSHOT)
    # Renamed, not replaced: the amount survives; the code every pre-existing
    # snapshot was captured under becomes explicit. A null snapshot stays a
    # null *pair* — the backfill must not invent a code for it.
    assert not column_exists("order_items", "converted_price_aud_minor")
    assert db(
        "SELECT converted_price_minor, converted_currency_code FROM order_items WHERE id = :i",
        i=with_snapshot,
    ) == [(11200, "AUD")]
    assert db(
        "SELECT converted_price_minor, converted_currency_code FROM order_items WHERE id = :i",
        i=without_snapshot,
    ) == [(None, None)]

    # A snapshot the post-upgrade app could take in a non-AUD reference currency.
    db(
        "UPDATE order_items SET converted_price_minor = 1200, "
        "converted_currency_code = 'JPY' WHERE id = :i",
        i=without_snapshot,
    )

    walk.down(IN_HAND_MERGE)
    # Lossy on purpose, and in one direction only: the restored column name
    # asserts AUD, so the AUD amount moves back and the JPY one is cleared
    # rather than silently relabelled as AUD.
    assert not column_exists("order_items", "converted_currency_code")
    assert db(
        "SELECT converted_price_aud_minor FROM order_items WHERE id = :i", i=with_snapshot
    ) == [(11200,)]
    assert db(
        "SELECT converted_price_aud_minor FROM order_items WHERE id = :i",
        i=without_snapshot,
    ) == [(None,)]


# --- 24ee4c9024e4: tool reference cost carries its currency ----------------------


def test_tool_cost_scales_by_the_reference_currency_and_downgrade_drops_foreign(
    reference_currency_pinned_to_aud, walk
):
    walk.down(CONVERTED_SNAPSHOT)
    priced, unpriced = uuid.uuid4(), uuid.uuid4()
    db(
        "INSERT INTO tools (id, name, category, quantity_on_hand, unit_cost_reference) "
        "VALUES (:a, 'Godhand SPN-120', 'cutting', 1, 45.00), "
        "(:b, 'Freebie Nipper', 'cutting', 1, NULL)",
        a=priced,
        b=unpriced,
    )

    walk.up(TOOL_COST_CURRENCY)
    # 45.00 under a 2-decimal reference currency is 4500 minor units stamped with
    # the instance's code; a null cost stays a null pair, never 0 or a bare code.
    assert not column_exists("tools", "unit_cost_reference")
    assert db(
        "SELECT unit_cost_reference_minor, unit_cost_reference_currency FROM tools WHERE id = :i",
        i=priced,
    ) == [(4500, "AUD")]
    assert db(
        "SELECT unit_cost_reference_minor, unit_cost_reference_currency FROM tools WHERE id = :i",
        i=unpriced,
    ) == [(None, None)]

    # Rows the post-upgrade app could hold: a foreign-currency cost, and a second
    # AUD one that must round-trip exactly.
    jpy_tool = uuid.uuid4()
    db(
        "INSERT INTO tools (id, name, category, quantity_on_hand, "
        "unit_cost_reference_minor, unit_cost_reference_currency) "
        "VALUES (:j, 'Airbrush (Yodobashi)', 'painting', 1, 1200, 'JPY')",
        j=jpy_tool,
    )

    walk.down(CONVERTED_SNAPSHOT)
    # AUD round-trips exactly; JPY is dropped rather than relabelled — the
    # restored column cannot state a currency, so a foreign amount moved into it
    # would become a number that means something else.
    rows = dict(
        (row[0], row[1]) for row in db("SELECT id, unit_cost_reference FROM tools ORDER BY name")
    )
    assert rows[priced] == Decimal("45.00")
    assert rows[unpriced] is None
    assert rows[jpy_tool] is None
    assert not column_exists("tools", "unit_cost_reference_minor")
    assert not column_exists("tools", "unit_cost_reference_currency")


# --- 2c97a5ced66a: display_items downgrade refuses while data exists -------------


def test_display_downgrade_refuses_until_no_display_data_in_any_form(walk):
    """The #126 downgrade guard, deferred to this harness by design: one
    invariant (no display data in any form), four states. A stored row, an
    orphan display order line, and both together each refuse with the counts
    and — when both — the order the operator must act in; empty proceeds, and
    what comes back is the old vocabulary."""
    item_id = uuid.uuid4()
    db(
        "INSERT INTO display_items (id, name, category, quantity_on_hand) "
        "VALUES (:i, 'Action Base 1', 'stand', 2)",
        i=item_id,
    )
    with pytest.raises(RuntimeError, match=r"1 display item\(s\)"):
        walk.down(SHIPPED_AT)
    # Transactional: nothing moved — including the auth-tables and
    # instance_settings drops that sit between head and the refusing revision,
    # rolled back with the rest.
    assert current_revision() == HEAD
    assert db("SELECT count(*) FROM display_items") == [(1,)]

    # An order line, with the row also present: the message must put the line
    # first — the app 409s a delete of an item a line still points at.
    _, order_id = seed_retailer_and_order("2026-08-01")
    line_id = uuid.uuid4()
    db(
        "INSERT INTO order_items (id, order_id, item_type, catalog_ref_id, quantity, "
        "unit_price_minor, currency_code) VALUES (:l, :o, 'display', :c, 1, 900, 'AUD')",
        l=line_id,
        o=order_id,
        c=item_id,
    )
    both_counts_then_ordered_steps = (
        r"1 display item\(s\) and 1 display order line\(s\)"
        r"[\s\S]*1\. remove[\s\S]*2\. then delete"
    )
    with pytest.raises(RuntimeError, match=both_counts_then_ordered_steps):
        walk.down(SHIPPED_AT)

    # The line alone — catalog_ref_id is polymorphic with no FK, so a display
    # line can outlive its row, and that state must still refuse.
    db("DELETE FROM display_items WHERE id = :i", i=item_id)
    with pytest.raises(RuntimeError, match=r"1 display order line\(s\)"):
        walk.down(SHIPPED_AT)

    db("DELETE FROM order_items WHERE id = :l", l=line_id)
    walk.down(SHIPPED_AT)
    assert current_revision() == SHIPPED_AT
    assert not table_exists("display_items")
    with pytest.raises(IntegrityError, match="ck_order_items_item_type"):
        db(
            "INSERT INTO order_items (id, order_id, item_type, quantity, unit_price_minor, "
            "currency_code) VALUES (:l, :o, 'display', 1, 900, 'AUD')",
            l=uuid.uuid4(),
            o=order_id,
        )


# --- f9979ec7b9cb: instance settings singleton (#23) -----------------------------


@pytest.fixture
def bootstrap_currency_jpy(monkeypatch):
    """The seed's one environment input, pinned to something the host .env is
    not — the point under test is that an installation's configured currency
    survives the upgrade, so the pin has to differ from the AUD default."""
    monkeypatch.setenv("REFERENCE_CURRENCY", "JPY")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_instance_settings_seeds_one_env_configured_row(bootstrap_currency_jpy, walk):
    """Upgrade creates the table with exactly one row: documented defaults plus
    the env-configured reference currency (the compatibility promise — an
    installation that set REFERENCE_CURRENCY keeps its default). Downgrade drops
    the table whole; the env var resumes its pre-#23 role on the old code."""
    walk.down(DISPLAY_ITEMS)
    assert not table_exists("instance_settings")

    walk.up(INSTANCE_SETTINGS)
    assert db(
        "SELECT id, interface_language, formatting_locale, time_zone, date_style, "
        "hour_cycle, reference_currency FROM instance_settings"
    ) == [(1, "en-AU", "en-AU", "UTC", "locale", "locale", "JPY")]
    # The CHECK holds the table to its one row — a second is a constraint
    # violation, not a divergent set of preferences.
    with pytest.raises(IntegrityError, match="ck_instance_settings_singleton"):
        db(
            "INSERT INTO instance_settings (id, interface_language, formatting_locale, "
            "time_zone, date_style, hour_cycle, reference_currency) "
            "VALUES (2, 'en-AU', 'en-AU', 'UTC', 'locale', 'locale', 'AUD')"
        )

    # Settings the post-upgrade app could hold; the downgrade loses them, which
    # the migration docstring discloses rather than guesses around.
    db("UPDATE instance_settings SET time_zone = 'Australia/Sydney'")

    walk.down(DISPLAY_ITEMS)
    assert not table_exists("instance_settings")

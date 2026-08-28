"""The instance reference currency and the entry-time conversion snapshot (§6).

The invariant under test throughout: a snapshot records the currency it was taken
in, so moving the instance default never restates what past purchases cost.
"""

import csv
import io

import pytest

from app.config import get_settings
from app.db import session_scope
from app.schemas.settings import InstanceSettingsUpdate
from app.services import instance_settings
from tests.diag import details, row_error, row_messages


@pytest.fixture
def bootstrap_currency(monkeypatch):
    """Set the REFERENCE_CURRENCY *bootstrap* input for one test. Since #23 it
    only seeds the settings row when the migration runs — runtime reads the row —
    so only the two config tests below still want this. get_settings is
    lru_cached, so the cache has to be cleared on the way in *and* out or the
    override leaks."""

    def _set(code: str) -> None:
        monkeypatch.setenv("REFERENCE_CURRENCY", code)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


@pytest.fixture
def reference_currency():
    """Set the instance's reference currency for one test — the settings row
    (#23), which is what every runtime read consults. conftest's clean_tables
    resets it between tests."""

    async def _set(code: str) -> None:
        async with session_scope() as session:
            await instance_settings.update_instance_settings(
                session, InstanceSettingsUpdate(reference_currency=code)
            )

    return _set


async def _preview_then_apply(client, filename: str, content: bytes):
    """Import the way a client has to since #41: preview, then apply that plan.

    The hash is mandatory, so these tests can no longer post straight to apply.
    Faults are deliberately left to the caller's own assertion — a preview that
    fails yields no hash, and the apply then reports why in its own status.
    """
    seen = await client.post(
        "/import/preview",
        files={"file": (filename, content, "text/csv")},
        data={"mode": "merge"},
    )
    return await client.post(
        "/import/apply",
        files={"file": (filename, content, "text/csv")},
        data={
            "mode": "merge",
            "plan_hash": seen.json().get("plan_hash", "") if seen.status_code == 200 else "",
        },
    )


def kit_line(**overrides) -> dict:
    return {
        "item_type": "kit",
        "quantity": 1,
        "unit_price_minor": 4999,
        "currency_code": "JPY",
        "kit": {"name": "RX-78-2 Gundam", "grade": "MG"},
        **overrides,
    }


async def make_order(client, retailer, items: list[dict], **extra):
    return await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": items,
            **extra,
        },
    )


# --- the setting ----------------------------------------------------------------


async def test_meta_reports_the_reference_currency(client, reference_currency):
    await reference_currency("JPY")
    resp = await client.get("/meta")
    assert resp.status_code == 200
    assert resp.json()["reference_currency"] == "JPY"


async def test_bootstrap_reference_currency_is_normalised(bootstrap_currency):
    bootstrap_currency("jpy")
    assert get_settings().reference_currency == "JPY"


async def test_nonsense_bootstrap_reference_currency_is_rejected(bootstrap_currency):
    bootstrap_currency("Australian Dollars")
    # Settings are lazy, so the complaint lands on first use — which for this
    # value is the migration that seeds the settings row (#23).
    with pytest.raises(ValueError, match="ISO 4217"):
        get_settings()


# --- the snapshot ---------------------------------------------------------------


async def test_snapshot_defaults_to_the_instance_currency(client, retailer, reference_currency):
    await reference_currency("EUR")
    resp = await make_order(client, retailer, [kit_line(converted_price_minor=3200)])
    assert resp.status_code == 201, resp.text
    line = resp.json()["items"][0]
    assert line["converted_price_minor"] == 3200
    assert line["converted_currency_code"] == "EUR"


async def test_an_explicit_snapshot_currency_wins(client, retailer, reference_currency):
    await reference_currency("EUR")
    resp = await make_order(
        client,
        retailer,
        [kit_line(converted_price_minor=3200, converted_currency_code="GBP")],
    )
    assert resp.json()["items"][0]["converted_currency_code"] == "GBP"


async def test_no_amount_means_no_snapshot(client, retailer):
    """The pair is all-or-nothing — a currency alone records nothing, and the
    paired CHECK constraint would reject it anyway."""
    resp = await make_order(client, retailer, [kit_line()])
    line = resp.json()["items"][0]
    assert line["converted_price_minor"] is None
    assert line["converted_currency_code"] is None


async def test_currency_without_an_amount_is_refused(client, retailer):
    resp = await make_order(client, retailer, [kit_line(converted_currency_code="GBP")])
    assert resp.status_code == 422
    assert "converted_price_minor" in resp.text


async def test_moving_the_instance_currency_does_not_restate_history(
    client, retailer, reference_currency
):
    """The whole point of storing the code per row (§6)."""
    await reference_currency("AUD")
    created = await make_order(client, retailer, [kit_line(converted_price_minor=4999)])
    order_id = created.json()["id"]

    await reference_currency("JPY")
    reread = (await client.get(f"/orders/{order_id}")).json()["items"][0]
    assert reread["converted_price_minor"] == 4999
    assert reread["converted_currency_code"] == "AUD"  # not reinterpreted as yen


async def test_editing_a_line_restamps_the_snapshot(client, retailer, reference_currency):
    await reference_currency("AUD")
    created = await make_order(client, retailer, [kit_line(converted_price_minor=4999)])
    order = created.json()
    line_id = order["items"][0]["id"]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [kit_line(id=line_id, converted_price_minor=5200)]},
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()["items"][0]
    assert line["converted_price_minor"] == 5200
    assert line["converted_currency_code"] == "AUD"


async def test_editing_a_line_preserves_an_omitted_snapshot(client, retailer, reference_currency):
    """Issue #3: an edit about the quantity is not permission to erase the snapshot.

    No client can restate a foreign-currency conversion — it has no entry-time
    rate — so an absent field has to mean "leave it", not "clear it"."""
    await reference_currency("AUD")
    created = await make_order(
        client, retailer, [kit_line(unit_price_minor=3800, converted_price_minor=7350)]
    )
    order = created.json()
    line_id = order["items"][0]["id"]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [kit_line(id=line_id, quantity=2, unit_price_minor=3800)]},
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()["items"][0]
    assert line["quantity"] == 2
    assert line["converted_price_minor"] == 7350
    assert line["converted_currency_code"] == "AUD"


async def test_correcting_only_the_amount_keeps_the_recorded_currency(
    client, retailer, reference_currency
):
    """A typo fix on the amount is not permission to relabel the currency.

    The stored code outranks the instance default here: stamping AUD onto a GBP
    snapshot because the payload didn't restate the code would turn £42.00 into
    A$43.00 — the same config-overwrites-a-record failure as the omitted case."""
    await reference_currency("AUD")
    created = await make_order(
        client,
        retailer,
        [kit_line(converted_price_minor=4200, converted_currency_code="GBP")],
    )
    order = created.json()
    line_id = order["items"][0]["id"]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [kit_line(id=line_id, converted_price_minor=4300)]},
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()["items"][0]
    assert line["converted_price_minor"] == 4300
    assert line["converted_currency_code"] == "GBP"  # not restamped to the instance default


async def test_an_explicit_null_clears_the_snapshot(client, retailer, reference_currency):
    """The other half of the rule: clearing is possible, it just has to be meant."""
    await reference_currency("AUD")
    created = await make_order(client, retailer, [kit_line(converted_price_minor=7350)])
    order = created.json()
    line_id = order["items"][0]["id"]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [kit_line(id=line_id, converted_price_minor=None)]},
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()["items"][0]
    assert line["converted_price_minor"] is None
    assert line["converted_currency_code"] is None


async def test_a_new_line_in_an_edit_invents_no_snapshot(client, retailer, reference_currency):
    """Preserving what exists must not turn into inventing what doesn't."""
    await reference_currency("AUD")
    created = await make_order(client, retailer, [kit_line(converted_price_minor=7350)])
    order = created.json()
    line_id = order["items"][0]["id"]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                kit_line(id=line_id, converted_price_minor=7350, converted_currency_code="AUD"),
                kit_line(kit={"name": "Zaku II", "grade": "HG"}),
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    added = next(item for item in resp.json()["items"] if item["id"] != line_id)
    assert added["converted_price_minor"] is None
    assert added["converted_currency_code"] is None


async def test_changing_only_the_snapshot_currency_is_refused(client, retailer):
    """Restating the amount is how an edit changes the code — a lone code still 422s,
    and must not read as "keep the amount, relabel it"."""
    created = await make_order(client, retailer, [kit_line(converted_price_minor=7350)])
    order = created.json()
    line_id = order["items"][0]["id"]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [kit_line(id=line_id, converted_currency_code="GBP")]},
    )
    assert resp.status_code == 422
    assert "converted_price_minor" in resp.text


# --- the retired CSV column -----------------------------------------------------


def order_items_csv(header: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


async def seeded_order(client, retailer) -> dict:
    resp = await make_order(client, retailer, [kit_line()])
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_legacy_converted_price_column_is_read_as_aud(client, retailer, reference_currency):
    """A pre-0.2 archive names the column converted_price_aud_minor and has no
    currency column. That name asserted AUD, so the rows are AUD even on an
    instance whose own reference currency is something else entirely."""
    await reference_currency("JPY")
    order = await seeded_order(client, retailer)
    line = order["items"][0]

    content = order_items_csv(
        [
            "id",
            "order_id",
            "item_type",
            "quantity",
            "unit_price_minor",
            "currency_code",
            "converted_price_aud_minor",
        ],
        [
            {
                "id": line["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "4999",
                "currency_code": "JPY",
                "converted_price_aud_minor": "7350",
            }
        ],
    )
    resp = await _preview_then_apply(client, "order_items.csv", content)
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 7350
    assert updated["converted_currency_code"] == "AUD"


async def test_legacy_column_does_not_warn_as_unknown(client, retailer):
    """It's a retired name, not a typo — warning about it would train people to
    ignore the warnings that matter."""
    order = await seeded_order(client, retailer)
    content = order_items_csv(
        ["id", "order_id", "item_type", "quantity", "currency_code", "converted_price_aud_minor"],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_price_aud_minor": "7350",
            }
        ],
    )
    resp = await client.post(
        "/import/preview",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    assert not [w for w in details(resp.json()["warnings"]) if "converted_price_aud_minor" in w]


async def test_current_column_wins_when_both_are_present(client, retailer):
    order = await seeded_order(client, retailer)
    content = order_items_csv(
        [
            "id",
            "order_id",
            "item_type",
            "quantity",
            "currency_code",
            "converted_price_minor",
            "converted_currency_code",
            "converted_price_aud_minor",
        ],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_price_minor": "1200",
                "converted_currency_code": "GBP",
                "converted_price_aud_minor": "7350",
            }
        ],
    )
    resp = await _preview_then_apply(client, "order_items.csv", content)
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 1200
    assert updated["converted_currency_code"] == "GBP"


async def test_import_stamps_the_instance_currency_on_a_blank_code(
    client, retailer, reference_currency
):
    """A hand-written sheet fills in an amount and leaves the code blank — which the
    column help says means the instance default. Reaching Postgres as NULL would trip
    the paired CHECK constraint as an unhandled 500."""
    await reference_currency("EUR")
    order = await seeded_order(client, retailer)
    content = order_items_csv(
        [
            "id",
            "order_id",
            "item_type",
            "quantity",
            "currency_code",
            "converted_price_minor",
            "converted_currency_code",
        ],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_price_minor": "3200",
                "converted_currency_code": "",
            }
        ],
    )
    resp = await _preview_then_apply(client, "order_items.csv", content)
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 3200
    assert updated["converted_currency_code"] == "EUR"


async def seeded_order_with_snapshot(client, retailer, minor: int, code: str) -> dict:
    """A line whose §6 snapshot is already recorded — an import, an agent, or an
    instance whose reference currency has since moved."""
    resp = await make_order(
        client,
        retailer,
        [kit_line(converted_price_minor=minor, converted_currency_code=code)],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def amount_only_csv(order: dict, minor: str) -> bytes:
    """A trimmed sheet: the amount column, and no currency column at all."""
    return order_items_csv(
        ["id", "order_id", "item_type", "quantity", "currency_code", "converted_price_minor"],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_price_minor": minor,
            }
        ],
    )


async def test_import_without_a_currency_column_keeps_the_recorded_code(
    client, retailer, reference_currency
):
    """Issue #12: a sheet that never mentions currency hasn't asked to change it.

    The import path of the same rule the API follows since #3 — otherwise correcting
    an amount reissues a GBP snapshot as this instance's currency, changing what the
    number means by a rate nobody supplied."""
    await reference_currency("AUD")
    order = await seeded_order_with_snapshot(client, retailer, 4200, "GBP")

    resp = await _preview_then_apply(client, "order_items.csv", amount_only_csv(order, "4400"))
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 4400
    assert updated["converted_currency_code"] == "GBP"  # not restamped to AUD


async def test_import_preview_does_not_claim_a_currency_change(
    client, retailer, reference_currency
):
    """The preview has to show what apply will really write, or it isn't a preview."""
    await reference_currency("AUD")
    order = await seeded_order_with_snapshot(client, retailer, 4200, "GBP")

    resp = await client.post(
        "/import/preview",
        files={"file": ("order_items.csv", amount_only_csv(order, "4400"), "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    table = next(t for t in resp.json()["tables"] if t["table"] == "order_items")
    fields = {change["field"] for row in table["rows"] for change in row["changes"]}
    assert "converted_price_minor" in fields
    assert "converted_currency_code" not in fields


async def test_import_without_a_currency_column_still_fills_a_missing_code(
    client, retailer, reference_currency
):
    """Deferring to what's recorded must not stop the fill where nothing is recorded —
    the paired CHECK constraint still needs both halves for a brand-new snapshot."""
    await reference_currency("EUR")
    order = await seeded_order(client, retailer)  # no snapshot on the line

    resp = await _preview_then_apply(client, "order_items.csv", amount_only_csv(order, "3200"))
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 3200
    assert updated["converted_currency_code"] == "EUR"


async def test_a_blank_cell_still_means_the_instance_default(client, retailer, reference_currency):
    """The deliberate line between silence and an instruction: a sheet that carries the
    column and leaves it blank *has* said something, and the column help promises blank
    means the instance default. Only a missing column defers to what's recorded."""
    await reference_currency("EUR")
    order = await seeded_order_with_snapshot(client, retailer, 4200, "GBP")
    content = order_items_csv(
        [
            "id",
            "order_id",
            "item_type",
            "quantity",
            "currency_code",
            "converted_price_minor",
            "converted_currency_code",
        ],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_price_minor": "4400",
                "converted_currency_code": "",
            }
        ],
    )
    resp = await _preview_then_apply(client, "order_items.csv", content)
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_currency_code"] == "EUR"


async def test_import_drops_a_currency_that_has_no_amount(client, retailer):
    """The mirror case: a code with no amount records nothing, so it isn't kept.
    Same rule the service layer applies to REST and MCP writes."""
    order = await seeded_order(client, retailer)
    content = order_items_csv(
        [
            "id",
            "order_id",
            "item_type",
            "quantity",
            "currency_code",
            "converted_price_minor",
            "converted_currency_code",
        ],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_price_minor": "",
                "converted_currency_code": "GBP",
            }
        ],
    )
    resp = await _preview_then_apply(client, "order_items.csv", content)
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] is None
    assert updated["converted_currency_code"] is None


async def test_exports_only_ever_name_the_current_column(client, retailer):
    await seeded_order(client, retailer)
    resp = await client.get("/export/order_items.csv")
    assert resp.status_code == 200
    header = resp.text.splitlines()[0]
    assert "converted_price_minor" in header
    assert "converted_price_aud_minor" not in header


# --- a tool's reference cost (#19) ----------------------------------------------
#
# The same invariant one table over: an amount records the code it was entered
# under, so nothing later reinterprets it. `tools.unit_cost_reference` was the last
# amount in the schema outside §6 — a scaled decimal with no currency anywhere on
# the table, so a recorded 45.00 could not be compared, converted, or explained.


def tools_csv(header: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


async def import_tools(client, content: bytes):
    return await _preview_then_apply(client, "tools.csv", content)


async def make_tool(client, **overrides) -> dict:
    resp = await client.post(
        "/tools", json={"name": "Godhand SPN-120", "category": "cutting", **overrides}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def tool_line(**overrides) -> dict:
    return {
        "item_type": "tool",
        "quantity": 1,
        "unit_price_minor": 3980,
        "currency_code": "JPY",
        "new_item": {"name": "Tamiya cement", "category": "gluing"},
        **overrides,
    }


async def test_a_tool_cost_records_its_currency(client):
    tool = await make_tool(
        client, unit_cost_reference_minor=4500, unit_cost_reference_currency="AUD"
    )
    assert tool["unit_cost_reference_minor"] == 4500
    assert tool["unit_cost_reference_currency"] == "AUD"


async def test_a_tool_cost_without_a_currency_is_refused(client):
    resp = await client.post(
        "/tools",
        json={"name": "Godhand", "category": "cutting", "unit_cost_reference_minor": 4500},
    )
    assert resp.status_code == 422


async def test_a_tool_currency_without_a_cost_is_refused(client):
    resp = await client.post(
        "/tools",
        json={"name": "Godhand", "category": "cutting", "unit_cost_reference_currency": "AUD"},
    )
    assert resp.status_code == 422


async def test_correcting_only_a_tool_cost_keeps_its_currency(client, reference_currency):
    """The rule #3 established, on the other table: a PATCH that carries the amount
    and not the code is a correction, not a redenomination."""
    await reference_currency("AUD")
    tool = await make_tool(
        client, unit_cost_reference_minor=1200, unit_cost_reference_currency="JPY"
    )

    resp = await client.patch(f"/tools/{tool['id']}", json={"unit_cost_reference_minor": 1400})
    assert resp.status_code == 200, resp.text
    assert resp.json()["unit_cost_reference_minor"] == 1400
    assert resp.json()["unit_cost_reference_currency"] == "JPY"


async def test_clearing_only_a_tool_currency_is_refused(client):
    """Breaking the pair across a PATCH boundary is a domain error naming the field,
    not an integrity error naming a constraint."""
    tool = await make_tool(
        client, unit_cost_reference_minor=4500, unit_cost_reference_currency="AUD"
    )
    resp = await client.patch(f"/tools/{tool['id']}", json={"unit_cost_reference_currency": None})
    assert resp.status_code == 422
    assert "together" in resp.json()["detail"]


async def test_clearing_both_halves_of_a_tool_cost_is_allowed(client):
    tool = await make_tool(
        client, unit_cost_reference_minor=4500, unit_cost_reference_currency="AUD"
    )
    resp = await client.patch(
        f"/tools/{tool['id']}",
        json={"unit_cost_reference_minor": None, "unit_cost_reference_currency": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["unit_cost_reference_minor"] is None
    assert resp.json()["unit_cost_reference_currency"] is None


async def test_an_order_line_stamps_its_own_currency_on_a_new_tool(
    client, retailer, reference_currency
):
    """The select-or-create path (§3.9) is the one place a tool's cost arrives with
    its currency already known — the line states it. Falling back to the instance
    default here would invent an exchange rate nobody supplied."""
    await reference_currency("AUD")
    resp = await make_order(
        client,
        retailer,
        [
            tool_line(
                new_item={
                    "name": "Tamiya cement",
                    "category": "gluing",
                    "unit_cost_reference_minor": 385,
                }
            )
        ],
    )
    assert resp.status_code == 201, resp.text

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Tamiya cement")
    assert tool["unit_cost_reference_minor"] == 385
    assert tool["unit_cost_reference_currency"] == "JPY"  # the line's, not AUD


async def test_an_order_line_without_a_cost_invents_no_currency(client, retailer):
    resp = await make_order(client, retailer, [tool_line()])
    assert resp.status_code == 201, resp.text

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Tamiya cement")
    assert tool["unit_cost_reference_minor"] is None
    assert tool["unit_cost_reference_currency"] is None


async def test_import_scales_a_tool_cost_by_its_own_currency(client, reference_currency):
    """The major-unit column is scaled by the row's *own* currency column, not by a
    column named `currency_code` — tools have no such column, and the two-decimal
    default would have read ¥1200 as ¥120000."""
    await reference_currency("AUD")
    content = tools_csv(
        [
            "name",
            "category",
            "quantity_on_hand",
            "unit_cost_reference",
            "unit_cost_reference_currency",
        ],
        [
            {
                "name": "Mr Cement S",
                "category": "gluing",
                "quantity_on_hand": "1",
                "unit_cost_reference": "1200",
                "unit_cost_reference_currency": "JPY",
            }
        ],
    )
    assert (await import_tools(client, content)).status_code == 200

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Mr Cement S")
    assert tool["unit_cost_reference_minor"] == 1200
    assert tool["unit_cost_reference_currency"] == "JPY"


async def test_import_stamps_the_instance_currency_on_a_blank_tool_code(client, reference_currency):
    await reference_currency("EUR")
    content = tools_csv(
        [
            "name",
            "category",
            "quantity_on_hand",
            "unit_cost_reference_minor",
            "unit_cost_reference_currency",
        ],
        [
            {
                "name": "Tamiya nippers",
                "category": "cutting",
                "quantity_on_hand": "1",
                "unit_cost_reference_minor": "2500",
                "unit_cost_reference_currency": "",
            }
        ],
    )
    assert (await import_tools(client, content)).status_code == 200

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Tamiya nippers")
    assert tool["unit_cost_reference_minor"] == 2500
    assert tool["unit_cost_reference_currency"] == "EUR"


async def test_import_without_a_tool_currency_column_keeps_the_recorded_code(
    client, reference_currency
):
    """#12's rule, generalised: a sheet with no currency column at all hasn't asked
    to relabel anything, so an existing row keeps the code it recorded."""
    await reference_currency("AUD")
    tool = await make_tool(
        client,
        name="Mr Cement S",
        unit_cost_reference_minor=1200,
        unit_cost_reference_currency="JPY",
    )
    content = tools_csv(
        ["id", "name", "category", "quantity_on_hand", "unit_cost_reference_minor"],
        [
            {
                "id": tool["id"],
                "name": "Mr Cement S",
                "category": "cutting",
                "quantity_on_hand": "1",
                "unit_cost_reference_minor": "1400",
            }
        ],
    )
    assert (await import_tools(client, content)).status_code == 200

    updated = next(t for t in (await client.get("/tools")).json() if t["id"] == tool["id"])
    assert updated["unit_cost_reference_minor"] == 1400
    assert updated["unit_cost_reference_currency"] == "JPY"  # not restamped AUD


async def test_import_drops_a_tool_currency_that_has_no_amount(client):
    content = tools_csv(
        [
            "name",
            "category",
            "quantity_on_hand",
            "unit_cost_reference_minor",
            "unit_cost_reference_currency",
        ],
        [
            {
                "name": "Plain file",
                "category": "filing",
                "quantity_on_hand": "1",
                "unit_cost_reference_minor": "",
                "unit_cost_reference_currency": "GBP",
            }
        ],
    )
    assert (await import_tools(client, content)).status_code == 200

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Plain file")
    assert tool["unit_cost_reference_minor"] is None
    assert tool["unit_cost_reference_currency"] is None


async def test_tool_exports_carry_the_currency_column(client):
    await make_tool(client, unit_cost_reference_minor=4500, unit_cost_reference_currency="AUD")
    resp = await client.get("/export/tools.csv")
    assert resp.status_code == 200
    header = resp.text.splitlines()[0]
    assert "unit_cost_reference_minor" in header
    assert "unit_cost_reference_currency" in header


@pytest.mark.parametrize(
    ("code", "minor", "major"),
    [("AUD", 4500, "45.00"), ("JPY", 1200, "1200"), ("KWD", 4500, "4.500")],
)
async def test_a_tool_cost_exports_its_major_units_in_its_own_currency(client, code, minor, major):
    """The readable twin is scaled by the code on the row, not by two decimals.

    Tools have no `currency_code` column — their money is denominated by
    `unit_cost_reference_currency`, which is what `ColumnSpec.currency_column`
    names. Reading the wrong field made every zero-decimal cost export a hundred
    times small (¥1200 as `12.00`) and every three-decimal one ten times large.

    Asserted as a value, not a header: the header-only version of the test above
    is why this shipped in the first place.
    """
    await make_tool(client, unit_cost_reference_minor=minor, unit_cost_reference_currency=code)
    rows = list(csv.DictReader(io.StringIO((await client.get("/export/tools.csv")).text)))
    row = next(r for r in rows if r["name"] == "Godhand SPN-120")
    assert row["unit_cost_reference_minor"] == str(minor)  # canonical, unchanged
    assert row["unit_cost_reference_currency"] == code
    assert row["unit_cost_reference"] == major


@pytest.mark.parametrize(
    ("code", "minor", "major"),
    [("AUD", 4999, "49.99"), ("JPY", 4999, "4999"), ("KWD", 4999, "4.999")],
)
async def test_an_order_line_exports_its_major_units_in_its_own_currency(
    client, retailer, code, minor, major
):
    """The control on the test above: order lines *do* name their currency
    `currency_code`, so they exercise the default and must not move."""
    resp = await make_order(
        client, retailer, [kit_line(unit_price_minor=minor, currency_code=code)]
    )
    assert resp.status_code == 201, resp.text
    rows = list(csv.DictReader(io.StringIO((await client.get("/export/order_items.csv")).text)))
    assert rows[0]["currency_code"] == code
    assert rows[0]["unit_price_minor"] == str(minor)
    assert rows[0]["unit_price"] == major


async def test_import_of_a_pre_0_2_3_tools_export_stamps_the_instance_currency(
    client, reference_currency
):
    """The old shape: a major-unit `unit_cost_reference` column and no currency column
    anywhere. The amount still has to land with a code beside it, or it trips the
    paired CHECK — and the code has to be settled *before* the major units are scaled,
    or ¥1200 is read with two decimal places."""
    await reference_currency("JPY")
    content = tools_csv(
        ["name", "category", "quantity_on_hand", "unit_cost_reference"],
        [
            {
                "name": "Legacy nippers",
                "category": "cutting",
                "quantity_on_hand": "1",
                "unit_cost_reference": "1200",
            }
        ],
    )
    resp = await import_tools(client, content)
    assert resp.status_code == 200, resp.text

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Legacy nippers")
    assert tool["unit_cost_reference_currency"] == "JPY"
    assert tool["unit_cost_reference_minor"] == 1200  # not 120000


async def test_import_ignores_a_tool_currency_column_with_no_amount_column(client):
    """A sheet naming only the currency isn't asking to redenominate. The REST API
    refuses a code with no amount; the importer must not quietly do it instead."""
    tool = await make_tool(
        client,
        name="Mr Cement S",
        unit_cost_reference_minor=1200,
        unit_cost_reference_currency="JPY",
    )
    content = tools_csv(
        ["id", "name", "category", "quantity_on_hand", "unit_cost_reference_currency"],
        [
            {
                "id": tool["id"],
                "name": "Mr Cement S",
                "category": "gluing",
                "quantity_on_hand": "1",
                "unit_cost_reference_currency": "GBP",
            }
        ],
    )
    resp = await import_tools(client, content)
    assert resp.status_code == 200, resp.text

    updated = next(t for t in (await client.get("/tools")).json() if t["id"] == tool["id"])
    assert updated["unit_cost_reference_minor"] == 1200
    assert updated["unit_cost_reference_currency"] == "JPY"  # not relabelled GBP


async def test_import_of_a_lone_tool_currency_on_a_new_row_is_not_a_500(client):
    content = tools_csv(
        ["name", "category", "quantity_on_hand", "unit_cost_reference_currency"],
        [
            {
                "name": "Bare currency",
                "category": "filing",
                "quantity_on_hand": "1",
                "unit_cost_reference_currency": "GBP",
            }
        ],
    )
    resp = await import_tools(client, content)
    assert resp.status_code == 200, resp.text

    tool = next(t for t in (await client.get("/tools")).json() if t["name"] == "Bare currency")
    assert tool["unit_cost_reference_minor"] is None
    assert tool["unit_cost_reference_currency"] is None


async def test_import_ignores_a_lone_snapshot_currency_column_too(client, retailer):
    """The same hole existed on order_items before `money_pairs` generalised it — a
    sheet naming converted_currency_code and no amount column relabelled the
    snapshot, which is the very thing #12 fixed on the other paths."""
    order = await seeded_order_with_snapshot(client, retailer, 3200, "JPY")
    content = order_items_csv(
        ["id", "order_id", "item_type", "quantity", "currency_code", "converted_currency_code"],
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
                "converted_currency_code": "GBP",
            }
        ],
    )
    resp = await _preview_then_apply(client, "order_items.csv", content)
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 3200
    assert updated["converted_currency_code"] == "JPY"  # not relabelled GBP


async def test_preview_says_a_lone_currency_column_is_being_ignored(client):
    """Dropping it silently would be its own bug — the sheet asked for something,
    and the person applying the import should see that it isn't happening."""
    content = tools_csv(
        ["name", "category", "quantity_on_hand", "unit_cost_reference_currency"],
        [
            {
                "name": "Bare currency",
                "category": "filing",
                "quantity_on_hand": "1",
                "unit_cost_reference_currency": "GBP",
            }
        ],
    )
    resp = await client.post("/import/preview", files={"file": ("tools.csv", content, "text/csv")})
    assert resp.status_code == 200, resp.text
    row = resp.json()["tables"][0]["rows"][0]
    assert any("unit_cost_reference_currency: ignored" in m for m in row_messages(row)), row


@pytest.mark.parametrize(
    ("filename", "column"),
    [
        # Literals, one per currency column the CSV shape declares — never
        # derived from the spec registry, which is the code under test here.
        ("orders.csv", "currency_code"),
        ("order_items.csv", "currency_code"),
        ("order_items.csv", "converted_currency_code"),
        ("tools.csv", "unit_cost_reference_currency"),
        ("instance_settings.csv", "reference_currency"),
    ],
)
async def test_a_unicode_letter_code_is_refused_on_every_currency_column(client, filename, column):
    """'ÅUD' is three letters to `str.isalpha` and no currency to ISO 4217
    (PR #159 review, P2). The importer judged the shape with `isalpha` while
    `PATCH /settings` used an ASCII regex, so the code REST refused imported
    cleanly — and, on the settings table, was then stamped into new conversion
    snapshots. The shape test is `require_currency_code` now, shared by both
    writers, and this matrix is the class sweep: every currency column answers,
    not just the one the review probed."""
    content = f"{column}\nÅUD\n".encode()
    resp = await client.post(
        "/import/preview",
        files={"file": (filename, content, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    (table,) = [t for t in resp.json()["tables"] if t["rows"]]
    (row,) = table["rows"]
    assert row["action"] == "error"
    assert "not a 3-letter ISO 4217 currency code" in row_error(row)

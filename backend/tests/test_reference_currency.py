"""The instance reference currency and the entry-time conversion snapshot (§6).

The invariant under test throughout: a snapshot records the currency it was taken
in, so moving the instance default never restates what past purchases cost.
"""

import csv
import io

import pytest

from app.config import get_settings


@pytest.fixture
def reference_currency(monkeypatch):
    """Set REFERENCE_CURRENCY for one test. get_settings is lru_cached, so the
    cache has to be cleared on the way in *and* out or the override leaks."""

    def _set(code: str) -> None:
        monkeypatch.setenv("REFERENCE_CURRENCY", code)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


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
    reference_currency("JPY")
    resp = await client.get("/meta")
    assert resp.status_code == 200
    assert resp.json()["reference_currency"] == "JPY"


async def test_reference_currency_is_normalised(reference_currency):
    reference_currency("jpy")
    assert get_settings().reference_currency == "JPY"


async def test_nonsense_reference_currency_is_rejected(reference_currency):
    reference_currency("Australian Dollars")
    # Settings are lazy, so the complaint lands on first use — which is startup.
    with pytest.raises(ValueError, match="ISO 4217"):
        get_settings()


# --- the snapshot ---------------------------------------------------------------


async def test_snapshot_defaults_to_the_instance_currency(client, retailer, reference_currency):
    reference_currency("EUR")
    resp = await make_order(client, retailer, [kit_line(converted_price_minor=3200)])
    assert resp.status_code == 201, resp.text
    line = resp.json()["items"][0]
    assert line["converted_price_minor"] == 3200
    assert line["converted_currency_code"] == "EUR"


async def test_an_explicit_snapshot_currency_wins(client, retailer, reference_currency):
    reference_currency("EUR")
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
    reference_currency("AUD")
    created = await make_order(client, retailer, [kit_line(converted_price_minor=4999)])
    order_id = created.json()["id"]

    reference_currency("JPY")
    reread = (await client.get(f"/orders/{order_id}")).json()["items"][0]
    assert reread["converted_price_minor"] == 4999
    assert reread["converted_currency_code"] == "AUD"  # not reinterpreted as yen


async def test_editing_a_line_restamps_the_snapshot(client, retailer, reference_currency):
    reference_currency("AUD")
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
    reference_currency("AUD")
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
    reference_currency("AUD")
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
    reference_currency("AUD")
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
    reference_currency("AUD")
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
    reference_currency("JPY")
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
    resp = await client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
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
    assert not [w for w in resp.json()["warnings"] if "converted_price_aud_minor" in w]


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
    resp = await client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
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
    reference_currency("EUR")
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
    resp = await client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text

    updated = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert updated["converted_price_minor"] == 3200
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
    resp = await client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
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

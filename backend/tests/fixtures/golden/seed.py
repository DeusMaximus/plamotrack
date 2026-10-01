"""The collection the golden archive is an export of (#303).

Built through the REST surface — the same service calls the browser makes — so
every state in it is one the app can actually reach: received stock applied by the
receipt, kits advanced by the order's ship and receive, an upgrade's stock spent by
applying it. Nothing here writes a table directly except to pin a clock.

Two things a live service call decides that a fixture cannot leave to chance:

* **Ids.** `deterministic_ids()` gives every row a counter per table, hashed through
  `uuid5`, while the seed runs. A row added later in a table moves only the ids
  after it in that table, so a regeneration's diff stays readable.
* **Clocks.** `created_at`, `updated_at`, `status_updated_at` and `applied_at` are
  stamped by the database or by `datetime.now()` at the moment of the call.
  `_pin_clocks` overwrites them afterwards with the instants below. The ones a
  request can state (`shipped_at`, `received_at`, the build dates) are stated in the
  request instead.

The data is invented. It exists to put every portable table, every cell shape the
format has, and the edge cases a second implementation gets wrong into one archive:
three currency exponents (JPY 0, AUD 2, KWD 3), a pre-order, a shipped order, a
received order with catalog lines, progressed kits, upgrade applications, a kit
added without an order, notes with commas, quotes and newlines, Japanese names, a
cell beginning with `=`, blank optional fields, and timestamps with and without
microseconds.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import event, text

from app.db import get_sessionmaker
from app.models.base import Base

#: Namespace for the fixture's ids. Changing it rewrites every id in the fixture.
NAMESPACE = uuid.UUID("6c1f7d0e-3a0b-5d55-9a43-2f6c7e0a3303")


def fixture_id(table: str, n: int) -> uuid.UUID:
    """The id of the `n`th row the seed writes to `table`."""
    return uuid.uuid5(NAMESPACE, f"{table}:{n}")


#: `applied_at` by application, in the order the seed applies them. 1 and 3 tie.
APPLIED_AT = {
    1: "2026-04-05T06:00:00+00:00",
    2: "2026-04-21T07:30:15.500000+00:00",
    3: "2026-04-05T06:00:00+00:00",
}


@contextmanager
def deterministic_ids() -> Iterator[None]:
    """Every row the ORM inserts without an id gets `uuid5(NAMESPACE, "<table>:<n>")`
    until exit.

    An ORM event rather than a swapped column default: the tables share one default
    object through their mixin, and once any statement had inserted explicit ids —
    an import earlier in the same process — SQLAlchemy stopped consulting the
    swapped default and the seed came out with random ids. `before_insert` runs for
    every unit-of-work insert, and the services write through nothing else.
    """
    counters: dict[str, int] = defaultdict(int)

    def assign(_mapper, _connection, target) -> None:
        if getattr(target, "id", None) is not None:
            return
        table = target.__table__.name
        counters[table] += 1
        target.id = fixture_id(table, counters[table])

    event.listen(Base, "before_insert", assign, propagate=True)
    try:
        yield
    finally:
        event.remove(Base, "before_insert", assign)


def at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


async def _ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


async def seed(client) -> None:
    """Build the golden collection on an empty instance."""
    with deterministic_ids():
        kit_clocks = await _seed(client)
    await _pin_clocks(kit_clocks)


async def _seed(client) -> dict[str, dict[str, str]]:
    await _ok(
        await client.patch(
            "/settings",
            json={
                "interface_language": "en-AU",
                "formatting_locale": "en-AU",
                "time_zone": "Australia/Sydney",
                "date_style": "medium",
                "hour_cycle": "h23",
                "reference_currency": "AUD",
            },
        )
    )

    # --- retailers: a full report card, a Japanese name, a bare name -------------
    hlj = await _ok(
        await client.post(
            "/retailers",
            json={
                "name": "Hobby Link Japan",
                "url": "https://www.hlj.com/",
                "rating": 5,
                "packing_quality": "excellent",
                "shipping_speed": "very_fast",
                "would_order_again": "yes",
                "notes": 'Ships EMS, DHL and SAL. Says "well packed",\nand means it.',
            },
        ),
        201,
    )
    amiami = await _ok(
        await client.post(
            "/retailers",
            json={
                "name": "あみあみ",
                "rating": 3,
                "packing_quality": "below_average",
                "shipping_speed": "slow",
                "would_order_again": "maybe",
            },
        ),
        201,
    )
    souq = await _ok(
        await client.post("/retailers", json={"name": "Souq Hobby Kuwait"}),
        201,
    )
    local = await _ok(await client.post("/retailers", json={"name": "Corner Hobbies"}), 201)

    # --- catalog stock acquired without an order (a stocktake) -------------------
    nippers = await _ok(
        await client.post(
            "/tools",
            json={
                "name": "Godhand Ultimate Nippers",
                "category": "cutting",
                "quantity_on_hand": 1,
                "unit_cost_reference_minor": 5280,
                "unit_cost_reference_currency": "JPY",
                "condition_notes": "Sharp. Never on runner gates thicker than 2mm, ever.",
            },
        ),
        201,
    )
    await _ok(
        await client.post(
            "/tools",
            json={
                "name": "Sanding sticks",
                "category": "filing",
                "quantity_on_hand": 6,
                "unit_cost_reference_minor": 1750,
                "unit_cost_reference_currency": "KWD",
            },
        ),
        201,
    )
    await _ok(
        await client.post(
            "/tools", json={"name": "Hobby knife", "category": "cutting", "quantity_on_hand": 2}
        ),
        201,
    )
    await _ok(
        await client.post(
            "/consumables",
            json={
                "name": "Tamiya Extra Thin Cement",
                "category": "cement",
                "quantity_on_hand": 1,
                "low_stock_threshold": 1,
            },
        ),
        201,
    )
    metal_parts = await _ok(
        await client.post(
            "/upgrades",
            json={"name": "Metal thruster set", "manufacturer": "Madworks", "quantity_on_hand": 4},
        ),
        201,
    )
    await _ok(
        await client.post(
            "/display-items",
            json={
                "name": "Action Base 2",
                "category": "stand",
                "scale": "1/144",
                "manufacturer": "Bandai",
                "quantity_on_hand": 3,
                "notes": "=SUM(A1:A3) is text here, not a formula",
            },
        ),
        201,
    )
    await _ok(
        await client.post(
            "/display-items",
            json={
                "name": "Scratch-built hangar wall",
                "category": "scenery",
                "quantity_on_hand": 1,
            },
        ),
        201,
    )

    # --- orders ------------------------------------------------------------------
    # Received, in yen, with a two-kit line and three catalog lines (one an existing
    # tool, two created inline), shipping, a conversion snapshot on two lines, and a
    # receipt instant with microseconds.
    await _ok(
        await client.post(
            "/orders",
            json={
                "retailer_id": hlj["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-88213",
                "delivery_service": "EMS",
                "tracking_number": "EM123456789JP",
                "tracking_url": "https://trackings.post.japanpost.jp/?q=EM123456789JP&lang=en",
                "shipping_cost_minor": 2300,
                "currency_code": "JPY",
                "received": True,
                "shipped_at": "2026-03-16T01:02:03+00:00",
                "received_at": "2026-03-20T04:05:06.250000+00:00",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 2,
                        "unit_price_minor": 2450,
                        "currency_code": "JPY",
                        "converted_price_minor": 2499,
                        "converted_currency_code": "AUD",
                        "kit": {
                            "name": "RX-79[G] Gundam Ground Type",
                            "grade": "HG",
                            "kit_number": "HGUC 210",
                        },
                    },
                    {
                        "item_type": "tool",
                        "quantity": 1,
                        "unit_price_minor": 5280,
                        "currency_code": "JPY",
                        "catalog_ref_id": nippers["id"],
                    },
                    {
                        "item_type": "consumable",
                        "quantity": 3,
                        "unit_price_minor": 330,
                        "currency_code": "JPY",
                        "converted_price_minor": 337,
                        "converted_currency_code": "AUD",
                        "new_item": {
                            "name": "Gundam Marker GM01 Black",
                            "category": "marker",
                            "low_stock_threshold": 2,
                        },
                    },
                    {
                        "item_type": "upgrade",
                        "quantity": 2,
                        "unit_price_minor": 1100,
                        "currency_code": "JPY",
                        "new_item": {
                            "name": "Waterslide decal 08th MS Team",
                            "manufacturer": "Delpi",
                        },
                    },
                ],
            },
        ),
        201,
    )

    # Shipped, not received: the kit is in the mail. Dinar, three decimals.
    await _ok(
        await client.post(
            "/orders",
            json={
                "retailer_id": souq["id"],
                "order_date": "2026-05-02",
                "order_number": "SQ/2026/0042",
                "delivery_service": "Aramex",
                "shipping_cost_minor": 1250,
                "currency_code": "KWD",
                "shipped_at": "2026-05-05T09:30:00+00:00",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 18375,
                        "currency_code": "KWD",
                        "converted_price_minor": 9112,
                        "converted_currency_code": "AUD",
                        "kit": {"name": "Gundam Barbatos Lupus Rex", "grade": "MG"},
                    },
                    {
                        "item_type": "display",
                        "quantity": 1,
                        "unit_price_minor": 4500,
                        "currency_code": "KWD",
                        "new_item": {"name": "Diorama base — desert", "category": "base"},
                    },
                ],
            },
        ),
        201,
    )

    # A pre-order: placed, nothing shipped, no order number, no delivery service.
    await _ok(
        await client.post(
            "/orders",
            json={
                "retailer_id": amiami["id"],
                "order_date": "2026-06-30",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 8800,
                        "currency_code": "JPY",
                        "kit": {
                            "name": "νガンダム Ver.Ka",
                            "grade": "MG",
                            "kit_number": "5065231",
                            "status": "pre_ordered",
                        },
                    }
                ],
            },
        ),
        201,
    )

    # Bought over the counter: received at entry, no delivery, Australian dollars.
    await _ok(
        await client.post(
            "/orders",
            json={
                "retailer_id": local["id"],
                "order_date": "2026-02-01",
                "currency_code": "AUD",
                "received": True,
                "received_at": "2026-02-01T05:00:00+00:00",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 4995,
                        "currency_code": "AUD",
                        "kit": {"name": "Zaku II", "grade": "HG", "scale": "1/144"},
                    }
                ],
            },
        ),
        201,
    )

    # --- kits ----------------------------------------------------------------------
    every_kit = await _ok(await client.get("/kits"))
    kits = {k["name"]: k for k in every_kit}
    # The two-kit line's pair: the line spawned them, so neither has a name of its own.
    finished, benched = sorted(
        (k for k in every_kit if k["name"] == "RX-79[G] Gundam Ground Type"), key=lambda k: k["id"]
    )

    await _ok(
        await client.patch(
            f"/kits/{finished['id']}",
            json={
                "status": "building",
                "series": "機動戦士ガンダム 第08MS小隊",
                "build_started_at": "2026-03-21T10:00:00+00:00",
            },
        )
    )
    await _ok(
        await client.patch(
            f"/kits/{finished['id']}",
            json={
                "status": "complete",
                "rating": 4,
                "build_completed_at": "2026-04-11T08:45:30.000125+00:00",
                "build_notes": 'Panel lined, "weathered" lightly.\nTopcoat: flat, two passes.',
            },
        )
    )
    await _ok(
        await client.patch(
            f"/kits/{benched['id']}",
            json={"status": "building", "build_started_at": "2026-04-20T00:00:00+00:00"},
        )
    )

    # Added without an order: a gift.
    gift = await _ok(
        await client.post(
            "/kits",
            json={
                "name": "SD Gundam EX-Standard Strike Freedom",
                "grade": "SD",
                "series": "Gundam SEED Destiny",
                "build_notes": "Birthday present, 2025",
            },
        ),
        201,
    )

    # --- upgrade applications --------------------------------------------------------
    # The finished kit's two applications share an instant (`_pin_clocks`), so their
    # order in the archive is the export's tiebreak alone. The third application's id
    # sorts before the first's, so the order they were written in and the order of
    # their ids disagree, and an export that lost the tiebreak would show it.
    decal = next(
        u for u in await _ok(await client.get("/upgrades")) if u["manufacturer"] == "Delpi"
    )
    for upgrade, kit, quantity in (
        (metal_parts, finished, 2),
        (metal_parts, benched, 1),
        (decal, finished, 1),
    ):
        await _ok(
            await client.post(
                f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit["id"], "quantity": quantity}
            ),
            201,
        )

    # --- the clocks the requests could not state -------------------------------------
    zaku = kits["Zaku II"]
    barbatos = kits["Gundam Barbatos Lupus Rex"]
    nu = kits["νガンダム Ver.Ka"]
    return {
        # kit id -> created_at, updated_at, status_updated_at
        zaku["id"]: {
            "created_at": "2026-02-01T05:00:00+00:00",
            "updated_at": "2026-02-01T05:00:00+00:00",
            "status_updated_at": "2026-02-01T05:00:00+00:00",
        },
        finished["id"]: {
            "created_at": "2026-03-14T11:00:00+00:00",
            "updated_at": "2026-04-11T08:45:30.000125+00:00",
            "status_updated_at": "2026-04-11T08:45:30.000125+00:00",
        },
        benched["id"]: {
            "created_at": "2026-03-14T11:00:00+00:00",
            "updated_at": "2026-04-20T00:00:00+00:00",
            "status_updated_at": "2026-04-20T00:00:00+00:00",
        },
        barbatos["id"]: {
            "created_at": "2026-05-02T03:15:00+00:00",
            "updated_at": "2026-05-05T09:30:00+00:00",
            "status_updated_at": "2026-05-05T09:30:00+00:00",
        },
        nu["id"]: {
            "created_at": "2026-06-30T12:00:00+00:00",
            "updated_at": "2026-06-30T12:00:00+00:00",
            "status_updated_at": "2026-06-30T12:00:00+00:00",
        },
        gift["id"]: {
            "created_at": "2026-07-04T00:00:00+00:00",
            "updated_at": "2026-07-04T00:00:00+00:00",
            "status_updated_at": "2026-07-04T00:00:00+00:00",
        },
    }


async def _pin_clocks(kit_clocks: dict[str, dict[str, str]]) -> None:
    async with get_sessionmaker()() as session:
        for kit_id, clocks in kit_clocks.items():
            result = await session.execute(
                text(
                    "UPDATE kits SET created_at = :created_at, updated_at = :updated_at, "
                    "status_updated_at = :status_updated_at WHERE id = :id"
                ),
                {"id": uuid.UUID(kit_id), **{k: at(v) for k, v in clocks.items()}},
            )
            assert result.rowcount == 1, kit_id
        for n, stamp in APPLIED_AT.items():
            result = await session.execute(
                text("UPDATE upgrade_applications SET applied_at = :stamp WHERE id = :id"),
                {"id": fixture_id("upgrade_applications", n), "stamp": at(stamp)},
            )
            assert result.rowcount == 1, n
        await session.commit()

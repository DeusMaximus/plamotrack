import pytest


async def test_create_kit_derives_scale_from_grade(client):
    resp = await client.post("/kits", json={"name": "Zaku II Ver.Ka", "grade": "MG"})
    assert resp.status_code == 201
    kit = resp.json()
    assert kit["scale"] == "1/100"
    assert kit["status"] == "backlog"
    assert kit["order_item_id"] is None


async def test_create_kit_explicit_scale_wins(client):
    resp = await client.post(
        "/kits", json={"name": "Weird resin kit", "grade": "HG", "scale": "1/120"}
    )
    assert resp.json()["scale"] == "1/120"


async def test_status_patch_bumps_status_updated_at(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()

    resp = await client.patch(f"/kits/{created['id']}", json={"status": "building"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["status"] == "building"
    assert updated["status_updated_at"] != created["status_updated_at"]


async def test_non_status_patch_leaves_status_updated_at(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()

    updated = (
        await client.patch(f"/kits/{created['id']}", json={"build_notes": "panel lining done"})
    ).json()
    assert updated["build_notes"] == "panel lining done"
    assert updated["status_updated_at"] == created["status_updated_at"]


async def test_invalid_status_rejected(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()
    resp = await client.patch(f"/kits/{created['id']}", json={"status": "painting"})
    assert resp.status_code == 422


async def test_rating_bounds(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()
    assert (await client.patch(f"/kits/{created['id']}", json={"rating": 6})).status_code == 422
    assert (await client.patch(f"/kits/{created['id']}", json={"rating": 5})).status_code == 200


async def test_list_kits_filters(client):
    await client.post("/kits", json={"name": "A", "grade": "HG"})
    await client.post("/kits", json={"name": "B", "grade": "MG", "status": "building"})

    building = (await client.get("/kits", params={"status": "building"})).json()
    assert [k["name"] for k in building] == ["B"]

    hg = (await client.get("/kits", params={"grade": "hg"})).json()  # case-insensitive
    assert [k["name"] for k in hg] == ["A"]


async def test_delete_kit(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()
    assert (await client.delete(f"/kits/{created['id']}")).status_code == 204
    assert (await client.get(f"/kits/{created['id']}")).status_code == 404


# --- sort and limit (§13.4, #232) ------------------------------------------------


async def _seed_two_per_status(client) -> None:
    """Two rows per status (the "rows diverging" rule), created oldest→newest as
    Zaku, Gouf, Dom, Acguy; then Zaku moves to building last, so its status
    clock is the newest while its creation is the oldest — the two clocks
    disagree, which is what makes `recent` distinguishable from `created`."""
    zaku = (await client.post("/kits", json={"name": "Zaku II", "grade": "HG"})).json()
    await client.post("/kits", json={"name": "Gouf", "grade": "HG"})
    await client.post("/kits", json={"name": "Dom", "grade": "HG", "status": "building"})
    await client.post("/kits", json={"name": "Acguy", "grade": "HG", "status": "building"})
    moved = await client.patch(f"/kits/{zaku['id']}", json={"status": "building"})
    assert moved.status_code == 200, moved.text


def _names(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [kit["name"] for kit in resp.json()]


async def test_the_status_clock_is_the_api_clock_on_create_too(client, monkeypatch):
    """`recent` compares `status_updated_at` across rows, so every path stamps it
    from one clock. A create took the database's (the column's server default)
    while a move took the API's, and a container clock a few milliseconds ahead
    of its host ranked a kit created just before a move above it. The API's clock
    is frozen here; a stamp that still came from the database would be today's."""
    from datetime import UTC, datetime

    frozen = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr("app.models.kits.datetime", FrozenDatetime)
    created = await client.post("/kits", json={"name": "Frozen", "grade": "HG"})
    assert created.status_code == 201, created.text
    stamp = datetime.fromisoformat(created.json()["status_updated_at"].replace("Z", "+00:00"))
    assert stamp == frozen


async def test_list_kits_sort_recent_is_the_status_clock_newest_first(client):
    await _seed_two_per_status(client)
    assert _names(await client.get("/kits")) == ["Zaku II", "Gouf", "Dom", "Acguy"]
    assert _names(await client.get("/kits", params={"sort": "created"})) == [
        "Zaku II",
        "Gouf",
        "Dom",
        "Acguy",
    ]
    assert _names(await client.get("/kits", params={"sort": "recent"})) == [
        "Zaku II",
        "Acguy",
        "Dom",
        "Gouf",
    ]
    assert _names(await client.get("/kits", params={"sort": "name"})) == [
        "Acguy",
        "Dom",
        "Gouf",
        "Zaku II",
    ]
    # Sort composes with the filters: Home's "view all" link.
    assert _names(await client.get("/kits", params={"status": "building", "sort": "recent"})) == [
        "Zaku II",
        "Acguy",
        "Dom",
    ]


async def test_list_kits_limit_is_the_first_n_of_the_sort(client):
    await _seed_two_per_status(client)
    assert _names(await client.get("/kits", params={"sort": "recent", "limit": 2})) == [
        "Zaku II",
        "Acguy",
    ]
    assert _names(await client.get("/kits", params={"limit": 1})) == ["Zaku II"]
    assert len(_names(await client.get("/kits", params={"limit": 50}))) == 4


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "newest"},
        {"sort": ""},
        {"sort": "RECENT"},
        {"limit": "0"},
        {"limit": "-1"},
        {"limit": "ten"},
    ],
)
async def test_list_kits_refuses_a_sort_or_limit_outside_the_vocabulary(client, params):
    assert (await client.get("/kits", params=params)).status_code == 422

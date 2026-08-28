"""The instance-settings singleton (§6.1, #23).

The REST surface, the service semantics behind it, and the one thing every write
path now reads from it: the reference currency. The bootstrap values asserted
here are literals on purpose — asserting against `instance_settings.DEFAULTS`
would let a mutation of the defaults move the test with it.

Value axes per the checklist: explicit null (refused — nothing is nullable),
empty and whitespace-only strings, the stored default restated, and a genuinely
different value. The state axis is which fields the PATCH carries.

The formatting-locale shape cases come from
`frontend/src/lib/__fixtures__/locale-cases.json`, which
`frontend/src/lib/locale-cases.test.ts` also reads against the real `Intl` —
a tag this backend stores that the consuming formatter throws on is the P3-2
of the PR #159 review, and the shared fixture is what keeps the two judgements
from drifting apart. Add locale cases there, not here.

`frontend/src/i18n/manifest.json` is the second shared frontend file (#22): the
interface-language catalogues ship there, and the parity test below holds
`SUPPORTED_INTERFACE_LANGUAGES` to exactly the manifest's enabled tags —
enabling a language means flipping `enabled` AND extending the tuple, one PR.
"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import text as sa_text

from app.db import get_sessionmaker, session_scope
from app.schemas.settings import InstanceSettingsUpdate
from app.services import instance_settings
from app.services.write_gate import _COLLECTION_WRITE_LOCK

pytestmark = pytest.mark.anyio

_LOCALE_CASES = json.loads(
    (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/__fixtures__/locale-cases.json"
    ).read_text(encoding="utf-8")
)

_I18N_MANIFEST = json.loads(
    (Path(__file__).resolve().parents[2] / "frontend/src/i18n/manifest.json").read_text(
        encoding="utf-8"
    )
)


def test_supported_interface_languages_are_the_manifests_enabled_tags():
    """The membership test and the shipped catalogues cannot drift (#22).

    `validate_interface_language` admits what this tuple holds; the browser can
    render what the manifest enables. If either moves alone, an owner can store
    a language no client can display, or a shipped catalogue no setting can
    reach — so this asserts equality, not subset, in both directions.
    """
    enabled = {entry["tag"] for entry in _I18N_MANIFEST["languages"] if entry["enabled"]}
    assert set(instance_settings.SUPPORTED_INTERFACE_LANGUAGES) == enabled
    # The unconditional fallback (§6.1) may never be disabled.
    assert "en-AU" in enabled


async def test_meta_advertises_the_supported_interface_languages(client):
    """`GET /meta` names what a PATCH will accept (#27), so a client can build a
    language selector without hardcoding the list. Held to the manifest — the
    same cross-layer fixture the parity test above reads — not to the tuple, so
    the wire claim and the shipped catalogues cannot drift apart either."""
    advertised = (await client.get("/meta")).json()["supported_interface_languages"]
    assert advertised == ["en-AU"]
    enabled = {entry["tag"] for entry in _I18N_MANIFEST["languages"] if entry["enabled"]}
    assert set(advertised) == enabled


#: What a fresh instance answers — the migration's seed, restated as literals.
BOOTSTRAP = {
    "interface_language": "en-AU",
    "formatting_locale": "en-AU",
    "time_zone": "UTC",
    "date_style": "locale",
    "hour_cycle": "locale",
    "reference_currency": "AUD",
}

FIELDS = tuple(BOOTSTRAP)


async def read_settings(client) -> dict:
    resp = await client.get("/settings")
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- reading --------------------------------------------------------------------


async def test_get_returns_the_bootstrap_row(client):
    settings = await read_settings(client)
    assert settings.pop("updated_at") is not None
    assert settings == BOOTSTRAP


async def test_a_missing_row_is_a_500_not_a_quiet_default(http_client):
    # Deployment breakage (nothing at runtime can delete the row), so the honest
    # answer is a server error naming the repair, not invented defaults.
    async with session_scope() as session:
        await session.execute(sa_text("DELETE FROM instance_settings"))
    assert (await http_client.get("/settings")).status_code == 500


# --- updating -------------------------------------------------------------------


async def test_patch_updates_only_the_supplied_fields(client):
    resp = await client.patch("/settings", json={"time_zone": "Australia/Sydney"})
    assert resp.status_code == 200, resp.text
    settings = await read_settings(client)
    assert settings["time_zone"] == "Australia/Sydney"
    for field, value in BOOTSTRAP.items():
        if field != "time_zone":
            assert settings[field] == value


async def test_patch_with_no_fields_changes_nothing(client):
    assert (await client.patch("/settings", json={})).status_code == 200
    settings = await read_settings(client)
    settings.pop("updated_at")
    assert settings == BOOTSTRAP


async def test_restating_the_stored_value_succeeds_quietly(client):
    assert (
        await client.patch("/settings", json={"interface_language": "en-AU"})
    ).status_code == 200
    assert (await read_settings(client))["interface_language"] == "en-AU"


@pytest.mark.parametrize(
    ("payload", "canonical"),
    [
        ({"formatting_locale": "EN-au"}, {"formatting_locale": "en-AU"}),
        ({"formatting_locale": "zh-hans-tw"}, {"formatting_locale": "zh-Hans-TW"}),
        # Variants sort into UTS 35's canonical order — Intl sorts them, so the
        # other spelling must not be storable as a second setting.
        ({"formatting_locale": "sl-rozaj-biske"}, {"formatting_locale": "sl-biske-rozaj"}),
        ({"time_zone": "australia/sydney"}, {"time_zone": "Australia/Sydney"}),
        ({"time_zone": "utc"}, {"time_zone": "UTC"}),
        ({"reference_currency": "jpy"}, {"reference_currency": "JPY"}),
        ({"interface_language": "EN-AU"}, {"interface_language": "en-AU"}),
        ({"date_style": "medium"}, {"date_style": "medium"}),
        ({"hour_cycle": "h23"}, {"hour_cycle": "h23"}),
    ],
)
async def test_values_are_canonicalised_on_the_way_in(client, payload, canonical):
    resp = await client.patch("/settings", json=payload)
    assert resp.status_code == 200, resp.text
    settings = await read_settings(client)
    for field, value in canonical.items():
        assert settings[field] == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # A well-formed tag for a language this build doesn't ship.
        ("interface_language", "fr-FR"),
        ("interface_language", "not a tag!"),
        ("interface_language", ""),
        ("formatting_locale", "not a tag!"),
        ("formatting_locale", ""),
        ("formatting_locale", "   "),
        # Extension subtags would smuggle in a second hour-cycle/calendar setting.
        ("formatting_locale", "en-AU-u-hc-h23"),
        # `Intl` throws on both of these, so storing either hands the Settings
        # page a formatter error (PR #159 review, P3-2): a repeated variant, and
        # a four-letter language subtag (reserved in BCP 47).
        ("formatting_locale", "en-abcde-abcde"),
        ("formatting_locale", "abcd"),
        ("time_zone", "Mars/Olympus_Mons"),
        ("time_zone", ""),
        ("reference_currency", "AU$"),
        ("reference_currency", "AUDD"),
        ("reference_currency", ""),
        # Three Unicode "letters" are not three ASCII letters (PR #159 review,
        # P2) — isalpha() thought otherwise, on the CSV side.
        ("reference_currency", "ÅUD"),
        # Enum fields: membership is pydantic's, same 422 either way.
        ("date_style", "sideways"),
        ("hour_cycle", "h25"),
    ],
)
async def test_invalid_values_are_refused_and_nothing_changes(http_client, field, value):
    resp = await http_client.patch("/settings", json={field: value})
    assert resp.status_code == 422, resp.text
    settings = await read_settings(http_client)
    settings.pop("updated_at")
    assert settings == BOOTSTRAP


@pytest.mark.parametrize("field", FIELDS)
async def test_explicit_null_is_refused_for_every_field(http_client, field):
    # Omitting a field means "leave it"; null is an instruction the row can't
    # hold, and silently treating it as either reading would surprise someone.
    resp = await http_client.patch("/settings", json={field: None})
    assert resp.status_code == 422, resp.text
    assert "can't be cleared" in resp.json()["detail"]
    settings = await read_settings(http_client)
    settings.pop("updated_at")
    assert settings == BOOTSTRAP


async def test_unknown_fields_are_refused(http_client):
    # extra="forbid": a typo'd field name must not read as a successful no-op.
    assert (await http_client.patch("/settings", json={"timezone": "UTC"})).status_code == 422


@pytest.mark.parametrize("case", _LOCALE_CASES["accepted"], ids=lambda case: repr(case["input"]))
async def test_locale_shapes_the_frontends_intl_accepts_are_accepted(case):
    assert instance_settings.canonical_locale(case["input"]) == case["canonical"]


@pytest.mark.parametrize(
    "case",
    _LOCALE_CASES["refused_everywhere"] + _LOCALE_CASES["refused_by_policy"],
    ids=lambda case: repr(case["input"]),
)
async def test_locale_shapes_this_instance_refuses_are_refused(case):
    # Both lists refuse here; the frontend suite is what tells them apart
    # (Intl throws on refused_everywhere and accepts refused_by_policy).
    with pytest.raises(ValueError):
        instance_settings.canonical_locale(case["input"])


async def test_concurrent_field_updates_land_without_overwriting_each_other():
    """A final-state control, not a serialization proof (PR #159 review, P3-3):
    SQLAlchemy only UPDATEs dirty columns, so two per-field writers can't erase
    each other even unserialized — the review measured exactly that by removing
    both locks under this test's previous name. What it pins is that write
    shape: an `update_instance_settings` that ever grew a read-copy-writeback of
    the whole row would go red here. The serialization claim itself lives in
    `test_an_update_waits_its_turn_on_the_write_gate`, which observes the
    blocking edge directly."""

    async def set_fields(**fields):
        async with session_scope() as session:
            await instance_settings.update_instance_settings(
                session, InstanceSettingsUpdate(**fields)
            )

    await asyncio.gather(
        set_fields(time_zone="Australia/Sydney"),
        set_fields(reference_currency="JPY"),
    )
    async with session_scope() as session:
        row = await instance_settings.get_instance_settings(session)
        assert row.time_zone == "Australia/Sydney"
        assert row.reference_currency == "JPY"


async def test_an_update_waits_its_turn_on_the_write_gate():
    """Rule 7.1: the gate comes before the locked read, so a settings change
    serializes against *every* writer — including an apply_import whose plan is
    reading this row — not merely against another settings PATCH.

    The wait is observed as the exact blocking edge, never slept for and never
    counted: `pg_blocking_pids(updater)` must contain the holder's own backend
    pid. Counting advisory waiters database-wide let an unrelated waiter satisfy
    the assertion with the gate deleted (PR #159 review, P3-3 — Codex parked a
    decoy on a different key and watched the stg-5 mutant survive five times).
    The row lock alone cannot pass this test either: the holder never touches
    the row, so only the gate can put the holder on the updater's blocker list.
    """
    loop = asyncio.get_running_loop()
    updater_pid: asyncio.Future[int] = loop.create_future()
    async with get_sessionmaker()() as holder:
        await holder.execute(
            sa_text("SELECT pg_advisory_xact_lock(:key)"), {"key": _COLLECTION_WRITE_LOCK}
        )
        holder_pid = await holder.scalar(sa_text("SELECT pg_backend_pid()"))

        async def update() -> None:
            async with session_scope() as session:
                updater_pid.set_result(await session.scalar(sa_text("SELECT pg_backend_pid()")))
                await instance_settings.update_instance_settings(
                    session, InstanceSettingsUpdate(reference_currency="JPY")
                )

        async def parked_behind_holder() -> bool:
            async with session_scope() as probe:
                return bool(
                    await probe.scalar(
                        sa_text("SELECT :holder = ANY(pg_blocking_pids(:waiter))"),
                        {"holder": holder_pid, "waiter": updater_pid.result()},
                    )
                )

        task = asyncio.create_task(update())
        await asyncio.wait_for(asyncio.shield(updater_pid), timeout=5)
        for _ in range(400):
            if task.done() or await parked_behind_holder():
                break
            await asyncio.sleep(0.01)
        assert not task.done(), "the update finished while the gate was held"
        assert await parked_behind_holder()
        await holder.rollback()  # the gate is transaction-scoped: this releases it
    await task
    async with session_scope() as session:
        row = await instance_settings.get_instance_settings(session)
        assert row.reference_currency == "JPY"


# --- what the rest of the app reads from it -------------------------------------


async def test_meta_reads_the_row_not_a_process_cache(client):
    # The pre-#23 value was env-backed and lru_cached, so a change needed a
    # restart. Same process, two requests: the second must see the new value.
    assert (await client.get("/meta")).json()["reference_currency"] == "AUD"
    await client.patch("/settings", json={"reference_currency": "JPY"})
    assert (await client.get("/meta")).json()["reference_currency"] == "JPY"


async def test_new_conversion_snapshots_default_to_the_current_setting(client, retailer):
    # §6: the snapshot's currency is resolved at write time from the *current*
    # setting — and only for the new snapshot; nothing stored is restated.
    await client.patch("/settings", json={"reference_currency": "JPY"})
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "USD",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 2999,
                    "currency_code": "USD",
                    "converted_price_minor": 4500,
                    "kit": {"name": "RG Nu Gundam", "grade": "RG"},
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    line = resp.json()["items"][0]
    assert line["converted_currency_code"] == "JPY"


async def test_an_edit_that_adds_a_snapshot_uses_the_current_setting(client, retailer):
    # The update path's fallback chain ends at the settings row too (§6): a line
    # that never had a snapshot gains one under the currency in effect at edit
    # time — there is no stored code to defer to.
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "USD",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 2999,
                    "currency_code": "USD",
                    "kit": {"name": "RG Sazabi", "grade": "RG"},
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()
    line_id = order["items"][0]["id"]
    await client.patch("/settings", json={"reference_currency": "JPY"})
    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line_id,
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 2999,
                    "currency_code": "USD",
                    "converted_price_minor": 4500,
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["converted_currency_code"] == "JPY"


async def test_changing_the_setting_never_restates_a_stored_snapshot(client, retailer):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 4500,
                    "currency_code": "AUD",
                    "converted_price_minor": 4500,
                    "kit": {"name": "HG Barbatos", "grade": "HG"},
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["id"]
    await client.patch("/settings", json={"reference_currency": "JPY"})
    stored = (await client.get(f"/orders/{order_id}")).json()["items"][0]
    assert stored["converted_currency_code"] == "AUD"

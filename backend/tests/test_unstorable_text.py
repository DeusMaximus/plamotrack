"""Text the database cannot hold is a refusal naming the field, never a 500 (#346).

Rule 6, on rule 1's three writers: REST and MCP share the request schemas, the
importer has `parse_text`, and the filters that reach a query as an argument have the
services. `services/text.py` is the one predicate they all read.

Driven through `http_client`, whose 500 comes back as a response: the point of each
test is which status a bad value earns.
"""

import inspect
import json
import types
import typing

import pytest
from fastapi.dependencies.utils import get_dependant
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel

from app.auth.registry import iter_effective_routes
from app.main import app
from app.mcp import mcp
from app.schemas.base import RequestModel
from app.services.portability import spec, starter_sheet
from app.services.portability.spec import parse_text
from app.services.text import is_storable_text, require_storable_text
from tests.oidc_fake import FakeIdp
from tests.test_mcp_oauth import NATIVE_CB, _bind_owner, _pkce, _state_rows, authorize, oauth_app
from tests.test_portability import apply, make_csv, preview, zip_members

UNSTORABLE = [
    pytest.param("a\x00b", id="NUL inside"),
    pytest.param("\x00", id="NUL alone"),
    pytest.param(" \x00 ", id="NUL inside whitespace"),
    pytest.param("a\ud800b", id="unpaired leading surrogate"),
    pytest.param("\udc00", id="unpaired trailing surrogate"),
]
NUL_ONLY = [pytest.param("a\x00b", id="NUL inside"), pytest.param("\x00", id="NUL alone")]
#: Text that looks as unusual and is not: the control on every refusal.
ORDINARY = [
    pytest.param("Zaku\tII\nMk", id="tab and newline"),
    pytest.param("\x01bell\x7f", id="other control characters"),
    pytest.param("😀", id="outside the BMP, a surrogate pair in JSON"),
    pytest.param("ホビーサーチ", id="not English"),
    pytest.param("�", id="the replacement character"),
]
ZERO_ID = "00000000-0000-0000-0000-000000000000"

# --- the predicate -------------------------------------------------------------------


@pytest.mark.parametrize("value", UNSTORABLE)
def test_what_a_column_cannot_hold(value):
    assert not is_storable_text(value)
    with pytest.raises(ValueError, match="can't store"):
        require_storable_text(value)


@pytest.mark.parametrize("value", [*ORDINARY, pytest.param("", id="empty")])
def test_what_it_can(value):
    assert is_storable_text(value)
    assert require_storable_text(value) == value


# --- REST: every writer that takes a body --------------------------------------------

#: (the collection, a body it accepts, the free-text fields to spoil).
CREATES = [
    ("/kits", {"name": "n", "grade": "HG"}, ["name", "grade", "scale", "kit_number", "series"]),
    ("/kits", {"name": "n", "grade": "HG"}, ["build_notes"]),
    ("/retailers", {"name": "n"}, ["name", "url", "notes"]),
    ("/tools", {"name": "n", "category": "c"}, ["name", "category", "condition_notes"]),
    ("/consumables", {"name": "n", "category": "c"}, ["name", "category"]),
    ("/upgrades", {"name": "n", "manufacturer": "m"}, ["name", "manufacturer"]),
    (
        "/display-items",
        {"name": "n", "category": "c"},
        ["name", "category", "scale", "manufacturer", "notes"],
    ),
]
CREATE_CASES = [(path, body, field) for path, body, fields in CREATES for field in fields]


def _the_refusal(resp, field: str) -> None:
    assert resp.status_code == 422, f"{resp.status_code} {resp.text[:200]}"
    body = resp.json()
    assert body["code"] == "request.validation", body
    # `value_error` is our validator. A constrained `str` (a `min_length`, a pattern)
    # hands the value to pydantic's core first, which has its own word for a value with
    # no UTF-8 form, so that one never reaches ours. Either is a named refusal.
    types_for_field = {
        finding["type"] for finding in body["params"]["errors"] if finding["field"] == field
    }
    assert types_for_field & {"value_error", "string_unicode"}, body


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(("path", "base", "field"), CREATE_CASES)
async def test_a_create_refuses_it_and_stores_nothing(http_client, path, base, field, value):
    resp = await http_client.post(
        path,
        content=_json({**base, field: value}),
        headers={"content-type": "application/json"},
    )
    _the_refusal(resp, field)
    assert (await http_client.get(path)).json() == []


def _json(body: dict) -> str:
    """`json=` would hand httpx's encoder a surrogate it cannot encode; `json.dumps`
    spells it `\\ud800`, which is what a client sends."""
    return json.dumps(body)


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(("path", "base", "field"), CREATE_CASES)
async def test_an_update_refuses_it_and_leaves_the_row(http_client, path, base, field, value):
    """The other state: a row exists, and it stays as it was."""
    created = await http_client.post(path, json=base)
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]

    resp = await http_client.patch(
        f"{path}/{row_id}",
        content=_json({field: value}),
        headers={"content-type": "application/json"},
    )
    _the_refusal(resp, field)
    [row] = (await http_client.get(path)).json()
    assert row == created.json() | {
        key: row[key] for key in ("updated_at", "status_updated_at") if key in row
    }


@pytest.mark.parametrize("value", ORDINARY)
@pytest.mark.parametrize(
    ("path", "base", "field"),
    [
        ("/kits", {"name": "n", "grade": "HG"}, "build_notes"),
        ("/retailers", {"name": "n"}, "notes"),
    ],
)
async def test_ordinary_text_is_still_stored_as_written(http_client, path, base, field, value):
    resp = await http_client.post(path, json={**base, field: value})
    assert resp.status_code == 201, resp.text
    assert resp.json()[field] == value


@pytest.mark.parametrize("value", [None, ""])
async def test_null_and_empty_are_not_what_it_refuses(http_client, value):
    resp = await http_client.post(
        "/kits", json={"name": "n", "grade": "HG", "series": None, "build_notes": value}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["build_notes"] == value


async def _order_body(http_client) -> dict:
    retailer = (await http_client.post("/retailers", json={"name": "Shop"})).json()
    return {
        "retailer_id": retailer["id"],
        "order_date": "2026-01-01",
        "currency_code": "AUD",
        "items": [
            {
                "item_type": "kit",
                "quantity": 1,
                "unit_price_minor": 100,
                "currency_code": "AUD",
                "kit": {"name": "Zaku", "grade": "HG"},
            }
        ],
    }


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(
    ("spoil", "field"),
    [
        (lambda b, v: b.update(order_number=v), "order_number"),
        (lambda b, v: b.update(delivery_service=v), "delivery_service"),
        (lambda b, v: b.update(tracking_number=v), "tracking_number"),
        (lambda b, v: b.update(tracking_url=v), "tracking_url"),
        (lambda b, v: b["items"][0]["kit"].update(name=v), "items.0.kit.name"),
        (lambda b, v: b["items"][0]["kit"].update(kit_number=v), "items.0.kit.kit_number"),
    ],
)
async def test_an_order_refuses_it_at_any_depth_and_spawns_nothing(
    http_client, spoil, field, value
):
    body = await _order_body(http_client)
    spoil(body, value)
    resp = await http_client.post(
        "/orders", content=_json(body), headers={"content-type": "application/json"}
    )
    _the_refusal(resp, field)
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []


@pytest.mark.parametrize("value", UNSTORABLE)
async def test_a_new_catalog_item_on_an_order_line_refuses_it(http_client, value):
    body = await _order_body(http_client)
    body["items"] = [
        {
            "item_type": "tool",
            "quantity": 1,
            "unit_price_minor": 100,
            "currency_code": "AUD",
            "new_item": {"name": value, "category": "cutting"},
        }
    ]
    resp = await http_client.post(
        "/orders", content=_json(body), headers={"content-type": "application/json"}
    )
    _the_refusal(resp, "items.0.new_item.name")
    assert (await http_client.get("/tools")).json() == []


@pytest.mark.parametrize("value", UNSTORABLE)
async def test_an_order_edit_refuses_it_and_leaves_the_order(http_client, value):
    created = await http_client.post("/orders", json=await _order_body(http_client))
    assert created.status_code == 201, created.text
    resp = await http_client.patch(
        f"/orders/{created.json()['id']}",
        content=_json({"tracking_number": value}),
        headers={"content-type": "application/json"},
    )
    _the_refusal(resp, "tracking_number")
    assert (await http_client.get(f"/orders/{created.json()['id']}")).json()[
        "tracking_number"
    ] is None


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(
    "field",
    ["interface_language", "formatting_locale", "time_zone", "reference_currency"],
)
async def test_the_settings_refuse_it(http_client, field, value):
    before = (await http_client.get("/settings")).json()
    resp = await http_client.patch(
        "/settings", content=_json({field: value}), headers={"content-type": "application/json"}
    )
    _the_refusal(resp, field)
    assert (await http_client.get("/settings")).json() == before


@pytest.mark.parametrize("value", UNSTORABLE)
async def test_a_token_name_refuses_it(http_client, value):
    resp = await http_client.post(
        "/auth/tokens",
        content=_json({"name": value, "scopes": ["collection:read"]}),
        headers={"content-type": "application/json"},
    )
    _the_refusal(resp, "name")


async def test_the_refusal_can_echo_a_surrogate_in_a_field_the_model_never_declared(http_client):
    """The 422 echoes what was sent, and that is what used to fail: rendering the
    body as UTF-8, which is a 500 from the handler the 422 was on its way out of."""
    resp = await http_client.patch(
        "/kits/" + ZERO_ID,
        content='{"\\ud800": "\\ud800"}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422, f"{resp.status_code} {resp.text[:200]}"
    assert resp.json()["code"] == "request.validation"


async def test_an_ordinary_422_keeps_the_default_bytes(http_client):
    """`_EchoResponse` is the surrogate's path alone: non-ASCII still leaves as UTF-8."""
    resp = await http_client.post(
        "/kits",
        content='{"name": "ザク", "grade": "HG", "rating_typo": 1, "status": "ザク"}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert "ザク".encode() in resp.content


# --- the filters: text that reaches a query as an argument ---------------------------


@pytest.mark.parametrize("value", ["a%00b", "%00"])
@pytest.mark.parametrize(
    ("path", "param", "field"),
    [
        ("/kits", "grade", "grade"),
        ("/kits", "series", "series"),
        ("/tools", "category", "category"),
        ("/consumables", "category", "category"),
        ("/display-items", "category", "category"),
        ("/catalog/search", "q", "query"),
    ],
)
async def test_a_filter_refuses_it_with_the_service_s_code(http_client, path, param, field, value):
    resp = await http_client.get(f"{path}?{param}={value}")
    assert resp.status_code == 422, f"{resp.status_code} {resp.text[:200]}"
    body = resp.json()
    assert body["code"] == "request.text_unstorable", body
    assert body["params"] == {"field": field}, body


@pytest.mark.parametrize(
    ("path", "param"),
    [
        ("/kits", "grade"),
        ("/kits", "series"),
        ("/tools", "category"),
        ("/consumables", "category"),
        ("/display-items", "category"),
        ("/catalog/search", "q"),
    ],
)
async def test_a_filter_on_ordinary_text_still_answers(http_client, path, param):
    resp = await http_client.get(f"{path}?{param}=nothing%25by_this%0Aname")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# --- MCP: the same refusals through the same services --------------------------------


async def _refused(tool: str, arguments: dict) -> str:
    async with Client(mcp) as client:
        # `MCPError` for a schema built inside the tool, as `create_order` builds its
        # own: the SDK's invalid-params answer, as for any other value that fails there.
        with pytest.raises((ToolError, MCPError)) as refused:
            await client.call_tool(tool, arguments)
    text = str(refused.value)
    assert "asyncpg" not in text and "sqlalchemy" not in text, text
    return text


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_catalog", lambda v: {"query": v}),
        ("list_kits", lambda v: {"grade": v}),
        ("list_kits", lambda v: {"series": v}),
        ("list_catalog_items", lambda v: {"item_type": "tool", "category": v}),
        ("adjust_stock", lambda v: {"catalog_id": ZERO_ID, "delta": 1, "reason": v}),
    ],
)
async def test_an_mcp_argument_is_refused_by_the_service(tool, arguments, value):
    assert "can't store" in await _refused(tool, arguments(value))


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("create_kit", lambda v: {"kit": {"name": v, "grade": "HG"}}),
        ("create_kit", lambda v: {"kit": {"name": "n", "grade": "HG", "build_notes": v}}),
        ("create_retailer", lambda v: {"retailer": {"name": v}}),
        ("create_catalog_tool", lambda v: {"tool": {"name": v, "category": "c"}}),
        ("create_catalog_consumable", lambda v: {"consumable": {"name": v, "category": "c"}}),
        ("create_catalog_upgrade", lambda v: {"upgrade": {"name": v, "manufacturer": "m"}}),
        ("create_catalog_display", lambda v: {"display_item": {"name": v, "category": "c"}}),
        ("update_kit", lambda v: {"kit_id": ZERO_ID, "changes": {"build_notes": v}}),
        ("update_retailer", lambda v: {"retailer_id": ZERO_ID, "changes": {"notes": v}}),
    ],
)
async def test_an_mcp_body_is_refused_by_the_shared_schema(http_client, tool, arguments, value):
    await _refused(tool, arguments(value))
    assert (await http_client.get("/kits")).json() == []
    assert (await http_client.get("/retailers")).json() == []
    assert (await http_client.get("/tools")).json() == []


ORDER_LINE = {
    "item_type": "kit",
    "quantity": 1,
    "unit_price_minor": 100,
    "currency_code": "AUD",
    "kit": {"name": "Zaku", "grade": "HG"},
}


@pytest.mark.parametrize("value", UNSTORABLE)
@pytest.mark.parametrize(
    "field", ["retailer", "order_number", "delivery_service", "tracking_number", "tracking_url"]
)
async def test_create_order_s_flat_arguments_refuse_it(http_client, field, value):
    """The tool's only flat text: `retailer` is looked up before any schema runs, and
    the rest are handed to `OrderCreate` inside the tool. The shop must not survive a
    refused order either, the transaction being one."""
    arguments = {
        "order_date": "2026-01-01",
        "retailer": "Shop",
        "currency_code": "AUD",
        "items": [ORDER_LINE],
    }
    await _refused("create_order", {**arguments, field: value})
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []
    assert (await http_client.get("/retailers")).json() == []


async def test_an_mcp_filter_on_ordinary_text_still_answers():
    async with Client(mcp) as client:
        assert (await client.call_tool("list_kits", {"grade": "ザク\t\x01"})).data == []


# --- the importer --------------------------------------------------------------------


def _one_diagnostic(plan: dict, table: str, field: str) -> dict:
    [tab] = [t for t in plan["tables"] if t["table"] == table]
    [row] = tab["rows"]
    assert row["action"] == "error", row
    return next(d for d in row["errors"] if d["params"].get("field") == field)


@pytest.mark.parametrize("value", NUL_ONLY)
@pytest.mark.parametrize("field", ["name", "url", "notes"])
@pytest.mark.parametrize("mode", ["merge", "add_only", "replace_all"])
async def test_a_preview_refuses_the_row_a_create(http_client, field, mode, value):
    """The preview used to plan this row as a create, and the apply then 500'd on it:
    a plan that says the file is fine is the second half of the defect."""
    row = {"id": "", "name": "Shop", "url": "", "notes": "", field: value}
    content = make_csv(["id", "name", "url", "notes"], [row])
    plan = await preview(http_client, content, filename="retailers.csv", mode=mode)
    diagnostic = _one_diagnostic(plan, "retailers", field)
    assert diagnostic["code"] == "import.cell_invalid"

    resp = await apply(http_client, content, filename="retailers.csv", mode=mode, confirm="REPLACE")
    assert resp.status_code == 409, f"{resp.status_code} {resp.text[:200]}"
    assert resp.json()["code"] == "import.blocked"
    assert (await http_client.get("/retailers")).json() == []


@pytest.mark.parametrize("value", NUL_ONLY)
async def test_a_preview_refuses_the_row_an_update_and_the_row_stays(http_client, value):
    """A row an id matches: `changes` would be non-empty, and this is the state in
    which the plan names a before and an after."""
    created = (await http_client.post("/retailers", json={"name": "Shop", "notes": "kept"})).json()
    content = make_csv(
        ["id", "name", "notes"], [{"id": created["id"], "name": "Shop", "notes": value}]
    )
    plan = await preview(http_client, content, filename="retailers.csv")
    assert _one_diagnostic(plan, "retailers", "notes")["code"] == "import.cell_invalid"
    resp = await apply(http_client, content, filename="retailers.csv")
    assert resp.status_code == 409, f"{resp.status_code} {resp.text[:200]}"
    [row] = (await http_client.get("/retailers")).json()
    assert row["notes"] == "kept"


async def test_an_unreadable_required_cell_says_so_once(http_client):
    """It was unreadable, not missing: "name is required" beside it would be untrue."""
    content = make_csv(["id", "name"], [{"id": "", "name": "a\x00b"}])
    plan = await preview(http_client, content, filename="retailers.csv")
    [row] = plan["tables"][0]["rows"]
    assert [d["code"] for d in row["errors"]] == ["import.cell_invalid"]
    assert row["errors"][0]["params"] == {"field": "name"}


async def test_an_archive_member_refuses_it_too(http_client):
    content = zip_members(
        {"retailers.csv": make_csv(["id", "name"], [{"id": "", "name": "a\x00b"}])}
    )
    plan = await preview(http_client, content)
    assert _one_diagnostic(plan, "retailers", "name")["code"] == "import.cell_invalid"


async def test_a_starter_sheet_refuses_it(http_client):
    content = make_csv(
        starter_sheet.STARTER_SHEET_HEADER,
        [{"kit_name": "a\x00b", "grade": "HG"}],
    )
    resp = await http_client.post(
        "/import/preview",
        files={"file": ("starter-sheet.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:200]}"
    codes = [
        d["code"] for table in resp.json()["tables"] for row in table["rows"] for d in row["errors"]
    ]
    assert codes, resp.text
    assert set(codes) == {"import.cell_invalid"}


@pytest.mark.parametrize("value", ORDINARY)
async def test_ordinary_text_still_imports(http_client, value):
    content = make_csv(["id", "name", "notes"], [{"id": "", "name": "Shop", "notes": value}])
    resp = await apply(http_client, content, filename="retailers.csv")
    assert resp.status_code == 200, resp.text
    [row] = (await http_client.get("/retailers")).json()
    assert row["notes"] == value.strip()


def test_every_text_column_on_every_sheet_goes_through_the_one_parser():
    """A text column with a parser of its own would be a door this suite never tried.
    What is not `parse_text` must refuse by its own grammar: a number, a date, an id, a
    currency, an enum. The count is written out so an empty walk cannot pass."""
    columns = [column for sheet in spec.TABLE_SPECS for column in sheet.columns]
    columns += list(starter_sheet.STARTER_SHEET_COLUMNS)
    text_columns = [column for column in columns if column.parse is parse_text]
    assert len(text_columns) >= 30
    for column in columns:
        try:
            parsed = column.parse("a\x00b")
        except (ArithmeticError, ValueError):
            continue
        raise AssertionError(f"{column.name} parsed a NUL into {parsed!r}")


# --- sign-in: a credential is hashed or compared, and never stored as written --------


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        ("/auth/login", {"password": "a\ud800b"}, "password"),
        ("/auth/setup", {"token": "t", "password": "a\ud800b"}, "password"),
        ("/auth/setup", {"token": "a\ud800b", "password": "p"}, "token"),
    ],
)
async def test_a_credential_with_no_utf8_form_is_a_422(http_client, path, body, field):
    """Their fields are constrained, so pydantic's core refuses this itself. What was
    the 500 is the handler, echoing the value in a body it could not encode."""
    resp = await http_client.post(
        path, content=_json(body), headers={"content-type": "application/json"}
    )
    _the_refusal(resp, field)


@pytest.mark.parametrize(
    "path_and_body",
    [
        ("/auth/login", {"password": "a\x00b"}),
        ("/auth/setup", {"token": "a\x00b", "password": "p"}),
    ],
)
async def test_a_nul_in_a_credential_stays_a_wrong_answer(http_client, path_and_body):
    """Never stored as written, so never this defect. A 422 here would also lock out
    an owner whose password holds one, which is why these three models stay off the base."""
    path, body = path_and_body
    resp = await http_client.post(path, json=body)
    assert resp.status_code == 403, f"{resp.status_code} {resp.text[:200]}"


# --- MCP OAuth: the state store's keys are the client's to name ----------------------


async def test_oauth_lookups_by_a_nul_key_are_the_protocol_s_own_refusals():
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_live, client):
        _verifier, challenge = _pkce()
        resp = await authorize(client, "a\x00b", challenge=challenge)
        assert resp.status_code == 400, f"{resp.status_code} {resp.text[:200]}"

        for grant in (
            {"grant_type": "authorization_code", "code": "c", "code_verifier": "v"},
            {"grant_type": "refresh_token", "refresh_token": "r"},
        ):
            resp = await client.post("/mcp/token", data={**grant, "client_id": "a\x00b"})
            assert resp.status_code == 401, f"{resp.status_code} {resp.text[:200]}"
            assert resp.json()["error"] == "invalid_client"

        resp = await client.post("/mcp/revoke", data={"client_id": "a\x00b", "token": "t"})
        assert resp.status_code == 401, f"{resp.status_code} {resp.text[:200]}"
        assert resp.json()["error"] == "invalid_client"
        assert await _state_rows() == []


@pytest.mark.parametrize(
    "path",
    [
        "/mcp/consent?txn_id=a%00b",
        "/mcp/auth/callback?state=a%00b&code=c",
        "/mcp/authorize?client_id=https%3A%2F%2Fclient.test%2Fa%00b&response_type=code"
        "&redirect_uri=http%3A%2F%2F127.0.0.1%3A1%2Fcb&code_challenge=x"
        "&code_challenge_method=S256",
    ],
    ids=["consent's transaction", "the provider's return", "a document URL as client id"],
)
async def test_the_other_keys_a_browser_names_are_never_a_500(path):
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_live, client):
        resp = await client.get(path, follow_redirects=False)
        assert resp.status_code < 500, f"{resp.status_code} {resp.text[:200]}"
        assert await _state_rows() == []


async def test_a_registered_client_s_nul_code_is_an_invalid_grant():
    """A real client, so the lookup that reaches the store is the code's, not the
    client's: the row key under test is one the request named."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_live, client):
        registered = await client.post(
            "/mcp/register",
            json={
                "redirect_uris": [NATIVE_CB],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert registered.status_code == 201, registered.text
        resp = await client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered.json()["client_id"],
                "code": "a\x00b",
                "code_verifier": "v" * 43,
                "redirect_uri": NATIVE_CB,
            },
        )
        assert resp.status_code == 401, f"{resp.status_code} {resp.text[:200]}"
        assert resp.json()["error"] == "invalid_grant"


# --- nothing new gets past the sweep -------------------------------------------------


def _models_in(annotation) -> set[type[BaseModel]]:
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        found = {annotation}
        for field in annotation.model_fields.values():
            found |= _models_in(field.annotation)
        return found
    found = set()
    for arg in typing.get_args(annotation):
        found |= _models_in(arg)
    return found


def _dependants():
    """Each REST route's parameters, as FastAPI reads them, dependencies included."""

    def flatten(dependant):
        yield dependant
        for child in dependant.dependencies:
            yield from flatten(child)

    for route in iter_effective_routes(app):
        for dependant in flatten(get_dependant(path=route.path, call=route.endpoint)):
            yield route, dependant


def _request_models() -> set[type[BaseModel]]:
    found: set[type[BaseModel]] = set()
    for _route, dependant in _dependants():
        for param in dependant.body_params:
            found |= _models_in(param.field_info.annotation)
    return found


async def _mcp_tools() -> dict:
    return {tool.name: tool for tool in await mcp.list_tools()}


def _is_text(annotation) -> bool:
    if annotation is str:
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return any(_is_text(arg) for arg in typing.get_args(annotation))
    return False


#: Every body type the route graph has today, spelled out so the walk below cannot
#: pass by finding nothing.
SOME_REQUEST_MODELS = {"KitCreate", "OrderCreate", "OrderItemCreate", "TokenCreate", "LoginRequest"}


def test_every_request_body_comes_from_the_base():
    """Rule 9's shape: what a new route brings is a deliberate act. A new model on
    `BaseModel` would hold text the wildcard validator never sees. The three that stay
    there carry credentials and no text bound for a column: see the sign-in tests."""
    models = _request_models()
    assert SOME_REQUEST_MODELS <= {model.__name__ for model in models}
    strangers = {model.__name__ for model in models if not issubclass(model, RequestModel)}
    assert strangers == {"SetupRequest", "LoginRequest", "OidcStartRequest"}


def test_every_text_query_parameter_is_one_this_suite_drives():
    """A filter is refused by its service, not by a base class, so a new one needs an
    answer. `state`/`code`/`error` are the OIDC callback's: hashed or matched against
    fixed words, never handed to a query as written (the callback's own test covers
    them). `sort` the service refuses by vocabulary; the three Form fields are an
    import's own, compared and never stored."""
    found = set()
    for route, dependant in _dependants():
        for param in (*dependant.query_params, *dependant.body_params):
            if _is_text(param.field_info.annotation):
                found.add((route.path, param.name))
    assert found == {
        ("/kits", "grade"),
        ("/kits", "series"),
        ("/tools", "category"),
        ("/consumables", "category"),
        ("/display-items", "category"),
        ("/catalog/search", "q"),
        ("/auth/oidc/callback", "state"),
        ("/auth/oidc/callback", "code"),
        ("/auth/oidc/callback", "error"),
        ("/import/apply", "plan_hash"),
        ("/import/apply", "confirm"),
    }


async def test_every_flat_text_argument_of_an_mcp_tool_is_accounted_for():
    """The MCP side of the same question, and the place REST's base class does not
    reach: a flat argument goes to a service or into a schema inside the tool."""
    accounted_for = {
        # Refused by the service, driven above.
        ("search_catalog", "query"),
        ("list_kits", "grade"),
        ("list_kits", "series"),
        ("list_catalog_items", "category"),
        ("adjust_stock", "reason"),
        # Reach a schema inside the tool, driven above.
        ("create_order", "retailer"),
        ("create_order", "order_number"),
        ("create_order", "delivery_service"),
        ("create_order", "tracking_number"),
        ("create_order", "tracking_url"),
        # A closed grammar the tool or the service parses before any query.
        ("list_kits", "status"),
        ("list_kits", "sort"),
        ("list_orders", "sort"),
        ("update_kit_status", "kit_id"),
        ("update_kit_status", "status"),
        ("get_kit", "kit_id"),
        ("update_kit", "kit_id"),
        ("list_catalog_items", "item_type"),
        ("list_catalog_categories", "item_type"),
        ("update_retailer", "retailer_id"),
        ("create_order", "order_date"),
        ("create_order", "retailer_id"),
        ("create_order", "currency_code"),
        ("create_order", "received_at"),
        ("create_order", "shipped_at"),
        ("get_order", "order_id"),
        ("update_order", "order_id"),
        ("mark_order_received", "order_id"),
        ("mark_order_received", "received_at"),
        ("mark_order_shipped", "order_id"),
        ("mark_order_shipped", "shipped_at"),
        ("adjust_stock", "catalog_id"),
        ("update_catalog_tool", "tool_id"),
        ("update_catalog_consumable", "consumable_id"),
        ("update_catalog_upgrade", "upgrade_id"),
        ("update_catalog_display", "display_item_id"),
        ("apply_upgrade", "upgrade_id"),
        ("apply_upgrade", "kit_id"),
        ("withdraw_upgrade_application", "application_id"),
    }
    found = set()
    for name, tool in (await _mcp_tools()).items():
        signature = inspect.signature(tool.fn)
        hints = typing.get_type_hints(tool.fn)
        for parameter in signature.parameters:
            if _is_text(hints.get(parameter)):
                found.add((name, parameter))
    assert found == accounted_for


async def test_every_mcp_body_type_comes_from_the_base():
    models: set[type[BaseModel]] = set()
    for tool in (await _mcp_tools()).values():
        for hint in typing.get_type_hints(tool.fn).values():
            models |= _models_in(hint)
    response_only = {name for name in ("ToolRead",) if name in {m.__name__ for m in models}}
    assert not response_only
    assert {"_KitPatch", "_KitInput", "ToolCreate", "OrderUpdate"} <= {m.__name__ for m in models}
    assert {m.__name__ for m in models if not issubclass(m, RequestModel)} == set()

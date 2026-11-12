"""#247 — a kit list sorted by a build date is sorted by the date the row shows.

Home's Recently completed strip printed each kit's completion date and asked the
server for `sort=recent`, the status clock — so a kit finished in July and recorded
in September sat above one finished yesterday. The bench was the same shape one
status over. The fix is new sorts (`started`, `completed`, and `newest` for the Kits
page's default), not a change to `recent`, which Home's Backlog strip and an agent
asking "what moved lately" still read.

The cases are shared with the browser: `frontend/src/lib/__fixtures__/
kit-sort-cases.json` holds the kits, the date each surface prints for them, and the
order each sort promises. This suite seeds the kits as rows and asks the API; the
frontend suite checks the printed dates and that every promised order is sorted by
them. A server order and a printed date that drift apart fail one side or the other.

The rows are inserted directly, with their clocks set, because every path through
the API stamps `created_at` and the status clock with *now* — the value space here
(a completion date earlier than, later than and equal to the status clock; two
builds backfilled to one midnight; a kit that has none) is not reachable by moving
kits in real time.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastmcp import Client

from app.db import session_scope
from app.mcp import mcp
from app.models import Kit, KitStatus

_FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/__fixtures__/kit-sort-cases.json"
    ).read_text(encoding="utf-8")
)
_ORDERS = _FIXTURE["orders"]


def _instant(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _seed() -> None:
    async with session_scope() as session:
        for case in _FIXTURE["kits"]:
            session.add(
                Kit(
                    name=case["name"],
                    grade="HG",
                    status=KitStatus(case["status"]),
                    created_at=_instant(case["created_at"]),
                    status_updated_at=_instant(case["status_updated_at"]),
                    build_started_at=_instant(case["build_started_at"]),
                    build_completed_at=_instant(case["build_completed_at"]),
                )
            )
        await session.commit()


def _case_id(case: dict) -> str:
    """`completed-complete` for `?sort=completed&status=complete` — a word pytest's
    `-k` can select (it refuses `=` and `&`), which the mutation harness does."""
    params = case["params"]
    return "-".join([params["sort"], *([params["status"]] if "status" in params else [])])


def _names(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [kit["name"] for kit in resp.json()]


def test_the_fixture_drives_every_new_sort():
    """Vacuity guard: the matrix below is read from the fixture, so an emptied or
    renamed fixture must fail here rather than parametrize into nothing."""
    assert len(_FIXTURE["kits"]) == 11
    sorts = {o["params"]["sort"] for o in _ORDERS}
    assert {"newest", "started", "completed", "recent"} <= sorts


@pytest.mark.parametrize("case", _ORDERS, ids=_case_id)
async def test_rest_lists_kits_in_the_promised_order(client, case):
    await _seed()
    assert _names(await client.get("/kits", params=case["params"])) == case["names"]


@pytest.mark.parametrize(
    "case",
    [o for o in _ORDERS if o["params"].get("status") in ("complete", "building")],
    ids=_case_id,
)
async def test_a_strip_is_the_first_six_of_its_list(client, case):
    """Home asks for `limit=6` of the same sort; the strip is the list's head."""
    await _seed()
    params = {**case["params"], "limit": 6}
    assert _names(await client.get("/kits", params=params)) == case["names"][:6]


@pytest.mark.parametrize("case", _ORDERS, ids=_case_id)
async def test_mcp_lists_kits_in_the_same_order(client, case):
    """One vocabulary for REST and MCP (rule 1): the tool passes its string to
    the same service, so an agent asking what it finished lately gets Home's
    order."""
    await _seed()
    async with Client(mcp) as mcp_client:
        kits = (await mcp_client.call_tool("list_kits", case["params"])).data
    assert [kit["name"] for kit in kits] == case["names"]

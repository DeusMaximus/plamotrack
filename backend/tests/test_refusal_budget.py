"""The refusal budget on the pre-routing guard's audit recorder, and automatic
audit retention (#210; #221 item 3; §5.6 log and audit hygiene).

A hostile-Origin flood on a path nginx does not rate-limit used to cost the
database one committed row per request, without bound. Now each address earns
`REFUSALS_PER_ADDRESS` rows per window and the instance `REFUSALS_PER_WINDOW`;
what a window suppressed is written as one summary row with the next recorded
refusal. The refusal itself is answered whatever the budget says.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app import error_codes
from app.auth.budget import (
    REFUSAL_WINDOW,
    REFUSALS_PER_ADDRESS,
    REFUSALS_PER_WINDOW,
    RefusalBudget,
)
from app.config import Settings
from app.db import get_sessionmaker
from app.main import REFUSAL_BUDGET_ATTR, app
from app.models import AuditEvent
from app.services import audit

pytestmark = pytest.mark.anyio

HOSTILE = {"Origin": "https://evil.example", "Content-Type": "application/json"}


def _client_from(address: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(address, 40000), raise_app_exceptions=False),
        base_url="http://test",
    )


async def _rows(*event_types: str) -> list[AuditEvent]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.event_type.in_(event_types))
            .order_by(AuditEvent.occurred_at)
        )
        return list(rows.scalars().all())


@pytest.fixture
def clock():
    now = {"t": 1000.0}
    setattr(app.state, REFUSAL_BUDGET_ATTR, RefusalBudget(clock=lambda: now["t"]))
    yield now
    setattr(app.state, REFUSAL_BUDGET_ATTR, RefusalBudget())


# --- the budget itself ------------------------------------------------------------


def test_each_address_and_the_instance_have_a_bound_and_the_window_rolls_over():
    now = {"t": 0.0}
    budget = RefusalBudget(clock=lambda: now["t"])
    admitted = [budget.admit("10.0.0.1")[0] for _ in range(REFUSALS_PER_ADDRESS + 5)]
    assert admitted.count(True) == REFUSALS_PER_ADDRESS
    assert admitted[REFUSALS_PER_ADDRESS:] == [False] * 5
    # Another address has its own allowance until the instance's bound is met.
    others = [budget.admit(f"10.0.1.{i}")[0] for i in range(REFUSALS_PER_WINDOW)]
    assert others.count(True) == REFUSALS_PER_WINDOW - REFUSALS_PER_ADDRESS
    assert budget.suppressed == 5 + REFUSALS_PER_ADDRESS
    # The per-address map cannot outgrow the instance bound: past it nothing is inserted.
    assert len(budget._per_address) <= REFUSALS_PER_WINDOW
    # The next window's first admitted refusal carries the count, once.
    now["t"] += REFUSAL_WINDOW
    assert budget.admit("10.0.0.1") == (True, 5 + REFUSALS_PER_ADDRESS)
    assert budget.admit("10.0.0.1") == (True, 0)
    assert budget.suppressed == 0


# --- through the guard ------------------------------------------------------------


async def test_a_hostile_origin_flood_writes_the_bound_then_one_summary_row(clock):
    """The rule of #210: a measured bound on synchronous audit writes, with the
    first refusals attributable and the rest counted."""
    flood = REFUSALS_PER_ADDRESS * 3
    async with _client_from("203.0.113.9") as attacker:
        for _ in range(flood):
            refused = await attacker.post("/retailers", content=b"{}", headers=HOSTILE)
            assert refused.status_code == 403
            assert refused.json()["code"] == error_codes.INGRESS_ORIGIN_NOT_ALLOWED
    rows = await _rows(audit.ORIGIN_REJECTED, audit.REFUSALS_SUPPRESSED)
    assert [row.event_type for row in rows] == [audit.ORIGIN_REJECTED] * REFUSALS_PER_ADDRESS
    assert {row.client_address for row in rows} == {"203.0.113.9"}
    assert {row.target for row in rows} == {"/retailers"}
    # Another caller in the same window is not charged for the flood.
    async with _client_from("198.51.100.2") as other:
        assert (await other.post("/retailers", content=b"{}", headers=HOSTILE)).status_code == 403
    rows = await _rows(audit.ORIGIN_REJECTED)
    assert rows[-1].client_address == "198.51.100.2"
    # The next window: the first recorded refusal carries the suppressed count.
    clock["t"] += REFUSAL_WINDOW
    async with _client_from("203.0.113.9") as attacker:
        again = await attacker.post("/retailers", content=b"{}", headers=HOSTILE)
        assert again.status_code == 403
    rows = await _rows(audit.ORIGIN_REJECTED, audit.REFUSALS_SUPPRESSED)
    summaries = [row for row in rows if row.event_type == audit.REFUSALS_SUPPRESSED]
    assert len(summaries) == 1
    assert summaries[0].detail == (
        f"suppressed={flood - REFUSALS_PER_ADDRESS} window_s={int(REFUSAL_WINDOW)}"
    )
    assert summaries[0].principal_kind == "anon"
    assert summaries[0].client_address is None
    assert summaries[0].target is None
    assert rows[-1].event_type == audit.ORIGIN_REJECTED
    assert len([row for row in rows if row.event_type == audit.ORIGIN_REJECTED]) == (
        REFUSALS_PER_ADDRESS + 2
    )


async def test_the_budget_never_changes_the_refusal_itself(clock):
    """Suppressed or recorded, a hostile Origin is 403 with the envelope."""
    async with _client_from("203.0.113.10") as attacker:
        statuses = {
            (await attacker.post("/retailers", content=b"{}", headers=HOSTILE)).status_code
            for _ in range(REFUSALS_PER_ADDRESS + 3)
        }
    assert statuses == {403}


# --- automatic retention ----------------------------------------------------------


async def test_prune_retained_deletes_rows_older_than_the_configured_days():
    old = AuditEvent(event_type="test.old", occurred_at=datetime.now(UTC) - timedelta(days=31))
    kept = AuditEvent(event_type="test.kept", occurred_at=datetime.now(UTC) - timedelta(days=29))
    async with get_sessionmaker()() as session:
        session.add_all((old, kept))
        await session.commit()
    assert await audit.prune_retained(30) == 1
    rows = await _rows("test.old", "test.kept", audit.AUDIT_PRUNED)
    assert [row.event_type for row in rows] == ["test.kept", audit.AUDIT_PRUNED]
    assert rows[-1].detail.startswith("deleted=1 before=")


async def test_the_retention_loop_survives_a_failed_pass(monkeypatch):
    calls: list[int] = []

    async def flaky(days: int) -> int:
        calls.append(days)
        if len(calls) == 1:
            raise RuntimeError("database away")
        return 0

    monkeypatch.setattr(audit, "prune_retained", flaky)
    task = asyncio.create_task(audit.retention_loop(7, interval=0.01))
    for _ in range(200):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls[:2] == [7, 7]


@pytest.mark.parametrize("value", [0, -1, "many"])
def test_audit_retention_days_refuses_non_positive_values(value):
    with pytest.raises(ValueError):
        Settings(audit_retention_days=value)


def test_audit_retention_days_is_optional_and_positive():
    assert Settings().audit_retention_days is None
    assert Settings(audit_retention_days="180").audit_retention_days == 180

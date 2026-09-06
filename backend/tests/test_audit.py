"""Security audit retention and completeness (M6-8, #193; §5.8 T10)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import AuditEvent
from app.services import audit

pytestmark = pytest.mark.anyio


async def test_prune_deletes_only_rows_strictly_older_than_the_cutoff():
    cutoff = datetime(2026, 3, 1, tzinfo=UTC)
    old = AuditEvent(event_type="test.old", occurred_at=cutoff - timedelta(microseconds=1))
    boundary = AuditEvent(event_type="test.boundary", occurred_at=cutoff)
    recent = AuditEvent(event_type="test.recent", occurred_at=cutoff + timedelta(days=1))
    async with get_sessionmaker()() as session:
        session.add_all((old, boundary, recent))
        await session.commit()

    async with get_sessionmaker()() as session:
        assert await audit.prune_events(session, before=cutoff) == 1

    async with get_sessionmaker()() as session:
        rows = (
            (await session.execute(select(AuditEvent).order_by(AuditEvent.occurred_at)))
            .scalars()
            .all()
        )

    assert [row.event_type for row in rows] == [
        "test.boundary",
        "test.recent",
        audit.AUDIT_PRUNED,
    ]
    prune = rows[-1]
    assert prune.principal_kind == "internal"
    assert prune.principal_subject is None
    assert prune.client_address == "host"
    assert prune.target == "maintenance prune-audit"
    assert prune.detail == f"deleted=1 before={cutoff.isoformat()}"


async def test_an_empty_prune_is_still_audited():
    cutoff = datetime.now(UTC) - timedelta(days=180)
    async with get_sessionmaker()() as session:
        assert await audit.prune_events(session, before=cutoff) == 0
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == audit.AUDIT_PRUNED
    assert rows[0].detail.startswith("deleted=0 before=")

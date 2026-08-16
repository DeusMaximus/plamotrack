"""The read side of the concurrency story: one stable snapshot for a multi-statement read.

`services/write_gate.py` serializes writers, and says explicitly that reads never
take it — preview and every list and detail path stay concurrent with everything.
That is the right trade for a read whose answer is a momentary view: it is stale
the instant it is serialized either way, and making a human's export block their
agent's writes (or the reverse) would buy nothing.

Export is the read where that stops being true. It issues one statement per table
and hands back a *file* — an archive that gets kept as a backup and fed back
through the importer. Under the default `READ COMMITTED` each of those statements
sees a fresh snapshot, so a write committing partway through lands in the archive
on one side of the seam and not the other: a kit whose `order_item_id` names an
order line that no CSV in the same zip contains. Nothing in the database is
damaged — the artifact is, and it is the artifact that outlives the request.

`REPEATABLE READ` fixes that at the transaction level rather than per query: every
statement in the transaction reads the same snapshot, taken at the *first* one.
No lock is involved, so writers are never delayed by an export and an export is
never delayed by a writer — it simply exports the collection as it stood when it
started.

`READ ONLY` is not decoration. It is the half that keeps this honest as the code
changes: Postgres refuses any write inside the transaction, so a future edit that
adds a write to an export path fails loudly instead of quietly writing from under
a snapshot.

Both are transaction characteristics, applied to the `BEGIN` itself by the asyncpg
driver and reset when the connection returns to the pool — so, like the write
gate, there is nothing to undo by hand and no way to strand a pooled connection in
read-only.

**Where this must not go.** It covers the whole transaction, not one call, so it
belongs on a read that is the entire unit of work — the export entry points, and
whatever read-only artifact comes after them. Putting it on a helper that a write
path also calls turns every one of those writes into a
`ReadOnlySQLTransactionError`: `plan_import` is the live example, shared by
`preview_import` (a read) and `apply_import` (the write that re-plans under the
gate before writing), and a snapshot taken inside it would break every import in
the application.
"""

from sqlalchemy.ext.asyncio import AsyncSession

#: `postgresql_readonly` is the dialect's spelling of `BEGIN ... READ ONLY`;
#: `isolation_level` alone would give a snapshot that still accepts writes.
_READ_SNAPSHOT = {"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}


async def begin_read_snapshot(session: AsyncSession) -> None:
    """Pin this transaction to one snapshot of the collection, and forbid writes.

    Call it **before the transaction's first statement**. Both characteristics are
    set on the connection as it begins the transaction, and the snapshot itself is
    taken when the first statement runs — so a read issued beforehand both escapes
    the snapshot and leaves SQLAlchemy nothing to configure, in which case it warns
    (`Connection is already established for the given bind`) rather than raising.
    Services that need a stable read call this first thing, on a per-request
    session that has done nothing else.

    Released with the transaction, at COMMIT or ROLLBACK.
    """
    await session.connection(execution_options=_READ_SNAPSHOT)

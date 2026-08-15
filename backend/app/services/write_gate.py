"""The collection-wide write gate.

plamotrack has three concurrent writer types by design — the browser, REST
clients, and MCP agents (rule 7) — and every one of them mutates a single
owner's single collection. Individual row locks (`with_for_update`) serialize
writers that touch *the same row*, and that is most of what the order and
catalog services need. What they cannot express is the shape the importer has:
read a great deal of state, decide what to do from it, then write across many
tables — where the decision is invalidated by a concurrent write to a row the
plan never named.

`apply_import` is the clearest case. It re-plans, compares the resulting
`plan_hash` against the one the user approved, then writes. A mutation landing
between the re-plan and the writes is invisible to both the hash and any
per-row lock taken afterwards, and the failure modes are not subtle: a parent
order deleted in that window turns a create into a foreign-key 500, a
`replace_all` `TRUNCATE` destroys rows the approved preview never listed as
deletions, and the kit-arrival side effect writes a status derived from a
snapshot someone else has already moved on from.

Enumerating those dependencies one at a time does not converge — each fix
covers the path in front of it and leaves the next one open, which is the
review history of #79 in one sentence. This gate is the invariant instead:

    every mutation takes the gate before it reads the state it will decide from.

A writer holding it runs to completion — read, decide, write, commit — with no
other writer interleaving. A second writer waits, then works from what the
first one committed. Nothing else needs to reason about which specific rows its
decision depended on.

**Scope is deliberately the whole collection**, not a row or a table. This is a
single-owner application (§3): the realistic concurrency is one person's
browser racing their own agent, or two tabs, and serializing those costs
nothing anybody will notice. A finer-grained gate would buy throughput this
application will never need, in exchange for exactly the per-path reasoning
that has already proven not to hold.

**Reads never take it.** Import preview, every list and detail endpoint, and
every MCP read tool run unlocked and stay concurrent with anything. Only the
mutating service functions gate, and the cost lands only where two writes
genuinely overlap.

Transaction-scoped (`pg_advisory_xact_lock`), so Postgres releases it at
COMMIT or ROLLBACK — including a rollback from an unhandled error. There is no
release call to forget, and no way for a crashed request to strand the gate.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Arbitrary but stable. Any int64 works as long as nothing else in this
#: database claims the same one; this spells "plamo" in hex so it is
#: recognisable in `pg_locks` when someone is working out what is waiting.
_COLLECTION_WRITE_LOCK = 0x706C616D6F


async def acquire_write_gate(session: AsyncSession) -> None:
    """Serialize this transaction against every other writer on the collection.

    Call it **before reading the state the write depends on**, not just before
    the write itself — a decision made from an unlocked read is already stale by
    the time the gate is taken, which is the whole failure this exists to stop.

    Blocks until the gate is free. It is released automatically when the
    transaction ends, so callers never release it and an error path cannot leak
    it. Re-entrant within one transaction: Postgres counts advisory locks per
    session, so a gated service calling another gated service is fine.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _COLLECTION_WRITE_LOCK}
    )

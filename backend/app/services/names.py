"""One rule for what a retailer's or catalog item's name *is* (#107, rule 3).

The CSV importer treats the case-insensitive name as the **natural key** for
retailers and the three catalog tables (`spec._name_key`, design notes §12.4): an
id-less `orders.csv` row names its shop, and two stored retailers that fold to the
same key make that row unimportable. `get_or_create_retailer` already applied the
rule on the way in (#49). The create and rename paths applied *no* rule — `POST
/retailers {"name": "hlj"}` with `HLJ` present was a second row, on REST, on MCP and
through an order line's `new_item` alike — so the database accepted a state the
importer declares invalid.

This module is the predicate, written once, and the two things every writer of a
name does with it:

* `clean_name` — the name as stored: surrounding whitespace removed, and a name that
  is *only* whitespace refused. `min_length=1` on the request schemas lets `" "`
  through, and a stored `""` has no natural key at all.
* `require_unique_name` — a `ConflictError` (409) when another row of the same table
  already folds to the same key. The caller passes its own id on a rename so a row
  may keep, or re-case, its own name.

The comparison is `lower(btrim(name))` on both sides, **in Postgres**. Both sides
in one runtime because Postgres `lower()` and Python `str.lower()` disagree on
Turkish `İ`, and a predicate that folds one side each way misses the exact stored
spelling (#49). `btrim` on the stored side because rows written before this module
existed can carry surrounding spaces — the browser forms never trimmed and neither
did the create routes — and the importer's `strip().lower()` reads `" HLJ "` and
`HLJ` as one shop. It trims spaces only; the importer's Python `strip()` trims every
Unicode whitespace, which is wider, and a legacy name padded with a tab is not a
case this guards.

Equality, never a pattern — `%`, `_` and a backslash in a name are characters (#49).
Per-table: a tool and a consumable may share a name; the importer matches "within
that table" and so does this.

**Not the importer.** `services/portability/importing.py` applies the same key its
own way: an id-less row naming a stored row *updates* it, and two id-less rows in
one upload naming the same thing are an error row. What it does not refuse is an
archive carrying two *id-bearing* rows under one key — by design, so an instance that
already holds such a pair can round-trip (§12.4). Whether a fresh id-bearing pair
should be told apart from that is filed as the sibling, for once #86 has landed in
that file.
"""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, InvalidInputError
from app.models import Consumable, Retailer, Tool, Upgrade

type NamedRow = Retailer | Tool | Consumable | Upgrade

#: What the refusal calls the row — the API's own vocabulary, not the table name.
_NOUN: dict[type, str] = {
    Retailer: "retailer",
    Tool: "tool",
    Consumable: "consumable",
    Upgrade: "upgrade",
}


def clean_name(name: str) -> str:
    """The name as it is stored. Trims; refuses blank."""
    cleaned = name.strip()
    if not cleaned:
        raise InvalidInputError("name cannot be blank")
    return cleaned


def _same_key[R: NamedRow](model: type[R], name: str) -> Select[tuple[R]]:
    # Both sides folded by Postgres; see the module docstring for why.
    return select(model).where(func.lower(func.btrim(model.name)) == func.lower(name))


async def find_by_name[R: NamedRow](session: AsyncSession, model: type[R], name: str) -> R | None:
    """The stored row `name` names under the natural key, or None.

    `name` is compared as given apart from trimming — pass the user's input. Where
    rows written before #107 already collide, this returns one of them; which one is
    not specified, and the importer reports that state as ambiguous.
    """
    return await session.scalar(_same_key(model, name.strip()).limit(1))


async def require_unique_name[R: NamedRow](
    session: AsyncSession,
    model: type[R],
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """`clean_name(name)`, or a `ConflictError` naming the row that already holds it.

    Callers take the write gate **before** calling this — it is a check-then-insert,
    and the gate is what makes two writers naming the same new shop at once produce
    one row and one 409 rather than two rows (rule 7.1).
    """
    cleaned = clean_name(name)
    stmt = _same_key(model, cleaned)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    existing = await session.scalar(stmt.limit(1))
    if existing is not None:
        noun = _NOUN[model]
        raise ConflictError(
            f"a {noun} named '{existing.name}' already exists ({existing.id}) — names "
            f"are matched case-insensitively, so reuse it or choose a different name"
        )
    return cleaned

"""One rule for what a retailer's or catalog item's name *is* (#107, rule 3).

The CSV importer treats the case-insensitive name as the **natural key** for
retailers and every catalog table (`spec._name_key`, design notes §12.4): an
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

The comparison is `lower(btrim(name, WHITESPACE))` on both sides, **in Postgres**.
Both sides in one runtime because Postgres `lower()` and Python `str.lower()`
disagree on Turkish `İ`, and a predicate that folds one side each way misses the
exact stored spelling (#49). Trimmed on the stored side because rows written before
this module existed can carry surrounding whitespace — the browser forms never
trimmed and neither did the create routes — and the importer's `strip().lower()`
reads `" HLJ "` and `HLJ` as one shop. The trim set is generated from this
runtime's `str.isspace()`, i.e. exactly what `str.strip()` removes from the input
here and in the importer, so a legacy name padded with a tab, a no-break space or
an ideographic space is the same key on both sides (PR #109 review, P3-1 — plain
`btrim` trims `0x20` only, and those four were each a second row).

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
from app.models import Consumable, DisplayItem, Retailer, Tool, Upgrade

type NamedRow = Retailer | Tool | Consumable | Upgrade | DisplayItem

#: Every character Python's `str.strip()` removes, generated from `str.isspace()` at
#: import so it can never drift from `clean_name` or the importer's `_norm_name`.
#: Handed to Postgres `btrim` as its trim set — `btrim(text, text)` is character-
#: aware for `text`, so the multi-byte members (NBSP, U+3000) trim as one character
#: each. Scanned over the Basic Multilingual Plane: every whitespace code point
#: Unicode defines lives there. 29 characters on current Pythons.
WHITESPACE = "".join(chr(code) for code in range(0x10000) if chr(code).isspace())

#: What the refusal calls the row — the API's own vocabulary, article included, so
#: the sentence reads the same for every table ("an upgrade", not "a upgrade").
#: A model missing from here is a `KeyError` inside the conflict path, i.e. a 500
#: where a 409 was owed — which is what `display_items` did before #126 added it.
_NOUN: dict[type, str] = {
    Retailer: "a retailer",
    Tool: "a tool",
    Consumable: "a consumable",
    Upgrade: "an upgrade",
    DisplayItem: "a display item",
}


def clean_name(name: str) -> str:
    """The name as it is stored. Trims; refuses blank."""
    cleaned = name.strip()
    if not cleaned:
        raise InvalidInputError("name cannot be blank")
    return cleaned


def clean_required_text(value: str, field: str) -> str:
    """`clean_name`'s rule for the other NOT NULL text columns — `category` on tools,
    consumables and display items, `manufacturer` on upgrades.

    `min_length=1` on the request schema is satisfied by a space, and the order
    dispatch tested `not new_item.category`, which a space also passes — so
    `category: "   "` was stored verbatim and `POST /display-items` answered 201
    (#129 review, P3-4). The check belongs beside `clean_name` because it is the
    same rule about the same kind of column, and in the service because three
    writers reach these tables (rule 1).

    The CSV importer already agreed: `spec.parse_text` strips and returns None for a
    blank cell, so this brings the live writers into line with it rather than
    inventing a fourth opinion.
    """
    cleaned = value.strip()
    if not cleaned:
        raise InvalidInputError(f"{field} cannot be blank")
    return cleaned


def clean_optional_text(value: str | None) -> str | None:
    """Trimmed, with blank or whitespace-only meaning "not recorded".

    The rule `_normalize_series` established for a free-text column (#113 review,
    P3-1): a stored `"  "` is indistinguishable from a value the user typed, and it
    would appear as an empty option the moment anything offers these columns as a
    typeahead — which is what #127 does with `category`.
    """
    if value is None:
        return None
    return value.strip() or None


def _same_key[R: NamedRow](model: type[R], name: str) -> Select[tuple[R]]:
    # Both sides folded by Postgres, the stored side trimmed with Python's own
    # whitespace set; see the module docstring for why.
    return select(model).where(func.lower(func.btrim(model.name, WHITESPACE)) == func.lower(name))


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
    one row and one 409 rather than two rows (rule 7.1). The lookup itself is a
    plain read, never `FOR UPDATE`: `update_catalog_item` calls this while holding
    a catalog row lock, and a locked lookup would be a second catalog lock taken
    outside the uuid-ordered set the order dispatch uses (`_lock_catalog_targets`)
    — a cycle. The gate serialises the writers; the read does not need to.
    """
    cleaned = clean_name(name)
    stmt = _same_key(model, cleaned)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    existing = await session.scalar(stmt.limit(1))
    if existing is not None:
        noun = _NOUN[model]
        raise ConflictError(
            f"{noun} named '{existing.name}' already exists ({existing.id}) — names "
            f"are matched case-insensitively, so reuse it or choose a different name"
        )
    return cleaned

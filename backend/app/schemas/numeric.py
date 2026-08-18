"""Integer field types bounded by what the column can actually hold.

Every integer column in this schema is a PostgreSQL `integer` — int4 — and until
now not one request field said so. `Field(ge=0)` without a ceiling accepts
2,147,483,648 happily, and the refusal arrives from the database as an
`IntegrityError` at flush: a 500 naming a constraint, raised after other rows in
the same transaction have already been written, rather than a 422 naming the
field the caller got wrong (rule 6).

The bound comes from `services.numeric.INT4_MAX`, which is also where the CSV
importer's `require_int4` reads it. That is the point of importing it rather than
writing the number here — #73 fixed this class on the CSV path alone, and the way
a two-boundary rule goes wrong is not one side forgetting to check but the two
sides checking against slightly different numbers.

Use these instead of a bare `int` on anything that reaches a column. Which lower
bound applies is a per-field question — stock floors at zero, a line quantity
starts at one — so they differ; the ceiling never does.
"""

from typing import Annotated, Any

from pydantic import BeforeValidator, Field

from app.services.numeric import INT4_MAX, INT4_MIN


def _reject_bool(value: Any) -> Any:
    """Refuse `true`/`false` where a number is meant.

    `bool` subclasses `int` in Python, so Pydantic's lax mode accepts JSON `true`
    as 1 and `false` as 0 — silently, on every integer field in this schema. That
    is not a typing curiosity: `{"quantity": true}` on an order line is a quantity
    of 1, which spawns a kit and records a purchase nobody made, and
    `{"delta": true}` adds one to stock. A caller that sends a boolean has a bug,
    and the honest answer is a 422 naming the field rather than a plausible 1.

    Rejected here rather than by `strict=True`, which would also refuse `"5"` —
    string-to-int coercion is long-standing behaviour on these fields and is not
    what was wrong (#100 review, Cursor Grok 4.6).
    """
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    return value


#: Applied to every alias below, so the refusal cannot be added to one and
#: forgotten on the others — which is the shape #73/#74 kept failing in.
#:
#: It must come *after* `Field(...)` in each `Annotated`, and that ordering is
#: load-bearing rather than style. Put first, the validator wraps a bare `int` and
#: the constraints then serialize as raw `ge`/`le` keywords instead of
#: `minimum`/`maximum` — so the bound vanishes from the published OpenAPI schema
#: and from the contract test that reads it, while still being enforced at
#: runtime. A silently weaker published contract is exactly what that test exists
#: to prevent, so it catches this; the comment is here so the next person does not
#: have to rediscover why.
_NotBool = BeforeValidator(_reject_bool)

#: Zero or more, up to what int4 holds. Stock levels, prices, thresholds.
NonNegativeInt4 = Annotated[int, Field(ge=0, le=INT4_MAX), _NotBool]

#: One or more, up to what int4 holds. Quantities where zero is meaningless.
PositiveInt4 = Annotated[int, Field(gt=0, le=INT4_MAX), _NotBool]

#: Signed, for a delta that may go either way. Nothing is *stored* signed — the
#: floor on stock is zero — but an adjustment is arithmetic on a stored value and
#: has to be a number the column could have held in the first place.
Int4 = Annotated[int, Field(ge=INT4_MIN, le=INT4_MAX), _NotBool]


#: One to five stars. Not an int4 bound — the range is a product rule and the
#: column could hold far more — but it lives here because this is where integers
#: that a request can set are declared, and being declared anywhere else is
#: exactly how it came to be the one write integer that took a boolean. `true`
#: was a rating of 1 on kits and retailers through both doors, on fields whose
#: own `ge=1` made `false` look correctly refused (#102 review, Cursor Grok 4.6).
Rating = Annotated[int, Field(ge=1, le=5), _NotBool]

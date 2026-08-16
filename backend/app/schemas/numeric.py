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

from typing import Annotated

from pydantic import Field

from app.services.numeric import INT4_MAX

#: Zero or more, up to what int4 holds. Stock levels, prices, thresholds.
NonNegativeInt4 = Annotated[int, Field(ge=0, le=INT4_MAX)]

#: One or more, up to what int4 holds. Quantities where zero is meaningless.
PositiveInt4 = Annotated[int, Field(gt=0, le=INT4_MAX)]

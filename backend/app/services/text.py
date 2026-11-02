"""Text the database cannot hold (#346).

PostgreSQL's `text` has no U+0000, and asyncpg cannot encode an unpaired surrogate
as UTF-8 at all. JSON can spell both (`"\\u0000"`, `"\\ud800"`) and a CSV cell or a
query string can carry a NUL, so a value someone sent reached the driver and came
back as a 500 naming SQL: rule 6's class, on every writer and every text filter.

Refused, not stripped. A character silently dropped is the "the import looked fine,
the value is slightly wrong" outcome #42 decided against for encodings.

One predicate, read by each boundary (the `services/numeric.py` shape, rule 1): the
request schemas (`schemas/base.py`), the importer's text cell (`spec.parse_text`),
the services' text filters (`refuse_unstorable_text`) and the MCP OAuth state store,
whose keys a client names.
"""

import re

from app import error_codes
from app.exceptions import InvalidInputError

_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")

UNSTORABLE_MESSAGE = (
    "contains a character plamotrack can't store (a NUL, or half of a broken "
    "Unicode pair) — remove it and try again"
)


def is_storable_text(value: str) -> bool:
    """Whether a `text` column could hold this value. Other control characters,
    and a character outside the BMP, are ordinary text."""
    return _UNSTORABLE.search(value) is None


def require_storable_text(value: str) -> str:
    """`value`, or `ValueError` — the shape a schema validator and a cell parser
    both turn into a refusal naming the field."""
    if not is_storable_text(value):
        raise ValueError(UNSTORABLE_MESSAGE)
    return value


def refuse_unstorable_text(field: str, value: str | None) -> None:
    """The service-layer refusal, for text that reaches a query as an argument
    rather than through a request schema: a list filter, the catalog search, a
    shop named to MCP's `create_order`. Here so REST and MCP answer alike."""
    if value is not None and not is_storable_text(value):
        raise InvalidInputError(
            f"{field} {UNSTORABLE_MESSAGE}",
            code=error_codes.REQUEST_TEXT_UNSTORABLE,
            params={"field": field},
        )

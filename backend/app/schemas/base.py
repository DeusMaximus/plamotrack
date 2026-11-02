"""The base of every request body (#346): text the database cannot hold is a 422
naming the field, from any field of any model, on REST and MCP alike.

A base class rather than an alias on each field (the `schemas/numeric.py` shape),
because the way this rule fails is a new field nobody thought about: a wildcard
validator has already seen it. A new *model* is what could still miss it, so
`tests/test_unstorable_text.py` walks the route graph and the MCP tools and fails on
any request model that does not come from here.
"""

from typing import Any

from pydantic import BaseModel, field_validator

from app.services.text import require_storable_text


def _check(value: Any) -> Any:
    if isinstance(value, str):
        require_storable_text(value)
    elif isinstance(value, list):
        for item in value:
            _check(item)
    return value


class RequestModel(BaseModel):
    """A request body whose text may reach a column."""

    @field_validator("*", mode="after")
    @classmethod
    def _text_is_storable(cls, value: Any) -> Any:
        return _check(value)

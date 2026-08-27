"""The REST error envelope (#25) — what every failed response body looks like.

`detail` is the pre-#25 contract, unchanged: an English sentence for domain
errors, FastAPI's list of findings for request validation — existing clients
that read only `detail` keep working, and the string-vs-list shape still tells
"the service refused" from "the schema spoke". `code` + `params` are the
additive machine contract: stable condition identifiers (`app/error_codes.py`)
with the interpolation values, which is what a translated browser renders.
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    """A refused operation: NotFound (404), Conflict (409), InvalidInput (422)."""

    detail: str = Field(
        description="English explanation — useful as-is; render `code` instead when known.",
    )
    code: str = Field(
        description="Stable semantic condition, `<domain>.<condition>`, e.g. "
        "'order.already_received'. Never derived from wording.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Values the condition involves — snake_case keys, JSON scalars.",
    )


class ValidationErrorEnvelope(BaseModel):
    """A request FastAPI's schema layer refused before any service ran (422)."""

    detail: list[dict[str, Any]] = Field(
        description="FastAPI's validation findings, byte-compatible with the default body.",
    )
    code: str = Field(description="Always 'request.validation'.")
    params: dict[str, Any] = Field(
        description="{'errors': [{'field', 'type'}, ...]} — the findings, normalized.",
    )


# Attached to every router in main.py — documentation that these statuses share
# one envelope, not a promise that every route can produce every status.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "The addressed record does not exist."},
    409: {"model": ErrorEnvelope, "description": "Stored state refuses the operation."},
    422: {
        "model": ErrorEnvelope | ValidationErrorEnvelope,
        "description": "Semantically invalid input (string detail) or a request the "
        "schema layer refused (list detail, code 'request.validation').",
    },
}

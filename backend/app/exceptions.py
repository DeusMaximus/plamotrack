from collections.abc import Mapping


class DomainError(Exception):
    """Base for errors raised by the service layer, shared by REST and MCP.

    `detail` is the English sentence and stays the exception's str() — MCP's
    ToolError and the REST `detail` field both carry it unchanged (#25 is
    additive). `code` is the stable semantic identifier (`app/error_codes.py`)
    a client switches on and the browser translates; `params` carry the values
    the sentence interpolates — snake_case keys, JSON-scalar values, and only
    values every raise of that code can promise (the shared fixture declares
    them, and the frontend catalogue test holds translations to that set).
    """

    def __init__(self, detail: str, *, code: str, params: Mapping[str, object] | None = None):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.params: dict[str, object] = dict(params or {})


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    """State conflict, e.g. insufficient stock."""


class InvalidInputError(DomainError):
    """Payload is well-formed but semantically invalid for this operation."""

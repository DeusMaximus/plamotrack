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


class UnauthenticatedError(DomainError):
    """No credential, or a presented one that fails, on a route that needs one
    (§5.5). 401. Raised by the authorization dependency (`app/auth/dependency.py`)
    and the resolver, not by a service — the service layer trusts that a caller
    reached it. `challenge`, when set, is the `WWW-Authenticate` value the
    response carries (RFC 7235 §3.1 — a 401 names the scheme it accepts): the
    dependency's bare `Bearer` for an absent credential, and RFC 6750's
    `Bearer error="invalid_token"` for a presented bearer that failed (#189)."""

    def __init__(
        self,
        detail: str,
        *,
        code: str,
        params: Mapping[str, object] | None = None,
        challenge: str | None = None,
    ):
        super().__init__(detail, code=code, params=params)
        self.challenge = challenge


class ForbiddenError(DomainError):
    """An authenticated principal without the scope the route requires (§5.5).
    403 — the credential is valid, the grant is not enough. Raised by the
    authorization dependency and by the import-apply admin check."""


class GoneError(DomainError):
    """The thing addressed existed once and is deliberately gone for good (410):
    the setup token's route after the instance is claimed (§5.5, family 3)."""


class RateLimitedError(DomainError):
    """The failure budget is shut (429, §5.6 brute force): `retry_after` is the
    whole seconds until the next attempt is allowed, sent as `Retry-After` by the
    handler as well as in `params`."""

    def __init__(
        self,
        detail: str,
        *,
        code: str,
        params: Mapping[str, object] | None = None,
        retry_after: int,
    ):
        super().__init__(detail, code=code, params=params)
        self.retry_after = retry_after

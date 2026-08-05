class DomainError(Exception):
    """Base for errors raised by the service layer, shared by REST and MCP."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    """State conflict, e.g. insufficient stock."""


class InvalidInputError(DomainError):
    """Payload is well-formed but semantically invalid for this operation."""

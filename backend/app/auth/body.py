"""Bounded request bodies (§5.6, resource exhaustion; #221 item 1).

An anonymous route that takes a body used to be read whole before anything
judged it — `Request.body()` in the protocol guards, FastAPI's parser for the
login and setup forms — under nothing smaller than the ingress's server-wide
32 MiB cap, sized for CSV imports. The route policy registry now declares a
budget per such route (`RoutePolicy.max_body_bytes`); the pre-routing gate
enforces it for the app's routes and the protocol guards for the mount's, with
this reader, before a parser sees a byte past it. The bundled nginx duplicates
the cheap half as `client_max_body_size` on the same routes, generated from the
same declaration (rule 12) — but the app is the authority, as always.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import Receive, Scope


def declared_length(scope: Scope) -> int | None:
    """The `Content-Length` a request declares, or None when absent or not a
    number (a malformed value is the server's 400 later; it declares nothing)."""
    value = Headers(scope=scope).get("content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def read_bounded(scope: Scope, receive: Receive, limit: int) -> bytes | None:
    """The whole body when it is within `limit` bytes, None when it is not —
    decided from `Content-Length` before a byte is read when the header is
    present, otherwise while reading, stopping at the first chunk that takes
    the total past the limit. What is read is what is held: never more than
    `limit` plus one chunk."""
    declared = declared_length(scope)
    if declared is not None and declared > limit:
        return None
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def replay(body: bytes) -> Receive:
    """A `receive` that hands the app the body already read, as one message."""

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return receive

"""Test-only instrumentation for the modern-era hold-and-cancel gate (#244).

The `2026-07-28` transport commits `text/event-stream` and sends keepalive
pings once a tool handler runs past the SDK's ping interval, even when the
handler emits no notifications (`json_response=False`, which this mount uses).
plamotrack exposes no long-running tool of its own — every tool is a short,
transactional read or write — so exercising that hold/keepalive/cancel path
through the real transport (and the packaged proxy chain) needs an *existing*
tool call made to wait deliberately.

`install_hold_probe` adds a FastMCP middleware that, for one existing read tool
(`get_meta`), holds a real database connection idle-in-transaction for a bounded
number of seconds **before** the tool body. The handler therefore holds a database
backend for the duration; a client that aborts mid-hold cancels the handler,
which cancels the wait and returns the connection — the cancellation-and-
cleanup the gate observes through `pg_stat_activity`.

This is **instrumentation, not a product path**. It is installed only when
`PLAMOTRACK_ENABLE_TEST_HOLD` names a positive number of seconds; the shipped
image never sets it (the Dockerfile and both compose files leave it unset), and
`tests/test_mcp_modern_hold.py` asserts the mount is inert without it. It adds
**no tool and no route** — the tool surface and the authorization registry are
unchanged — so it needs no `MCP_TOOL_SCOPES` entry and cannot widen access:
`get_meta` still requires `collection:read`, and the wait runs behind the
transport's bearer check like any other call. Coverage limit: it proves the
transport's and proxy's handling of a held modern SSE response and the
handler's cancellation, not any product behaviour, since no product tool holds.
"""

from __future__ import annotations

import anyio
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from sqlalchemy import text

#: The env var that arms the probe (a positive integer number of seconds).
ENABLE_ENV = "PLAMOTRACK_ENABLE_TEST_HOLD"
#: A recognisable marker in the held connection's last statement, so the gate
#: can find exactly this backend in pg_stat_activity.
HOLD_MARKER = "plamotrack_hold_probe"
#: The existing read tool whose call is made to wait — chosen because it is a
#: pure read with no side effects.
HELD_TOOL = "get_meta"


class HoldProbeMiddleware(Middleware):
    """Makes one existing tool call hold a database backend for `seconds`."""

    def __init__(self, seconds: int) -> None:
        self._seconds = seconds

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        if getattr(context.message, "name", None) == HELD_TOOL:
            from app.db import session_scope

            async with session_scope() as session:
                # A real backend, checked out and left idle-in-transaction under
                # a recognisable marker, held for the duration by a Python-level
                # wait. A client abort cancels this await promptly (unlike
                # `pg_sleep`, which Postgres does not interrupt on disconnect),
                # and the session-scope exit rolls back and returns the
                # connection — the cancellation-and-cleanup the gate verifies in
                # pg_stat_activity by this marker.
                await session.execute(text(f"SELECT '{HOLD_MARKER}'"))
                await anyio.sleep(self._seconds)
        return await call_next(context)


def hold_probe_seconds(environ) -> int:
    """Parse `PLAMOTRACK_ENABLE_TEST_HOLD` into a bounded number of seconds; 0
    (off) for anything unset, non-numeric, non-positive, or above the cap."""
    raw = environ.get(ENABLE_ENV)
    if raw is None:
        return 0
    try:
        seconds = int(raw)
    except ValueError:
        return 0
    return seconds if 0 < seconds <= 600 else 0


def install_hold_probe(mcp_server, seconds: int) -> bool:
    """Install the probe middleware when `seconds > 0`. Returns whether it was."""
    if seconds <= 0:
        return False
    mcp_server.add_middleware(HoldProbeMiddleware(seconds))
    return True

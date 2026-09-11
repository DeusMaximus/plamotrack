"""Modern-era (`2026-07-28`) hold-and-cancel over the real transport (#244).

plamotrack's mount serves the modern era from the same endpoint as the
handshake era (§7.1). The legacy standalone SSE channel is held and cancelled
by `ingress_matrix.hold_stream` / the deployment gate; this file is its modern
twin at the transport layer, because ASGI-in-memory clients buffer the whole
response and cannot observe a held stream — so it drives a **real uvicorn
socket**.

The modern era has no standalone GET channel and opens no session, and
plamotrack exposes no long-running tool, so the hold is built around an
*existing* tool call (`get_meta`) made to wait by the env-gated
`app.mcp_hold_probe` middleware (a controlled database wait — see that module).
`json_response=False` (this mount's setting) means the SDK commits
`text/event-stream` and sends keepalive pings once the handler runs past the
ping interval even with no notification; the interval is monkeypatched down
here for speed (the gate uses the real 15 s). What is asserted: the modern POST
commits SSE with no `Mcp-Session-Id` and `no-cache`; keepalive pings arrive
across the window; a client abort cancels the handler server-side; and the held
database connection is returned (no lingering backend under the probe marker).

Coverage limit: the wait is test instrumentation, not a product path — no
plamotrack tool holds a stream — so this proves the transport's and the
handler's behaviour, not a product feature.
"""

from __future__ import annotations

import asyncio
import socket

import anyio
import httpx
import pytest
import uvicorn
from fastmcp import FastMCP
from fastmcp.server.http import create_streamable_http_app
from sqlalchemy import text

from app.db import session_scope
from app.mcp_hold_probe import HOLD_MARKER, hold_probe_seconds, install_hold_probe

pytestmark = pytest.mark.anyio

_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "modern-hold-test", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2026-07-28",
    "Mcp-Method": "tools/call",
    "Mcp-Name": "get_meta",
}


def _call_get_meta() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "get_meta", "arguments": {}, "_meta": _META},
    }


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _held_backends() -> int:
    async with session_scope() as session:
        result = await session.execute(
            text(
                f"select count(*) from pg_stat_activity where query like '%{HOLD_MARKER}%' "
                "and pid <> pg_backend_pid()"
            )
        )
        return int(result.scalar_one())


def _isolated_app(hold_seconds: int):
    """An isolated instance whose one tool is `get_meta`, with the modern-hold
    probe armed to `hold_seconds` — never the shipped `app.mcp.mcp`."""
    server = FastMCP("modern-hold-test")

    @server.tool
    async def get_meta() -> dict:
        return {"ok": True}

    install_hold_probe(server, hold_seconds)
    return create_streamable_http_app(
        server=server,
        streamable_http_path="/",
        auth=None,
        json_response=False,
        stateless_http=False,
    )


class _RunningServer:
    def __init__(self, app):
        self._app = app
        self.port = _free_port()

    async def __aenter__(self):
        self._server = uvicorn.Server(
            uvicorn.Config(self._app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        # Embedded in the test's own loop: never touch process signal handlers.
        self._server.install_signal_handlers = lambda: None
        self._task = asyncio.create_task(self._server.serve())
        for _ in range(200):
            if self._server.started:
                return self
            await asyncio.sleep(0.02)
        raise RuntimeError("uvicorn did not start")

    async def __aexit__(self, *exc):
        self._server.should_exit = True
        await self._task

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"


async def test_a_modern_call_held_past_the_window_streams_pings_and_cancels(monkeypatch):
    """The whole modern hold-and-cancel contract in one flow: commit, keepalive,
    abort, server-side cancellation, and connection cleanup."""
    import mcp.server._streamable_http_modern as modern

    monkeypatch.setattr(modern, "_SSE_PING_INTERVAL", 1.0)
    async with _RunningServer(_isolated_app(15)) as server:
        assert await _held_backends() == 0
        info: dict = {}
        pings = 0
        async with httpx.AsyncClient(base_url=server.base, timeout=20) as client:
            async with client.stream(
                "POST", "/", json=_call_get_meta(), headers=_HEADERS
            ) as response:
                info["status"] = response.status_code
                info["content_type"] = response.headers.get("content-type")
                info["session"] = response.headers.get("mcp-session-id")
                info["cache_control"] = response.headers.get("cache-control")
                async for line in response.aiter_lines():
                    if line.startswith(": ping"):
                        pings += 1
                    if pings >= 2:
                        break  # abort mid-hold by leaving the stream
        # The response committed SSE, with no session and no-cache, and pinged.
        assert info["status"] == 200
        assert (info["content_type"] or "").startswith("text/event-stream")
        assert info["session"] is None
        assert "no-cache" in (info["cache_control"] or "")
        assert pings >= 2
        # The abort cancelled the handler server-side and returned the held
        # connection: the probe's backend is gone within a short window.
        for _ in range(40):
            if await _held_backends() == 0:
                break
            await anyio.sleep(0.25)
        assert await _held_backends() == 0


async def test_a_modern_call_that_is_not_aborted_completes_with_its_result(monkeypatch):
    """Held past the ping window, then allowed to finish: the final SSE frame is
    the tool's own result, and the connection is released."""
    import mcp.server._streamable_http_modern as modern

    monkeypatch.setattr(modern, "_SSE_PING_INTERVAL", 1.0)
    async with _RunningServer(_isolated_app(2)) as server:
        got_result = False
        async with httpx.AsyncClient(base_url=server.base, timeout=20) as client:
            async with client.stream(
                "POST", "/", json=_call_get_meta(), headers=_HEADERS
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data:") and '"id":3' in line and "result" in line:
                        got_result = True
                        break
        assert got_result
        assert await _held_backends() == 0


async def test_the_probe_is_off_and_the_shipped_mount_carries_no_hold_middleware():
    """The instrumentation is off unless the environment arms it. Installing at
    zero seconds is a no-op, and the shipped `app.mcp.mcp` — built with the flag
    unset under the test suite — carries no hold middleware."""
    from app.mcp import mcp as shipped
    from app.mcp_hold_probe import HoldProbeMiddleware

    server = FastMCP("off")
    assert install_hold_probe(server, 0) is False

    def _has_probe(mcp_server) -> bool:
        middlewares = getattr(mcp_server, "middleware", [])
        return any(isinstance(m, HoldProbeMiddleware) for m in middlewares)

    assert not _has_probe(server)
    assert not _has_probe(shipped)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        ("", 0),
        ("  ", 0),
        ("nope", 0),
        ("0", 0),
        ("-5", 0),
        ("601", 0),
        ("15", 15),
        ("600", 600),
    ],
)
def test_hold_probe_seconds_parses_and_bounds_the_env(value, expected):
    env = {} if value is None else {"PLAMOTRACK_ENABLE_TEST_HOLD": value}
    assert hold_probe_seconds(env) == expected

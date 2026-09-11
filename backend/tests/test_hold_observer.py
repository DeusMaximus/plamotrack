"""Offline, deterministic coverage of the held-stream gate (#244; Codex #250 F1/F3).

`ingress_matrix.hold_stream_modern` (and the legacy `hold_stream`) must *assert*
that a held SSE keeps flowing, not merely report a gap: an initial-ping-then-
silence stream, a >2-interval gap, a completed body on a still-open socket, and
an empty stream are all gate failures. `deployment_gate.phase_modern_hold` must
disarm the probe flag even when arming's restart fails. Both are exercised here
with a scripted socket and a frozen clock — no network, no host — so the checks
run in CI (the tracked home of what the remote gate proves live)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import deployment_gate as gate
import ingress_matrix as matrix

_HEADERS = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
)
_PING = b"8\r\n: ping\n\n\r\n"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _Stream:
    """A scripted socket: `first` is returned once (headers + any initial body),
    then `(at, bytes)` pairs set the clock and deliver a chunk, then every recv
    is a TimeoutError advancing the clock by the socket timeout."""

    def __init__(self, clock: _Clock, first: bytes, later=()) -> None:
        self.clock = clock
        self.first: bytes | None = first
        self.later = list(later)
        self.closed = False

    def sendall(self, _value) -> None:
        pass

    def settimeout(self, _value) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def recv(self, _size) -> bytes:
        if self.first is not None:
            first, self.first = self.first, None
            return first
        if self.later:
            at, value = self.later.pop(0)
            self.clock.now = at
            return value
        self.clock.now += 2.0
        raise TimeoutError


def _run(first: bytes, later=()):
    clock = _Clock()
    stream = _Stream(clock, first, later)
    with (
        patch.object(matrix.socket, "create_connection", return_value=stream),
        patch.object(matrix.time, "monotonic", clock.monotonic),
    ):
        return matrix.hold_stream_modern(
            "http://127.0.0.1:8080", matrix.Bearer(raw="fixture-only", token_id=""), "/mcp/", 75
        )


@pytest.mark.parametrize(
    ("name", "first", "later", "expect_ok", "reason_needle"),
    [
        (
            "healthy 15 s pings",
            _HEADERS,
            [(n, _PING) for n in (15, 30, 45, 60, 75)],
            True,
            "max gap",
        ),
        ("initial ping then silence", _HEADERS + _PING, [], False, "silent"),
        ("35 s gap between pings", _HEADERS + _PING, [(35, _PING)], False, "gap"),
        ("completed body, socket open", _HEADERS + _PING + b"0\r\n\r\n", [], False, "completed"),
        ("empty silent stream", _HEADERS, [], False, "silent"),
    ],
)
def test_the_modern_hold_observer_only_passes_a_live_stream(
    name, first, later, expect_ok, reason_needle
):
    ok, message = _run(first, later)
    assert ok is expect_ok, (name, message)
    assert reason_needle in message, (name, message)


class _Results:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, bool]] = []

    def record(self, step: str, result: str, ok: bool = True) -> None:
        self.records.append((step, result, ok))


class _Host:
    """A host whose `up()` raises for the first `fail_ups` calls."""

    def __init__(self, fail_ups: int) -> None:
        self.fail_ups = fail_ups
        self.env: dict[str, str | None] = {}
        self.ups = 0

    def psql(self, _query: str):
        return ["0"]

    def env_set(self, **values: str | None) -> None:
        self.env.update(values)

    def up(self) -> None:
        self.ups += 1
        if self.ups <= self.fail_ups:
            raise gate.GateError("simulated startup failure")


class _Ctx:
    def __init__(self, host: _Host) -> None:
        self.host = host
        self.hold = 75
        self.results = _Results()

    def load(self, _name: str) -> str:
        return "fixture-only"


@pytest.mark.parametrize("fail_ups", [1, 99])
def test_a_startup_failure_still_disarms_the_hold_flag(fail_ups):
    """Arming's restart failing (or every restart failing) must leave the probe
    flag disarmed and re-raise the original error, never leave `get_meta`
    delayed for a later run (Codex #250 F3)."""
    host = _Host(fail_ups=fail_ups)
    ctx = _Ctx(host)
    with pytest.raises(gate.GateError, match="simulated startup failure"):
        gate.phase_modern_hold(ctx)
    assert host.env.get("PLAMOTRACK_ENABLE_TEST_HOLD") is None

"""The packaged worker budget and the ingress harness's secret outputs (#193)."""

import errno
import importlib
import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner
from uvicorn import Config

from ingress_matrix import write_private


@pytest.mark.parametrize(
    "web_workers,uvicorn_workers", [(None, None), ("4", None), (None, "4"), ("4", "8")]
)
def test_packaged_worker_count_ignores_environment(web_workers, uvicorn_workers, monkeypatch):
    """Exercise Uvicorn's real CLI, including its two environment defaults."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    (line,) = [line for line in dockerfile.read_text().splitlines() if line.startswith("CMD ")]
    command = json.loads(line.removeprefix("CMD "))
    assert command[0] == "uvicorn"
    module = importlib.import_module("uvicorn.main")
    observed = []

    def capture(app, **kwargs):
        observed.append(Config(app, workers=kwargs["workers"]).workers)

    monkeypatch.setattr(module, "run", capture)
    result = CliRunner().invoke(
        module.main,
        command[1:],
        env={"WEB_CONCURRENCY": web_workers, "UVICORN_WORKERS": uvicorn_workers},
    )
    assert result.exit_code == 0, result.output
    assert observed == [1]


@pytest.mark.parametrize("previous", [None, "", "a longer previous synthetic value"])
def test_private_output_creates_or_restricts_a_file(tmp_path, previous):
    path = tmp_path / "secret"
    if previous is not None:
        path.write_text(previous)
        path.chmod(0o644)
    assert write_private(str(path), "test-value\n") == path
    assert path.read_text() == "test-value\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("existing_target", [True, False])
def test_private_output_refuses_symlinks_without_touching_the_target(tmp_path, existing_target):
    target = tmp_path / "target"
    if existing_target:
        target.write_text("unchanged")
        target.chmod(0o644)
    path = tmp_path / "secret"
    path.symlink_to(target)
    with pytest.raises(OSError) as error:
        write_private(str(path), "synthetic-secret")
    assert error.value.errno == errno.ELOOP
    assert path.is_symlink()
    if existing_target:
        assert target.read_text() == "unchanged"
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
    else:
        assert not target.exists()


def test_private_output_keeps_the_open_file_when_the_path_is_replaced(tmp_path, monkeypatch):
    """Pin a path swap between restricting the file and writing its secret."""
    path = tmp_path / "secret"
    opened = tmp_path / "opened"
    target = tmp_path / "target"
    target.write_text("unchanged")
    fchmod = os.fchmod

    def replace_path(fd, mode):
        fchmod(fd, mode)
        path.rename(opened)
        path.symlink_to(target)

    monkeypatch.setattr(os, "fchmod", replace_path)
    write_private(str(path), "synthetic-secret")
    assert opened.read_text() == "synthetic-secret"
    assert stat.S_IMODE(opened.stat().st_mode) == 0o600
    assert target.read_text() == "unchanged"


# --- #194: the matrix through a TLS proxy ------------------------------------------
import http.client  # noqa: E402
import socketserver  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import ingress_matrix  # noqa: E402
from ingress_matrix import (  # noqa: E402
    HOSTILE_HOST_LABELS,
    Bearer,
    Credential,
    Response,
    Tokens,
    hold_stream,
    is_loopback_base,
    rows,
    write_rows,
)


@pytest.mark.parametrize(
    "base,scheme,port",
    [
        ("http://127.0.0.1:8080", "http", 8080),
        ("http://nas.lan", "http", 80),
        ("https://plamotrack.example", "https", 443),
        ("https://plamotrack.example:8443", "https", 8443),
    ],
)
def test_send_picks_the_transport_and_port_from_the_base_scheme(base, scheme, port, monkeypatch):
    """An https BASE_URL is an HTTPSConnection on 443 through the module's TLS
    context; http stays what it was, so CI's loopback run is byte-identical."""
    seen = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b"{}"

        def getheaders(self):
            return [("Content-Type", "application/json")]

    def make(kind):
        class Fake:
            def __init__(self, host, port_, timeout=None, context=None):
                seen.update(kind=kind, host=host, port=port_, context=context)

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return FakeResponse()

            def close(self):
                pass

        return Fake

    monkeypatch.setattr(http.client, "HTTPConnection", make("http"))
    monkeypatch.setattr(http.client, "HTTPSConnection", make("https"))
    resp = ingress_matrix.send(base, ingress_matrix.Row("probe", "GET", "/", 200))
    assert resp.status == 200
    assert seen["kind"] == scheme
    assert seen["port"] == port
    if scheme == "https":
        assert seen["context"] is ingress_matrix.TLS_CONTEXT
    else:
        assert seen["context"] is None


@pytest.mark.parametrize(
    "base,loopback",
    [
        ("http://127.0.0.1:8080", True),
        ("http://localhost:8080", True),
        ("http://[::1]:8080", True),
        ("http://nas.lan:8080", False),
        ("https://plamotrack.example", False),
        ("http://10.1.1.129:8080", False),
    ],
)
def test_the_loopback_reading_of_the_base_name(base, loopback):
    assert is_loopback_base(base) is loopback


def test_behind_proxy_skips_exactly_the_three_hostile_host_rows():
    """A proxy answers a foreign Host itself, so those three rows never reach
    nginx; nothing else changes — the same labels in the same order otherwise."""
    with_nginx = [row.label for row in rows(None)]
    with_proxy = [row.label for row in rows(None, behind_proxy=True)]
    assert set(with_nginx) - set(with_proxy) == set(HOSTILE_HOST_LABELS)
    assert [label for label in with_nginx if label not in HOSTILE_HOST_LABELS] == with_proxy
    assert len(HOSTILE_HOST_LABELS) == 3
    for label in HOSTILE_HOST_LABELS:
        assert label in with_nginx


@pytest.mark.parametrize(
    "base,signed_in,status,code",
    [
        ("http://127.0.0.1:8080", True, 201, None),
        ("http://127.0.0.1:8080", False, 401, "auth.unauthenticated"),
        ("https://plamotrack.example", True, 403, "ingress.origin_not_allowed"),
        ("https://plamotrack.example", False, 403, "ingress.origin_not_allowed"),
    ],
)
def test_the_loopback_origin_write_expects_by_the_base_name(
    base, signed_in, status, code, monkeypatch
):
    """The loopback-to-loopback allowance needs both sides: against a loopback
    name the write lands (or is the dependency's 401 anonymous); against any
    other name the guard refuses it first, signed in or not."""
    sent = []

    def fake_send(base_, row, host_override=None):
        sent.append(row)
        return Response(status, {"content-type": "application/json"}, b'{"id": 1}')

    monkeypatch.setattr(ingress_matrix, "send", fake_send)
    credential = Credential(cookie="s=1", csrf_token="c") if signed_in else None
    (row, _), *_rest = write_rows(base, None, credential)
    assert row.headers["Origin"].startswith("http://localhost")
    assert row.status == status
    assert row.json_code == code


class _FakeMcpServer(socketserver.ThreadingTCPServer):
    """Just enough HTTP/1.1 to stand in for nginx + the SDK on a socket: an
    initialize that mints a session, an initialized ack, a standalone GET stream
    that pings on a short interval, and a DELETE that ends it."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *, ping_every: float, close_early_after: float | None, chunked: bool):
        super().__init__(("127.0.0.1", 0), _FakeMcpHandler)
        self.ping_every = ping_every
        self.close_early_after = close_early_after
        self.chunked = chunked
        self.deleted = threading.Event()
        self.stream_opened = threading.Event()
        self.requests: list[tuple[str, str, dict[str, str]]] = []


class _FakeMcpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        request_line = self.rfile.readline().decode("latin-1").rstrip("\r\n")
        method, path, _ = request_line.split(" ", 2)
        headers = {}
        while True:
            line = self.rfile.readline().decode("latin-1")
            if line in ("\r\n", "\n", ""):
                break
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length:
            self.rfile.read(length)
        server: _FakeMcpServer = self.server  # type: ignore[assignment]
        server.requests.append((method, path, headers))
        if method == "POST" and b"initialize" in self._peek_body(headers):
            self._respond(200, [("Mcp-Session-Id", "sess-1")], b"")
        elif method == "POST":
            self._respond(202, [], b"")
        elif method == "DELETE":
            server.deleted.set()
            self._respond(200, [], b"")
        elif method == "GET":
            self._stream(server)
        else:
            self._respond(405, [], b"")

    def _peek_body(self, headers):
        # The body was consumed above; the fake decides by the session header
        # instead: no session id yet means the initialize.
        return b"" if "mcp-session-id" in headers else b"initialize"

    def _respond(self, status, extra, body):
        head = [f"HTTP/1.1 {status} X", "Content-Type: application/json"]
        head += [f"{k}: {v}" for k, v in extra]
        head += [f"Content-Length: {len(body)}", "Connection: close", "", ""]
        self.wfile.write("\r\n".join(head).encode() + body)
        self.wfile.flush()

    def _stream(self, server: _FakeMcpServer):
        head = ["HTTP/1.1 200 OK", "Content-Type: text/event-stream", "Cache-Control: no-cache"]
        if server.chunked:
            head.append("Transfer-Encoding: chunked")
        head += ["Connection: close", "", ""]
        self.wfile.write("\r\n".join(head).encode())
        self.wfile.flush()
        server.stream_opened.set()
        started = time.monotonic()
        while True:
            if server.close_early_after is not None:
                if time.monotonic() - started >= server.close_early_after:
                    break
            if server.deleted.is_set():
                break
            time.sleep(server.ping_every)
            frame = b": ping\r\n\r\n"
            if server.chunked:
                frame = f"{len(frame):x}\r\n".encode() + frame + b"\r\n"
            try:
                self.wfile.write(frame)
                self.wfile.flush()
            except OSError:
                return
        if server.chunked:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        # then the connection closes (Connection: close) as the handler returns


@pytest.fixture
def fake_mcp():
    servers = []

    def start(**kwargs):
        server = _FakeMcpServer(**kwargs)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        host, port = server.server_address
        return server, f"http://{host}:{port}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("chunked", [True, False])
def test_hold_stream_reports_the_hold_and_the_gap_and_ends_on_delete(fake_mcp, chunked):
    server, base = fake_mcp(ping_every=0.1, close_early_after=None, chunked=chunked)
    ok, message = hold_stream(base, Bearer("ptk_x_y", "id"), "/mcp/", 1, close_grace=3)
    assert ok, message
    assert message.startswith("held 1.")
    assert "max gap 0." in message
    assert "ended 0." in message
    assert server.deleted.is_set()
    methods = [(m, p) for m, p, _ in server.requests]
    assert methods[:2] == [("POST", "/mcp/"), ("POST", "/mcp/")]
    assert ("GET", "/mcp/") in methods and ("DELETE", "/mcp/") in methods
    get_headers = next(h for m, p, h in server.requests if m == "GET")
    assert get_headers["mcp-session-id"] == "sess-1"
    assert get_headers["accept"] == "text/event-stream"


@pytest.mark.parametrize("chunked", [True, False])
def test_hold_stream_fails_when_the_chain_ends_the_stream_early(fake_mcp, chunked):
    server, base = fake_mcp(ping_every=0.1, close_early_after=0.4, chunked=chunked)
    ok, message = hold_stream(base, Bearer("ptk_x_y", "id"), "/mcp/", 3, close_grace=1)
    assert not ok
    # The observer now names *how* the stream ended early (#244, Codex #250 F1):
    # a chunked stream sends the terminal chunk, a plain one just closes the socket.
    if chunked:
        assert message.startswith("the stream completed (terminal chunk) after 0.")
    else:
        assert message.startswith("the chain closed the stream after 0.")
    assert " of 3" in message
    assert not server.deleted.is_set()


def test_hold_stream_fails_when_nothing_ends_the_stream_after_delete(fake_mcp, monkeypatch):
    server, base = fake_mcp(ping_every=0.1, close_early_after=None, chunked=False)
    # A DELETE the stream ignores: the fake acknowledges it but never breaks.
    monkeypatch.setattr(server.deleted, "set", lambda: None)
    ok, message = hold_stream(base, Bearer("ptk_x_y", "id"), "/mcp/", 1, close_grace=1)
    assert not ok
    assert message.startswith("still open 1 s after DELETE")


def test_hold_stream_reports_a_missing_session_id(fake_mcp, monkeypatch):
    _, base = fake_mcp(ping_every=0.1, close_early_after=None, chunked=False)

    def no_session(base_, row, host_override=None):
        return Response(200, {"content-type": "text/event-stream"}, b"")

    monkeypatch.setattr(ingress_matrix, "send", no_session)
    ok, message = hold_stream(base, Bearer("ptk_x_y", "id"), "/mcp/", 1, close_grace=1)
    assert not ok
    assert "mcp-session-id" in message


def test_tokens_dataclass_is_what_the_hold_receives():
    tokens = Tokens(write=Bearer("ptk_a_b", "1"), read=Bearer("ptk_c_d", "2"))
    assert tokens.write.header() == {"Authorization": "Bearer ptk_a_b"}


# --- #194: the gate driver's pure parts --------------------------------------------
import deployment_gate as gate  # noqa: E402


def test_caddyfile_normalisation_drops_comments_and_whitespace():
    reference = (
        "# a comment\nplamotrack.example {\n    reverse_proxy 127.0.0.1:8080  # trailing\n}\n"
    )
    on_host = (
        "plamotrack.example {\n\treverse_proxy 127.0.0.1:8080\n}\n\n"
        "idp.x {\n reverse_proxy 127.0.0.1:8081\n}\n"
    )
    expected = "plamotrack.example { reverse_proxy 127.0.0.1:8080 }"
    assert gate.normalised_caddyfile(reference) == expected
    assert gate.normalised_caddyfile(reference) in gate.normalised_caddyfile(on_host)
    # the name substitution the precheck applies before comparing
    renamed = reference.replace("plamotrack.example", "testhost.example")
    assert gate.normalised_caddyfile(renamed) not in gate.normalised_caddyfile(on_host)


def test_results_block_marks_failures_and_escapes_pipes():
    results = gate.Results()
    results.record("TLS", "TLSv1.3; issuer Let's Encrypt | R3")
    results.record("matrix", "1 failing / 90 ok", ok=False)
    assert results.failures == 1
    block = gate.results_markdown = results.markdown(["### Deployment gate — test"])
    assert block.startswith("### Deployment gate — test\n\n| Step | Result |\n| --- | --- |\n")
    assert "| TLS | TLSv1.3; issuer Let's Encrypt \\| R3 |" in block
    assert "| matrix **FAIL** | 1 failing / 90 ok |" in block


def test_env_set_sends_the_value_on_stdin_never_in_the_command(monkeypatch):
    """The command carries only the key name; the value travels on stdin, so a
    secret setting never appears in argv (this process's or the remote shell's).
    A `None` removes the line and sends no stdin."""
    calls = []

    def fake_run(argv, input=None, capture_output=None, text=None):
        calls.append((argv, input))

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return Done()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    host = gate.Host("root@testhost", "/opt/plamotrack")
    host.env_set(MCP_OAUTH_SIGNING_KEY="s3cret-signing-key", TRUSTED_PROXIES=None)
    (set_argv, set_stdin), (rm_argv, rm_stdin) = calls
    set_cmd, rm_cmd = set_argv[-1], rm_argv[-1]
    # the secret is on stdin, and nowhere in the command sent to ssh
    assert set_stdin == "s3cret-signing-key"
    assert "s3cret-signing-key" not in set_cmd
    assert "MCP_OAUTH_SIGNING_KEY" in set_cmd and "cat;" in set_cmd and ">> .env" in set_cmd
    # a removal is just the sed, no stdin
    assert rm_cmd == "cd /opt/plamotrack && sed -i '/^TRUSTED_PROXIES=/d' .env"
    assert rm_stdin is None
    with pytest.raises(gate.GateError):
        host.env_set(**{"not a key": "x"})


def test_a_failed_secret_edit_leaks_no_secret_anywhere(monkeypatch):
    """The regression the review asked for: force the SSH call to fail while
    setting a secret and prove the value is absent from the command argv, the
    surfaced stderr, the raised GateError, and the results Markdown a stopped
    phase renders."""
    marker = "SIGNKEYSECRET-deadbeef"
    seen_argv = {}

    def failing_run(argv, input=None, capture_output=None, text=None):
        seen_argv["argv"] = argv
        seen_argv["stdin"] = input

        class Done:
            returncode = 255
            stdout = ""
            stderr = "ssh: connect to host testhost port 22: Connection refused"

        return Done()

    monkeypatch.setattr(gate.subprocess, "run", failing_run)
    host = gate.Host("root@testhost", "/opt/plamotrack")
    with pytest.raises(gate.GateError) as error:
        host.env_set(MCP_OAUTH_SIGNING_KEY=marker)
    assert marker not in " ".join(seen_argv["argv"])  # not in argv
    assert seen_argv["stdin"] == marker  # only on stdin
    assert marker not in str(error.value)  # not in the raised error
    assert "editing .env (MCP_OAUTH_SIGNING_KEY)" in str(error.value)  # a redacted label
    # and not in the results Markdown a stopped phase writes from str(error)
    results = gate.Results()
    results.record("oidc: stopped", str(error.value), ok=False)
    assert marker not in results.markdown(["### gate"])


def test_web_last_address_reads_nginx_s_most_recent_access_record(monkeypatch):
    host = gate.Host("root@testhost", "/opt/plamotrack")
    log = (
        "web-1  | plamotrack: server_name localhost 127.0.0.1 [::1] testhost.example\n"
        'web-1  | 172.18.0.1 [07/Sep/2026:10:00:00 +0000] "GET /api/healthz HTTP/1.1" 200 15\n'
        'web-1  | 10.86.64.128 [07/Sep/2026:10:00:01 +0000] "GET /api/healthz HTTP/1.1" 200 15\n'
    )
    monkeypatch.setattr(host, "compose", lambda arguments, **kw: log)
    assert host.web_last_address() == "10.86.64.128"
    startup_only = "web-1  | plamotrack: server_name x\n"
    monkeypatch.setattr(host, "compose", lambda arguments, **kw: startup_only)
    with pytest.raises(gate.GateError):
        host.web_last_address()


def test_the_gate_s_all_phases_end_with_t13_and_the_tunnel_is_opt_in():
    assert gate.ALL == (
        "precheck",
        "lockout",
        "local",
        "modern-hold",
        "break-glass",
        "trusted-proxies",
        "oidc",
        "t13",
    )
    assert set(gate.PHASES) == set(gate.ALL) | {"tunnel"}


@pytest.mark.parametrize("mode", ["local", "oidc"])
def test_the_oidc_rows_follow_the_mode_and_name_the_public_origin(mode):
    """Local mode: the routes answer their own 404 naming the mode, no Location.
    OIDC mode: `oidc/start` is live and the callback's Location is built from
    PUBLIC_BASE_URL — the public https origin, not the base the matrix dialled."""
    tokens = Tokens(write=Bearer("ptk_a_b", "1"), read=Bearer("ptk_c_d", "2"))
    rows = {
        row.path: row
        for row in ingress_matrix.token_rows(
            "https://testhost.example", tokens, mode=mode, public_base_url="https://public.example"
        )
    }
    start = rows["/api/auth/oidc/start"]
    callback = rows["/api/auth/oidc/callback?state=x&code=y"]
    if mode == "local":
        assert (start.status, start.json_code) == (404, "auth.not_in_this_mode")
        assert (callback.status, callback.json_code, callback.location) == (
            404,
            "auth.not_in_this_mode",
            None,
        )
    else:
        assert (start.status, start.json_code) == (200, None)
        assert (callback.status, callback.location) == (
            302,
            "https://public.example/?auth_error=oidc_expired",
        )
    assert start.headers["Origin"] == "https://testhost.example"


def test_skip_rate_limits_omits_the_limiter_rows(monkeypatch, capsys):
    """A run behind a CDN skips nginx's per-address limiter checks — the latency
    and URL normalisation make them unobservable, and they are proven at the
    packaged layer — without touching any other row (#194 tunnel)."""
    called = {"rate_checks": 0, "rate_rows": 0}

    def no_rate_checks(base, mode="local"):
        called["rate_checks"] += 1
        return ["a limiter did not trip"]

    def no_rate_rows(base):
        called["rate_rows"] += 1
        return []

    monkeypatch.setattr(ingress_matrix, "rate_limit_checks", no_rate_checks)
    monkeypatch.setattr(ingress_matrix, "rate_limit_rows", no_rate_rows)
    monkeypatch.setattr(ingress_matrix, "send", lambda *a, **k: Response(200, {}, b"{}"))
    # No credential (no --password): only the anonymous rows and the skipped
    # limiter run; the stub's blanket 200 makes the rejection rows fail, but this
    # test is about the limiter branch — that it is not entered and says so.
    ingress_matrix.main(["https://x.example", "--skip-rate-limits"])
    out = capsys.readouterr().out
    assert called == {"rate_checks": 0, "rate_rows": 0}
    assert "limiter checks skipped" in out
    assert "FAIL RATE" not in out

    # And without the flag, the limiter checks do run (and, stubbed to fail here,
    # are counted) — so the skip is a real branch, not a no-op.
    called_again = {"rate_checks": 0, "rate_rows": 0}
    monkeypatch.setattr(
        ingress_matrix,
        "rate_limit_checks",
        lambda base, mode="local": called_again.__setitem__("rate_checks", 1) or [],
    )
    monkeypatch.setattr(
        ingress_matrix,
        "rate_limit_rows",
        lambda base: called_again.__setitem__("rate_rows", 1) or [],
    )
    ingress_matrix.main(["https://x.example"])
    assert called_again == {"rate_checks": 1, "rate_rows": 1}


def test_t13_partial_restore_requires_the_invalid_client_error_class():
    """A restore that dropped a secret or the store must show refresh 401
    *invalid_client* (§5.6: the class that tells a client to re-register), not
    just any 401 — the gate previously accepted invalid_grant (Codex #218 P3)."""
    intact = {"session": "owner", "pat": 200, "data": True}
    good = {"refresh_status": 401, "refresh_error": "invalid_client", "old_access_initialize": 401}
    assert gate.t13_partial_restore_ok(intact, good)
    # another 401 error class is refused
    assert not gate.t13_partial_restore_ok(intact, {**good, "refresh_error": "invalid_grant"})
    # a missing error, or the old token still accepted, or lost data, all refuse
    assert not gate.t13_partial_restore_ok(intact, {**good, "refresh_error": None})
    assert not gate.t13_partial_restore_ok(intact, {**good, "old_access_initialize": 200})
    assert not gate.t13_partial_restore_ok({**intact, "data": False}, good)


def test_the_tunnel_phase_requires_an_expected_visitor(monkeypatch):
    """The tunnel phase refuses to run without --tunnel-visitor: 'the address
    changed' is too weak, so the exact expected value must be supplied (P3)."""
    ctx = gate.Context(
        base="https://x",
        host=gate.Host("root@h", "/opt/plamotrack"),
        results=gate.Results(),
        state_dir=Path("/tmp"),
        idp=None,
        idp_user="owner",
        idp_password=None,
        hold=75,
        ca_cert=None,
        host_ip="10.0.0.9",
        tunnel_base="https://t",
        tunnel_proxy="10.0.0.5",
        tunnel_visitor=None,
    )
    with pytest.raises(gate.GateError) as error:
        gate.phase_tunnel(ctx)
    assert "--tunnel-visitor" in str(error.value)


# --- #218 round 2 (P3-5..8) ---------------------------------------------------------
class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def _sse(*messages):
    import json as _json

    return "\n".join("data: " + _json.dumps(m) for m in messages) + "\n\n"


def test_mcp_result_treats_a_200_with_a_jsonrpc_error_or_iserror_as_failure():
    """HTTP 200 is not MCP success: a JSON-RPC error, a tool result with
    isError, or no message for the id is a failure the transport wraps in a 200
    (P3-8). A clean result returns."""
    ok = _Resp(200, _sse({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "x"}}))
    assert gate.mcp_result(ok, 1, "initialize") == {"protocolVersion": "x"}

    tool_ok = _Resp(
        200, _sse({"jsonrpc": "2.0", "id": 2, "result": {"content": [], "isError": False}})
    )
    assert gate.mcp_result(tool_ok, 2, "get_meta")["isError"] is False

    for bad, why in [
        (
            _Resp(
                200, _sse({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "no"}})
            ),
            "error",
        ),
        (
            _Resp(
                200, _sse({"jsonrpc": "2.0", "id": 2, "result": {"isError": True, "content": []}})
            ),
            "isError",
        ),
        (_Resp(200, _sse({"jsonrpc": "2.0", "id": 99, "result": {}})), "wrong id"),
        (_Resp(401, ""), "http"),
    ]:
        with pytest.raises(gate.GateError):
            gate.mcp_result(bad, 1 if why != "isError" else 2, "call")


def test_phase_local_branches_on_session_state_not_a_swallowed_ssh_error(monkeypatch, tmp_path):
    """An SSH/Compose failure reading the setup token must surface, not be
    reclassified as 'already claimed' (P3-7). The phase reads /api/auth/session
    first: unclaimed requires setup_token to succeed; claimed loads the saved
    password without calling it."""

    class Sentinel(Exception):
        pass

    def ctx_for(state):
        c = gate.Context(
            base="https://x",
            host=gate.Host("root@h", "/opt/plamotrack"),
            results=gate.Results(),
            state_dir=tmp_path,
            idp=None,
            idp_user="owner",
            idp_password=None,
            hold=5,
            ca_cert=None,
            host_ip=None,
            tunnel_base=None,
            tunnel_proxy=None,
            tunnel_visitor=None,
        )
        monkeypatch.setattr(gate, "session_state", lambda ctx, cred=None: {"state": state})
        return c

    # unclaimed + setup_token raises (an SSH error) → it propagates, not swallowed
    ctx = ctx_for("unclaimed")
    monkeypatch.setattr(
        ctx.host, "setup_token", lambda: (_ for _ in ()).throw(gate.GateError("ssh failed"))
    )
    with pytest.raises(gate.GateError, match="ssh failed"):
        gate.phase_local(ctx)

    # claimed → the saved password is loaded and setup_token is never called
    ctx = ctx_for("owner")
    gate.write_private(str(ctx.state("local-password")), "saved-pw\n")
    called = {"setup": False}
    monkeypatch.setattr(ctx.host, "setup_token", lambda: called.__setitem__("setup", True) or "t")
    monkeypatch.setattr(gate, "run_matrix", lambda c, argv: (_ for _ in ()).throw(Sentinel()))
    with pytest.raises(Sentinel):
        gate.phase_local(ctx)
    assert called["setup"] is False


def test_the_tunnel_runbook_names_every_required_tunnel_argument():
    """A required phase input cannot drift out of the copyable runbook (P3-5):
    the README and the module docstring must name every --tunnel-* / --host-ip
    flag the tunnel phase requires."""
    repo = Path(__file__).resolve().parents[2]
    readme = (repo / ".agents/deployment-gate/README.md").read_text(encoding="utf-8")
    docstring = gate.__doc__ or ""
    for flag in ("--tunnel-base", "--tunnel-proxy", "--host-ip", "--tunnel-visitor"):
        assert flag in readme, f"{flag} missing from the deployment-gate README"
        assert flag in docstring, f"{flag} missing from the deployment_gate docstring"
    # and the systemd drop-in must not offer the wrong `systemctl edit` path (P3-6)
    conf = (repo / "deploy/caddy/caddy.service.d/cloudflare.conf").read_text(encoding="utf-8")
    assert "systemctl edit" not in conf
    assert "sudoedit /etc/caddy/cloudflare.env" in conf

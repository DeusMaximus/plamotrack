"""T10 at uvicorn's real access logger, absent under ASGITransport (#193/#192)."""

import http.client
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("protocol", ["h11", "httptools"])
def test_access_logs_keep_requests_without_oauth_query_credentials(tmp_path, protocol):
    """Both shipped HTTP parsers emit useful access records after app startup,
    but callback/query credentials never enter those records."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    logfile = tmp_path / "uvicorn.log"
    script = (
        "import socket,sys,uvicorn; "
        "sock=socket.socket(fileno=int(sys.argv[1])); "
        "uvicorn.Server(uvicorn.Config('app.main:app', http=sys.argv[2], "
        "proxy_headers=False, workers=1)).run(sockets=[sock])"
    )
    with logfile.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(listener.fileno()), protocol],
            pass_fds=(listener.fileno(),),
            stdout=output,
            stderr=subprocess.STDOUT,
            env={**os.environ, "AUTH_MODE": "local"},
            cwd=Path(__file__).resolve().parents[1],
        )
    listener.close()

    def request(path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    try:
        deadline = time.monotonic() + 20
        while True:
            assert process.poll() is None, logfile.read_text()
            try:
                if request("/healthz") == 200:
                    break
            except OSError:
                pass
            assert time.monotonic() < deadline, logfile.read_text()
            time.sleep(0.05)
        marker = "integration-oauth-access-log-secret"
        paths = ("/healthz", "/auth/oidc/callback", "/mcp/auth/callback")
        for path in paths:
            assert request(path + "?code=" + marker + "&state=" + marker) in {200, 404}
        assert request("/healthz?access_token=" + marker) == 200
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    logged = logfile.read_text()
    for path in paths:
        assert f'"GET {path} HTTP/1.1"' in logged, logged
    assert marker not in logged


@pytest.mark.parametrize(
    "namespace", ["fastmcp.server.auth.late_logger", "mcp.server.auth.late_logger"]
)
@pytest.mark.parametrize("interpolated", [False, True])
def test_auth_library_diagnostics_keep_severity_and_source_without_payloads(
    namespace, interpolated
):
    import io
    import logging

    from app.log_hygiene import install_log_hygiene

    install_log_hygiene()
    # Created AFTER installation: a lazy library import must follow the policy.
    logger = logging.getLogger(namespace)
    logger.disabled = False
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        try:
            raise ValueError("exception-credential-marker")
        except ValueError:
            if interpolated:
                logger.error("already formatted credential-marker", exc_info=True)
            else:
                logger.error("credential: %s", "argument-credential-marker", exc_info=True)
    finally:
        logger.removeHandler(handler)
    rendered = output.getvalue()
    assert namespace + " ERROR " in rendered
    assert "sensitive details omitted" in rendered
    assert "credential-marker" not in rendered
    assert "Traceback" not in rendered

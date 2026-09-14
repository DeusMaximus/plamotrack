"""T12/T13 — the deployment gate, run from a workstation against a prepared host
(design notes §5.4 mode R, §5.8; M6-9, #194).

    uv run python deployment_gate.py --base https://NAME --ssh root@HOST \\
        --idp https://idp.NAME --idp-password-env GATE_IDP_PASSWORD \\
        --phase all [--tunnel-base https://TUNNEL --tunnel-proxy 10.0.0.5
                     --host-ip 10.0.0.9 --tunnel-visitor <your public IP>]

The host is a fresh Linux box prepared by `.agents/deployment-gate/host-prepare.sh`:
Docker and Compose, Caddy with the cloudflare DNS module and the reference
Caddyfile (`deploy/caddy/Caddyfile`) in front of the bundled stack on
`127.0.0.1:8080`, a Keycloak (the #190 spike's) behind the same Caddy as the
identity provider, and this working tree at `--remote-dir`. Every host-side step
runs over `ssh` as the operator would type it — the `.env` edits, `docker compose
up -d`, the documented backup and restore commands verbatim — and every check is
made from outside, through the TLS front. Phases, in the order `all` runs them:

  precheck        four healthy services; versions; the cloudflare module; the host
                  Caddyfile is the reference file with the name filled in; the
                  certificate the name presents.
  lockout         mode R's two lockouts and their recoveries: a name not yet listed
                  is nginx's 421 through the proxy, `ALLOWED_HOSTS` recovers it; a
                  browser write against the https origin is the guard's 403 until
                  `PUBLIC_BASE_URL` names it, after which the dependency's 401 is
                  what an anonymous write earns. Nothing is lost in between.
  local           the ingress matrix (`ingress_matrix.py`) over https in local mode:
                  claim, login, the PAT rows, the legacy stream held on both spellings,
                  a real MCP client's `tools/list`, the T10 log scan.
  modern-hold     the `2026-07-28` twin (#244): with the stack armed
                  (`PLAMOTRACK_ENABLE_TEST_HOLD`, an isolated test instance) a modern
                  `tools/call` SSE is held past the ping interval and aborted on both
                  `/mcp` spellings, and the held database backend must then be gone —
                  server-side cancellation and connection cleanup. The flag is
                  disarmed again afterwards.
  break-glass     `recovery reset-password` and `revoke-sessions` from the host, and
                  what the old and new sessions see (T13's first clause).
  trusted-proxies what nginx records as the client before and after
                  `TRUSTED_PROXIES=127.0.0.1` — the observation the docs' line
                  about a proxy on the same host is written from.
  oidc            switch to OIDC mode, sign in at the provider headlessly, and run
                  the matrix signed in over https in that mode.
  t13             a real MCP client linked through the chain, then the three
                  restores from the two-part backup set (database + `.env`):
                  complete, without the env secrets, without the store.
  tunnel          the same stack reached through a Cloudflare Tunnel whose connector
                  runs on another host: `WEB_BIND` on the LAN address,
                  `TRUSTED_PROXIES` naming the connector, the OIDC login and the
                  matrix through it, the stream held past Cloudflare's 125 s.

Secrets — the owner password the gate sets, the PATs, the session cookie, the MCP
client's tokens, the signing key — live in `--state-dir` as mode-0600 files and are
never printed. The results block (`--results-out`) is the Markdown the release
notes carry; every number in it is observed, none is assumed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import secrets
import shlex
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

import ingress_matrix as matrix
from ingress_matrix import Credential, Row, send, write_private

#: The session cookie names the API sets (backend/app/auth/sessions.py), typed
#: here as literals the way the matrix types its rows: an independent snapshot.
SESSION_COOKIE_NAMES = ("__Host-plamotrack_session", "plamotrack_session")
OIDC_LOGIN_COOKIE_NAMES = ("__Host-plamotrack_oidc_login", "plamotrack_oidc_login")
#: The gate's Keycloak realm (.agents/deployment-gate/keycloak/realm.template.json).
IDP_REALM = "plamotrack"
IDP_CLIENT_ID = "plamotrack"
IDP_CLIENT_SECRET = "plamotrack-gate-secret"  # noqa: S105 — a test fixture's, in the realm file
#: A loopback redirect the proxy admits for a dynamically registered client.
MCP_CLIENT_REDIRECT = "http://localhost:6274/oauth/callback"
INITIALIZE_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "deployment_gate", "version": "0"},
}


class GateError(Exception):
    """A step's precondition or assertion failed; the phase stops here."""


# --- the host, over ssh ------------------------------------------------------------


@dataclass
class Host:
    ssh: str
    remote_dir: str

    def run(
        self,
        command: str,
        *,
        input_text: str | None = None,
        check: bool = True,
        label: str | None = None,
    ) -> str:
        """Run one shell command in the working tree on the host, as the operator
        would; the command is the documented one, not a private helper. `label`
        names the operation in an error instead of the command text, for a step
        whose command must never be echoed (an `.env` edit carrying a secret) —
        the value it sets travels on stdin, never in argv."""
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                self.ssh,
                f"cd {shlex.quote(self.remote_dir)} && {command}",
            ],
            input=input_text,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            what = label or f"`{command}`"
            raise GateError(
                f"on the host, {what} exited {result.returncode}: {result.stderr.strip()[-600:]}"
            )
        return result.stdout

    def compose(self, arguments: str, **kwargs) -> str:
        return self.run(f"docker compose {arguments}", **kwargs)

    def env_set(self, **values: str | None) -> None:
        """Edit `.env` the way the docs say to: one `KEY=value` line per setting,
        a `None` removes the line. Followed by `up()` — changes need `up -d`.

        The value travels on stdin, so a secret setting (POSTGRES_PASSWORD,
        MCP_OAUTH_SIGNING_KEY, OIDC_CLIENT_SECRET) never appears in the SSH
        command line — not in this process's argv, the remote shell's argv, or a
        raised error. Only the key name (validated, never secret) is in the
        command; the error names the operation, not the command."""
        for key, value in values.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise GateError(f"not an .env key: {key!r}")
            command = f"sed -i {shlex.quote(f'/^{key}=/d')} .env"
            if value is not None:
                # printf the key, then cat the value from stdin, then a newline.
                command += f" && {{ printf '%s=' {shlex.quote(key)}; cat; printf '\\n'; }} >> .env"
            self.run(command, input_text=value, label=f"editing .env ({key})")

    def up(self) -> None:
        self.compose("up -d --wait")

    def setup_token(self) -> str:
        """The one-time setup token the API printed at start, read the way the
        docs (and CI) read it — from the container log."""
        pattern = r"s/^[^|]*\|[[:space:]]+([A-Za-z0-9_-]{40,})[[:space:]]*$/\1/p"
        output = self.compose(f"logs --no-color api | sed -nE {shlex.quote(pattern)} | tail -n 1")
        token = output.strip()
        if not token:
            raise GateError("no setup token in the api log (is the instance already claimed?)")
        return token

    def web_last_address(self) -> str:
        """`$remote_addr` of nginx's most recent access record — the address it
        resolved for the client after the TRUSTED_PROXIES walk."""
        output = self.compose("logs --no-color --tail 20 web")
        records = [
            line.split("|", 1)[1].strip()
            for line in output.splitlines()
            if "|" in line and re.match(r"^[^|]*\|\s*\S+ \[", line)
        ]
        if not records:
            raise GateError("no nginx access record in the web log")
        return records[-1].split(" ", 1)[0]

    def peer_address(self) -> str:
        """The address the host sees this workstation as — what the proxy chain
        should resolve a request from here to."""
        output = self.run('printf "%s" "$SSH_CONNECTION"')
        return output.split()[0]

    def psql(self, sql: str) -> list[str]:
        # `-v ON_ERROR_STOP=1` so a SQL error (a statement timeout on an
        # observation query, a dropped connection) exits psql non-zero and
        # raises here, instead of exiting 0 with empty stdout — which every
        # reader would misread as "no rows" (a released backend, a zero count).
        # The boundary refuses to return an error as emptiness, so no caller has
        # to distinguish the two (Codex #250 F7 — the observation-model gap one
        # level up from F2/F6).
        output = self.compose(
            "exec -T db sh -c "
            '\'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA\'',
            input_text=sql,
        )
        return [line for line in output.splitlines() if line.strip()]

    def dump(self, remote_path: str) -> None:
        """docs/operations.md, "Backups": the exact-restore dump."""
        self.compose(
            'exec -T db sh -c \'exec pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"\''
            f" > {shlex.quote(remote_path)}"
        )

    def restore(self, remote_dump: str) -> None:
        """docs/operations.md, "Restoring a dump": the four commands, verbatim, into
        an empty database. `down -v` is what makes it the disaster-recovery path."""
        self.compose("down -v")
        self.compose("up -d db --wait")
        self.compose(
            'exec -T db sh -c \'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
            f" --clean --if-exists' < {shlex.quote(remote_dump)}"
        )
        self.compose("up -d --build --wait")

    def recovery(self, subcommand: str, *, input_text: str | None = None) -> str:
        return self.compose(
            f"exec -T api python -m app.auth.recovery {subcommand}", input_text=input_text
        )


# --- results -----------------------------------------------------------------------


@dataclass
class Results:
    rows: list[tuple[str, str, bool]] = field(default_factory=list)

    @property
    def failures(self) -> int:
        return sum(1 for _, _, ok in self.rows if not ok)

    def record(self, step: str, result: str, ok: bool = True) -> None:
        self.rows.append((step, result, ok))
        print(f"{'ok  ' if ok else 'FAIL'} {step:34} {result}")

    def markdown(self, header: list[str]) -> str:
        lines = [*header, "", "| Step | Result |", "| --- | --- |"]
        for step, result, ok in self.rows:
            mark = "" if ok else " **FAIL**"
            lines.append(f"| {step}{mark} | {result.replace('|', '\\|')} |")
        return "\n".join(lines) + "\n"


# --- the workstation side ----------------------------------------------------------


@dataclass
class Context:
    base: str
    host: Host
    results: Results
    state_dir: pathlib.Path
    idp: str | None
    idp_user: str
    idp_password: str | None
    hold: int
    ca_cert: str | None
    host_ip: str | None
    tunnel_base: str | None
    tunnel_proxy: str | None
    tunnel_visitor: str | None

    @property
    def name(self) -> str:
        return urlsplit(self.base).hostname or ""

    def state(self, filename: str) -> pathlib.Path:
        return self.state_dir / filename

    def save(self, filename: str, content: str) -> pathlib.Path:
        return write_private(str(self.state(filename)), content)

    def load(self, filename: str) -> str:
        path = self.state(filename)
        if not path.exists():
            raise GateError(f"{path} is missing — run the phase that writes it first")
        return path.read_text(encoding="utf-8").rstrip("\n")

    def http(self) -> httpx.Client:
        return httpx.Client(
            follow_redirects=False, timeout=60, verify=self.ca_cert if self.ca_cert else True
        )


def get(ctx: Context, path: str, *, base: str | None = None, **kwargs) -> matrix.Response:
    return send(base or ctx.base, Row("gate", "GET", path, 0, **kwargs))


def post(ctx: Context, path: str, *, base: str | None = None, **kwargs) -> matrix.Response:
    return send(base or ctx.base, Row("gate", "POST", path, 0, **kwargs))


def expect(ctx: Context, step: str, resp: matrix.Response, status: int, code: str | None = None):
    detail = f"{status}" + (f" {code}" if code else "")
    got = f"{resp.status}"
    body_code = None
    with contextlib.suppress(ValueError, AttributeError):
        body_code = resp.json().get("code")
    if body_code:
        got += f" {body_code}"
    ok = resp.status == status and (code is None or body_code == code)
    ctx.results.record(step, got if ok else f"{got}, expected {detail}", ok)
    if not ok:
        raise GateError(f"{step}: {got}, expected {detail}")


def session_state(ctx: Context, credential: Credential | None, *, base: str | None = None) -> dict:
    headers = credential.read() if credential is not None else {}
    resp = get(ctx, "/api/auth/session", base=base, headers=headers)
    if resp.status != 200:
        raise GateError(f"GET /api/auth/session answered {resp.status}")
    return resp.json()


def sign_in_when_allowed(base: str, password: str, *, wait: float = 150.0) -> Credential:
    """`matrix.sign_in`, retried while nginx's login limiter (family 3, 5 r/min)
    is still refusing this address — the matrix ends with a deliberate burst."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return matrix.sign_in(base, setup_token=None, password=password)
        except SystemExit as refused:
            if " 429" not in str(refused) or time.monotonic() > deadline:
                raise
            time.sleep(15)


def run_matrix(ctx: Context, argv: list[str]) -> tuple[int, int, int]:
    """The ingress matrix in-process; returns (failing checks, ok rows, skipped)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        failures = matrix.main(argv)
    output = buffer.getvalue()
    sys.stdout.write(output)
    lines = output.splitlines()
    for line in lines:  # the held streams are results of their own
        match = re.match(r"^(ok |FAIL) HOLD\s+(\S+)\s+(.*)$", line)
        if match:
            ctx.results.record(f"hold {match.group(2)}", match.group(3), match.group(1) == "ok ")
    ok_rows = sum(1 for line in lines if line.startswith("ok ") and " HOLD " not in line)
    skipped = sum(1 for line in lines if line.startswith("skip"))
    return failures, ok_rows, skipped


def scan_logs(ctx: Context, secret_files: list[pathlib.Path]) -> None:
    """T10 as CI runs it: both access logs must have spoken, and no value the run
    put in a header, body or query may appear in either."""
    logs = ctx.host.compose("logs --no-color api web")
    lines = logs.splitlines()
    if not any('"GET /healthz HTTP/1.1" 200' in line and "api" in line for line in lines):
        raise GateError("no uvicorn access record from the api service")
    if not any('"GET /api/healthz HTTP/1.1" 200' in line and "web" in line for line in lines):
        raise GateError("no nginx access record from the web service")
    checked = 0
    for path in secret_files:
        for kind, value in json.loads(path.read_text(encoding="utf-8")).items():
            checked += 1
            if value and value in logs:
                raise GateError(f"the {kind} from {path.name} appears in a container log")
    ctx.results.record(
        "T10 log scan", f"api and web access records seen; {checked} run values absent"
    )


# --- phases ------------------------------------------------------------------------


def normalised_caddyfile(text: str) -> str:
    """Comments out, whitespace collapsed: what the precheck compares."""
    lines = [line.split("#", 1)[0] for line in text.splitlines()]
    return " ".join(" ".join(lines).split())


def phase_precheck(ctx: Context) -> None:
    host = ctx.host
    output = host.compose("ps -a --format json")
    try:
        parsed = json.loads(output)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:  # one JSON object per line
        rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    services = {
        row["Service"]: (row.get("State"), row.get("Health"), row.get("ExitCode")) for row in rows
    }
    for name in ("api", "web", "db"):
        state, health, _ = services.get(name, (None, None, None))
        if state != "running" or health not in ("healthy", ""):
            raise GateError(f"service {name}: {services.get(name)}")
    if services.get("migrate", (None, None, None))[2] != 0:
        raise GateError(f"migrate: {services.get('migrate')}")
    ctx.results.record("services", "api, web, db healthy; migrate Exited (0)")

    versions = host.run(
        "docker --version; docker compose version --short; caddy version; "
        "caddy list-modules | grep '^dns.providers.cloudflare$' || echo NO-CLOUDFLARE-MODULE"
    ).splitlines()
    if "NO-CLOUDFLARE-MODULE" in versions:
        raise GateError("caddy lacks dns.providers.cloudflare")
    virt = host.run('systemd-detect-virt || true; . /etc/os-release && echo "$PRETTY_NAME"')
    ctx.results.record("host", "; ".join(v.strip() for v in virt.splitlines() if v.strip()))
    ctx.results.record("versions", "; ".join(v.strip() for v in versions[:3]))

    reference = (pathlib.Path(__file__).resolve().parents[1] / "deploy/caddy/Caddyfile").read_text(
        encoding="utf-8"
    )
    rendered = normalised_caddyfile(reference.replace("plamotrack.example", ctx.name))
    on_host = normalised_caddyfile(host.run("cat /etc/caddy/Caddyfile"))
    if rendered not in on_host:
        raise GateError("the host's /etc/caddy/Caddyfile does not contain the reference site block")
    ctx.results.record("Caddyfile", "the host runs deploy/caddy/Caddyfile (name filled in)")

    context = ssl.create_default_context(cafile=ctx.ca_cert or None)
    with socket.create_connection((ctx.name, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=ctx.name) as tls:
            cert = tls.getpeercert()
            issuer = dict(item for pair in cert.get("issuer", ()) for item in pair)
            ctx.results.record(
                "TLS",
                f"{tls.version()}, {tls.cipher()[0]}; issuer {issuer.get('organizationName')}"
                f" / {issuer.get('commonName')}; notAfter {cert.get('notAfter')}",
            )


def phase_lockout(ctx: Context) -> None:
    """Mode R's two lockouts, each recovered by the line the docs name."""
    host = ctx.host
    host.env_set(PUBLIC_BASE_URL=None, ALLOWED_HOSTS=None)
    host.up()
    expect(
        ctx, "lockout: name not listed", get(ctx, "/api/healthz"), 421, "ingress.host_not_allowed"
    )
    resp = get(ctx, "/api/healthz")
    if resp.json().get("params", {}).get("setting") != "ALLOWED_HOSTS":
        raise GateError("the 421 envelope does not name ALLOWED_HOSTS")
    host.env_set(ALLOWED_HOSTS=ctx.name)
    host.up()
    expect(ctx, "recovery: ALLOWED_HOSTS", get(ctx, "/api/healthz"), 200)
    body = b'{"name":"Deployment Gate"}'
    json_type = {"Content-Type": "application/json", "Origin": ctx.base}
    expect(
        ctx,
        "lockout: https Origin on a write",
        post(ctx, "/api/retailers", headers=json_type, body=body),
        403,
        "ingress.origin_not_allowed",
    )
    host.env_set(PUBLIC_BASE_URL=ctx.base, ALLOWED_HOSTS=None)
    host.up()
    expect(
        ctx,
        "recovery: PUBLIC_BASE_URL",
        post(ctx, "/api/retailers", headers=json_type, body=body),
        401,
        "auth.unauthenticated",
    )
    state = session_state(ctx, None)["state"]
    ctx.results.record("nothing lost", f"session state {state} throughout", state == "unclaimed")


def phase_local(ctx: Context) -> None:
    host = ctx.host
    # Branch on the instance's own claim state, read first — never on whether a
    # host command happened to fail (Codex #218 P3-7): an SSH/Compose error while
    # reading the setup token must surface, not be misread as "already claimed".
    state = session_state(ctx, None)["state"]
    if state == "unclaimed":
        token: str | None = host.setup_token()  # must succeed; a host error propagates
        password = secrets.token_urlsafe(18)
        ctx.save("local-password", password + "\n")
        ctx.results.record("local: claim", "was unclaimed; setup token read, claiming")
    else:
        token = None
        password = ctx.load("local-password")
        ctx.results.record("local: claim", f"already claimed (session {state}); saved password")
    pat = ctx.state("pat-local")
    log_secrets = ctx.state("log-secrets-local.json")
    failures, ok_rows, skipped = run_matrix(
        ctx,
        [
            ctx.base,
            *([f"--setup-token={token}"] if token is not None else []),
            "--password",
            password,
            f"--token-out={pat}",
            f"--log-secrets-out={log_secrets}",
            "--behind-proxy",
            "--hold-stream",
            str(ctx.hold),
            *(["--ca-cert", ctx.ca_cert] if ctx.ca_cert else []),
        ],
    )
    ctx.results.record(
        "matrix (local, https, --behind-proxy)",
        f"{failures} failing / {ok_rows} ok rows, {skipped} skipped"
        " (hostile Host: the proxy answers)",
        failures == 0,
    )
    if failures:
        raise GateError("the local-mode matrix has failing rows")

    from fastmcp import Client  # noqa: PLC0415 — the backend's dependency, loaded on use

    async def list_tools(token_value: str) -> list[str]:
        async with Client(f"{ctx.base}/mcp/", auth=token_value) as client:
            return sorted(tool.name for tool in await client.list_tools())

    tools = asyncio.run(list_tools(pat.read_text(encoding="utf-8").strip()))
    ctx.results.record(
        "MCP client tools/list", f"{len(tools)} tools, list_kits present", "list_kits" in tools
    )
    expect(ctx, "/api/readyz from outside", get(ctx, "/api/readyz"), 404)
    scan_logs(ctx, [log_secrets])


#: The marker `app.mcp_hold_probe` leaves on the held connection's last
#: statement — typed here as a literal, an independent snapshot like the cookie
#: names above, so the gate finds exactly that backend in pg_stat_activity.
HOLD_PROBE_MARKER = "plamotrack_hold_probe"


def _held_backends(ctx: Context) -> int:
    rows = ctx.host.psql(
        "select count(*) from pg_stat_activity where query like "
        f"'%{HOLD_PROBE_MARKER}%' and pid <> pg_backend_pid();"
    )
    return int(rows[0]) if rows else 0


def _held_pids(ctx: Context) -> set[str]:
    """The backend PIDs currently holding the probe's transaction (idle in
    transaction under the marker) — the actual live backends, so 'gone after
    abort' is asserted against the same PIDs seen during the hold, not a mere
    count that was zero before and after (Codex #250 F2)."""
    rows = ctx.host.psql(
        "select pid from pg_stat_activity where query like "
        f"'%{HOLD_PROBE_MARKER}%' and state = 'idle in transaction' "
        "and pid <> pg_backend_pid();"
    )
    return {row.strip() for row in rows if row.strip()}


def _backends_released(during: set[str], poll, *, tries: int = 60, pause: float = 0.5) -> bool:
    """Positive confirmation that none of the `during` PIDs remain after the
    abort — polled up to `tries` times. A backend that lingers through every
    poll (or a partial set where one PID stays) is never read as released; the
    verdict is not defaulted to success (Codex #250 F6 — the same class as F2:
    the cleanup must be confirmed, never assumed)."""
    for _ in range(tries):
        if not (during & poll()):
            return True
        time.sleep(pause)
    return False


def phase_modern_hold(ctx: Context) -> None:
    """T12's modern twin (#244): the `2026-07-28` era through the proxy chain on
    both `/mcp` spellings. The era has no standalone stream and no long tool, so
    the stack is armed with `PLAMOTRACK_ENABLE_TEST_HOLD` (isolated test
    instance) to make `get_meta` hold a database connection; the client holds
    the modern SSE past the ping interval, aborts by closing the socket, and a
    backend that was **observed live during the hold** must then be gone —
    server-side cancellation and connection cleanup, not a count that read zero
    both before and after (Codex #250 F2). The arming, the holds and the
    disarm are one protected scope so a startup failure cannot leave the flag
    armed (Codex #250 F3); the disarm runs whatever happened, and a disarm
    failure does not mask the original error."""
    import threading  # noqa: PLC0415

    from ingress_matrix import Bearer, hold_stream_modern  # noqa: PLC0415

    host = ctx.host
    pat = ctx.load("pat-local")
    bearer = Bearer(raw=pat, token_id="")
    hold = max(ctx.hold, 20)
    if _held_backends(ctx) != 0:
        raise GateError("a hold-probe backend is already present before arming")
    body_error: BaseException | None = None
    try:
        host.env_set(PLAMOTRACK_ENABLE_TEST_HOLD=str(hold + 60))
        host.up()
        for path in ("/mcp/", "/mcp"):
            outcome: dict = {}

            def run(path: str = path, outcome: dict = outcome) -> None:
                outcome["ok"], outcome["message"] = hold_stream_modern(ctx.base, bearer, path, hold)

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            during: set[str] = set()
            deadline = time.monotonic() + hold
            while worker.is_alive() and time.monotonic() < deadline:
                during = _held_pids(ctx)
                if during:
                    break
                time.sleep(1)
            worker.join(timeout=hold + 90)
            ok = outcome.get("ok", False)
            released = bool(during) and _backends_released(during, lambda: _held_pids(ctx))
            held_ok = ok and released
            ctx.results.record(
                f"modern hold {path}",
                f"{outcome.get('message', '(no result)')}; backend pid(s) "
                f"{sorted(during) or 'NONE'} held during, "
                f"{'gone' if released else 'LINGERING/absent'} after abort",
                held_ok,
            )
            if not held_ok:
                raise GateError(f"modern hold on {path} failed")
    except BaseException as error:
        body_error = error
        raise
    finally:
        try:
            host.env_set(PLAMOTRACK_ENABLE_TEST_HOLD=None)
            host.up()
        except Exception as cleanup_error:  # noqa: BLE001
            if body_error is None:
                raise
            ctx.results.record(
                "modern-hold: disarm after failure",
                f"the probe flag disarm also failed: {cleanup_error}",
                ok=False,
            )


def phase_break_glass(ctx: Context) -> None:
    """T13's first clause: the host-side reset revokes sessions and restores
    access; the old session is anonymous, the new password signs in. Its own
    phase because the matrix leaves this address throttled on the login family
    for up to a minute."""
    host = ctx.host
    password = ctx.load("local-password")
    old = sign_in_when_allowed(ctx.base, password)
    new_password = secrets.token_urlsafe(18)
    host.recovery("reset-password --password-stdin", input_text=new_password + "\n")
    ctx.save("local-password", new_password + "\n")
    state = session_state(ctx, old)["state"]
    ctx.results.record(
        "break-glass: reset-password", f"old session now {state}", state == "anonymous"
    )
    fresh = sign_in_when_allowed(ctx.base, new_password)
    host.recovery("revoke-sessions")
    state = session_state(ctx, fresh)["state"]
    ctx.results.record(
        "break-glass: revoke-sessions", f"new session now {state}", state == "anonymous"
    )


def phase_trusted_proxies(ctx: Context) -> None:
    host = ctx.host
    expected = host.peer_address()
    host.env_set(TRUSTED_PROXIES=None)
    host.up()
    get(ctx, "/api/healthz")
    before = host.web_last_address()
    host.env_set(TRUSTED_PROXIES="127.0.0.1")
    host.up()
    get(ctx, "/api/healthz")
    after = host.web_last_address()
    ok = after == expected and before != expected
    ctx.results.record(
        "TRUSTED_PROXIES=127.0.0.1",
        f"nginx $remote_addr before: {before}; after: {after}; this workstation: {expected}",
        ok,
    )
    if not ok:
        raise GateError("the gateway rule did not resolve the visitor")
    password = ctx.load("local-password")
    credential = sign_in_when_allowed(ctx.base, password)
    rows = host.psql(
        "select client_address from audit_event where event_type = 'auth.login_succeeded'"
        " order by occurred_at desc limit 1;"
    )
    recorded = rows[0] if rows else ""
    ctx.results.record("audit client_address", recorded, recorded == expected)
    matrix.sign_out(ctx.base, credential)


class KeycloakForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")
        if tag == "input" and attributes.get("name") and attributes.get("type") == "hidden":
            self.fields[attributes["name"]] = attributes.get("value", "")


def idp_sign_in(ctx: Context, authorization_url: str) -> str:
    """Drive Keycloak's login form as a browser would; returns the redirect back."""
    if ctx.idp_password is None:
        raise GateError("--idp-password-env names no password")
    with httpx.Client(follow_redirects=True, timeout=60, verify=ctx.ca_cert or True) as idp:
        page = idp.get(authorization_url)
        form = KeycloakForm()
        form.feed(page.text)
        if not form.action:
            raise GateError(f"no Keycloak login form at the provider ({page.status_code})")
        answer = idp.post(
            form.action,
            data={
                "username": ctx.idp_user,
                "password": ctx.idp_password,
                "credentialId": "",
                **form.fields,
            },
            follow_redirects=False,
        )
    if answer.status_code != 302:
        raise GateError(f"the provider's login answered {answer.status_code}")
    return answer.headers["location"]


def oidc_login(ctx: Context, setup_token: str | None, *, base: str | None = None) -> Credential:
    """The browser OIDC login headlessly: start (the setup token in the body while
    unbound), the provider's form, the callback with the login-binding cookie,
    then the session cookie and CSRF token from `/api/auth/session`."""
    base = base or ctx.base
    with ctx.http() as browser:
        payload = {"setup_token": setup_token} if setup_token else {}
        started = browser.post(
            f"{base}/api/auth/oidc/start", json=payload, headers={"Origin": base}
        )
        if started.status_code != 200:
            raise GateError(f"oidc/start answered {started.status_code}: {started.text[:200]}")
        if not any(name in browser.cookies for name in OIDC_LOGIN_COOKIE_NAMES):
            raise GateError("oidc/start set no login-binding cookie")
        callback = idp_sign_in(ctx, started.json()["authorization_url"])
        if not callback.startswith(f"{base}/api/auth/oidc/callback?"):
            raise GateError(f"the provider redirected elsewhere: {callback[:120]}")
        landed = browser.get(callback)
        if landed.status_code != 302 or "auth_error" in landed.headers.get("location", ""):
            raise GateError(
                f"oidc/callback answered {landed.status_code} {landed.headers.get('location')}"
            )
        cookie = next(
            (
                f"{name}={browser.cookies[name]}"
                for name in SESSION_COOKIE_NAMES
                if name in browser.cookies
            ),
            None,
        )
        if cookie is None:
            raise GateError("the callback set no session cookie")
        session = browser.get(f"{base}/api/auth/session").json()
    if session.get("state") != "owner":
        raise GateError(f"after the provider login the session is {session.get('state')!r}")
    return Credential(cookie=cookie, csrf_token=session["csrf_token"])


def save_credential(ctx: Context, filename: str, credential: Credential) -> pathlib.Path:
    return ctx.save(
        filename,
        json.dumps({"cookie": credential.cookie, "csrf_token": credential.csrf_token}) + "\n",
    )


def load_credential(ctx: Context, filename: str) -> Credential:
    data = json.loads(ctx.load(filename))
    return Credential(cookie=data["cookie"], csrf_token=data["csrf_token"])


def phase_oidc(ctx: Context) -> None:
    if ctx.idp is None:
        raise GateError("--idp is required for the oidc phase")
    host = ctx.host
    # A re-run keeps the key: rotating it is T13's business, not this phase's.
    existing = ctx.state("signing-key")
    signing_key = existing.read_text(encoding="utf-8").strip() if existing.exists() else ""
    signing_key = signing_key or secrets.token_hex(32)
    ctx.save("signing-key", signing_key + "\n")
    host.env_set(
        AUTH_MODE="oidc",
        OIDC_ISSUER=f"{ctx.idp}/realms/{IDP_REALM}",
        OIDC_CLIENT_ID=IDP_CLIENT_ID,
        OIDC_CLIENT_SECRET=IDP_CLIENT_SECRET,
        MCP_OAUTH_SIGNING_KEY=signing_key,
        PUBLIC_BASE_URL=ctx.base,
    )
    host.up()
    # Unbound (the first start in this mode) needs the setup token; a re-run
    # against a bound owner signs in without one.
    unbound = session_state(ctx, None)["state"] == "unclaimed"
    credential = oidc_login(ctx, host.setup_token() if unbound else None)
    credential_file = save_credential(ctx, "credential-oidc.json", credential)
    ctx.results.record(
        "OIDC login through the proxy",
        ("setup token + " if unbound else "") + "provider sign-in → owner session",
    )
    pat = ctx.state("pat-oidc")
    log_secrets = ctx.state("log-secrets-oidc.json")
    failures, ok_rows, skipped = run_matrix(
        ctx,
        [
            ctx.base,
            "--mode",
            "oidc",
            "--public-base-url",
            ctx.base,
            f"--credential-file={credential_file}",
            f"--token-out={pat}",
            f"--log-secrets-out={log_secrets}",
            "--behind-proxy",
            "--hold-stream",
            str(ctx.hold),
            *(["--ca-cert", ctx.ca_cert] if ctx.ca_cert else []),
        ],
    )
    ctx.results.record(
        "matrix (oidc, https, signed in)",
        f"{failures} failing / {ok_rows} ok rows, {skipped} skipped",
        failures == 0,
    )
    if failures:
        raise GateError("the OIDC-mode matrix has failing rows")
    scan_logs(ctx, [log_secrets, ctx.state("log-secrets-local.json")])


# --- T13: a real MCP client, then the three restores --------------------------------


def mcp_post(
    client: httpx.Client, base: str, token: str, method: str, params=None, *, id_=1, session=None
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    body: dict = {"jsonrpc": "2.0", "method": method}
    if not method.startswith("notifications/"):
        body["id"] = id_
    if params is not None:
        body["params"] = params
    return client.post(f"{base}/mcp/", json=body, headers=headers)


def mcp_initialize(client: httpx.Client, base: str, token: str) -> httpx.Response:
    return mcp_post(client, base, token, "initialize", INITIALIZE_PARAMS)


def sse_json(text: str) -> list[dict]:
    """The JSON-RPC messages in a streamable-HTTP (SSE) body — the shape
    tests/test_auth_tokens.py drives by hand."""
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


def mcp_result(response: httpx.Response, request_id: int, what: str) -> dict:
    """The JSON-RPC *result* for `request_id` — HTTP 200 is not success. A
    JSON-RPC `error`, a missing message, or a tool result with `isError: true`
    (a 200 carrying a failed tool call) is a failure the transport wraps in a 200
    (Codex #218 P3-8). Raises GateError otherwise; returns the result."""
    if response.status_code != 200:
        raise GateError(f"{what} answered HTTP {response.status_code}")
    messages = [m for m in sse_json(response.text) if m.get("id") == request_id]
    if not messages:
        raise GateError(
            f"{what}: no JSON-RPC message for id {request_id} in {response.text[:200]!r}"
        )
    message = messages[-1]
    if message.get("error"):
        raise GateError(f"{what}: JSON-RPC error {message['error']}")
    result = message.get("result")
    if result is None:
        raise GateError(f"{what}: a JSON-RPC message with neither result nor error")
    if isinstance(result, dict) and result.get("isError"):
        raise GateError(f"{what}: the tool call returned isError=true: {result}")
    return result


def mcp_link(ctx: Context) -> dict:
    """A dynamically registered client through the whole chain: discovery, DCR,
    authorize, consent, the provider's login, callback, token, initialize, a tool
    call, refresh. Returns what a client keeps."""
    base = ctx.base
    with ctx.http() as client:
        resource = client.get(f"{base}/.well-known/oauth-protected-resource/mcp/").json()
        server = client.get(f"{base}/.well-known/oauth-authorization-server/mcp").json()
        if resource.get("resource") != f"{base}/mcp/" or server.get("issuer") != f"{base}/mcp":
            raise GateError(f"discovery names another instance: {resource} {server}")
        registered = client.post(
            server["registration_endpoint"],
            json={
                "client_name": "deployment gate",
                "redirect_uris": [MCP_CLIENT_REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        if registered.status_code != 201:
            raise GateError(
                f"/mcp/register answered {registered.status_code}: {registered.text[:200]}"
            )
        client_id = registered.json()["client_id"]
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(16)
        authorize = client.get(
            server["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": MCP_CLIENT_REDIRECT,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": state,
                    "scope": "openid",
                    "resource": f"{base}/mcp/",
                }
            )
        )
        consent_location = authorize.headers.get("location", "")
        if authorize.status_code != 302 or "/mcp/consent" not in consent_location:
            raise GateError(f"/mcp/authorize answered {authorize.status_code}")
        consent_url = authorize.headers["location"]
        page = client.get(consent_url)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        if not csrf:
            raise GateError("no csrf_token on the consent page")
        txn = parse_qs(urlsplit(consent_url).query)["txn_id"][0]
        approved = client.post(
            f"{base}/mcp/consent",
            data={"txn_id": txn, "csrf_token": csrf.group(1), "action": "approve"},
        )
        if approved.status_code != 302:
            raise GateError(f"/mcp/consent answered {approved.status_code}: {approved.text[:200]}")
        callback = idp_sign_in(ctx, approved.headers["location"])
        if not callback.startswith(f"{base}/mcp/auth/callback?"):
            raise GateError(f"the provider redirected elsewhere: {callback[:120]}")
        returned = client.get(callback)
        if returned.status_code != 302 or not returned.headers.get("location", "").startswith(
            MCP_CLIENT_REDIRECT
        ):
            raise GateError(f"/mcp/auth/callback answered {returned.status_code}")
        query = parse_qs(urlsplit(returned.headers["location"]).query)
        if query["state"][0] != state:
            raise GateError("the client's state did not come back")
        tokens = client.post(
            server["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "redirect_uri": MCP_CLIENT_REDIRECT,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": f"{base}/mcp/",
            },
        )
        if tokens.status_code != 200:
            raise GateError(f"/mcp/token answered {tokens.status_code}: {tokens.text[:200]}")
        issued = tokens.json()
        opened = mcp_initialize(client, base, issued["access_token"])
        mcp_result(opened, 1, "initialize with the issued token")
        session = opened.headers.get("mcp-session-id")
        ack = mcp_post(
            client, base, issued["access_token"], "notifications/initialized", session=session
        )
        if ack.status_code != 202:
            raise GateError(f"notifications/initialized answered {ack.status_code}")
        called = mcp_post(
            client,
            base,
            issued["access_token"],
            "tools/call",
            {"name": "get_meta", "arguments": {}},
            id_=2,
            session=session,
        )
        mcp_result(called, 2, "tools/call get_meta")
        refreshed = client.post(
            server["token_endpoint"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "client_id": client_id,
            },
        )
        if refreshed.status_code != 200:
            raise GateError(f"the first refresh answered {refreshed.status_code}")
        current = refreshed.json()
    return {
        "client_id": client_id,
        "refresh_token": current["refresh_token"],
        "access_token": current["access_token"],
        "token_endpoint": server["token_endpoint"],
    }


def mcp_verify(ctx: Context, link: dict) -> dict:
    """What an existing client sees after a restore: its refresh, its old access
    token, and (when the refresh succeeded) its new access token."""
    out: dict = {}
    with ctx.http() as client:
        refreshed = client.post(
            link["token_endpoint"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": link["refresh_token"],
                "client_id": link["client_id"],
            },
        )
        out["refresh_status"] = refreshed.status_code
        if refreshed.status_code != 200:
            with contextlib.suppress(ValueError):
                out["refresh_error"] = refreshed.json().get("error")
        old = mcp_initialize(client, ctx.base, link["access_token"])
        out["old_access_initialize"] = old.status_code
        if refreshed.status_code == 200:
            fresh = refreshed.json()
            new = mcp_initialize(client, ctx.base, fresh["access_token"])
            # The refreshed token must complete a real initialize, not just 200
            # (Codex #218 P3-8) — a protocol failure here raises, not passes.
            mcp_result(new, 1, "initialize with the refreshed token")
            out["new_access_initialize"] = new.status_code
            link.update(refresh_token=fresh["refresh_token"], access_token=fresh["access_token"])
    return out


def t13_counters(ctx: Context) -> dict[str, int]:
    host = ctx.host
    web = host.compose("logs --no-color web")
    return {
        "registrations": sum(
            1 for line in web.splitlines() if '"POST /mcp/register HTTP/1.1" 201' in line
        ),
        "grants": int(
            host.psql(
                "select count(*) from audit_event where event_type = 'auth.mcp_grant_issued';"
            )[0]
        ),
        "clients": int(
            host.psql(
                "select count(*) from mcp_oauth_state where collection = 'mcp-oauth-proxy-clients';"
            )[0]
        ),
    }


def describe(checks: dict) -> str:
    data = "intact" if checks["data"] else "MISSING"
    return f"session {checks['session']}, PAT {checks['pat']}, data {data},"


def t13_partial_restore_ok(checks: dict, seen: dict) -> bool:
    """What a restore that dropped a secret or the store must show: the data,
    session and PAT intact, the old MCP access token refused, and the client's
    refresh refused as **invalid_client** specifically — the class §5.6 names,
    the one that tells a client to re-register rather than retry (a different 401,
    e.g. invalid_grant, would be a different contract). The relink is checked by
    the caller."""
    return (
        checks["session"] == "owner"
        and checks["pat"] == 200
        and checks["data"]
        and seen["refresh_status"] == 401
        and seen.get("refresh_error") == "invalid_client"
        and seen["old_access_initialize"] == 401
    )


def t13_checks(ctx: Context, label: str, credential: Credential, pat: str) -> dict:
    """The public behaviour every restore is judged by."""
    out = {"session": session_state(ctx, credential)["state"]}
    out["pat"] = get(ctx, "/api/kits", headers={"Authorization": f"Bearer {pat}"}).status
    retailers = get(ctx, "/api/retailers", headers=credential.read())
    names = [row["name"] for row in retailers.json()] if retailers.status == 200 else []
    out["data"] = "Deployment Gate" in names
    return out


def phase_t13(ctx: Context) -> None:
    host = ctx.host
    credential = load_credential(ctx, "credential-oidc.json")
    pat = ctx.load("pat-oidc")
    # Data the restores must bring back: one retailer, written before dump A.
    created = post(
        ctx,
        "/api/retailers",
        headers={**credential.write(ctx.base), "Content-Type": "application/json"},
        body=b'{"name":"Deployment Gate"}',
    )
    if created.status not in (201, 409):
        raise GateError(f"creating the marker retailer answered {created.status}")
    host.dump("/root/gate-dump-A.dump")
    host.run("cp .env /root/gate-env-A")
    before = t13_counters(ctx)
    link = mcp_link(ctx)
    ctx.save("mcp-link.json", json.dumps(link) + "\n")
    after = t13_counters(ctx)
    ctx.results.record(
        "T13 link",
        f"DCR + provider login + token + initialize + get_meta + refresh;"
        f" registrations {before['registrations']}→{after['registrations']},"
        f" grants {before['grants']}→{after['grants']},"
        f" client rows {before['clients']}→{after['clients']}",
        after["registrations"] == before["registrations"] + 1
        and after["grants"] == before["grants"] + 1,
    )
    host.dump("/root/gate-dump-B.dump")
    host.run("cp .env /root/gate-env-B")
    linked = t13_counters(ctx)

    # 1. The complete set: dump B and the same .env.
    host.restore("/root/gate-dump-B.dump")
    checks = t13_checks(ctx, "complete", credential, pat)
    seen = mcp_verify(ctx, link)
    now = t13_counters(ctx)
    ok = (
        checks["session"] == "owner"
        and checks["pat"] == 200
        and checks["data"]
        and seen["refresh_status"] == 200
        and seen.get("new_access_initialize") == 200
        and now["registrations"] == 0
        and now["grants"] == linked["grants"]
        and now["clients"] == linked["clients"]
    )
    ctx.results.record(
        "T13 restore: complete set",
        describe(checks)
        + f" refresh {seen['refresh_status']}, initialize {seen.get('new_access_initialize')},"
        f" registrations after restore {now['registrations']}, grants {now['grants']}",
        ok,
    )
    ctx.save("mcp-link.json", json.dumps(link) + "\n")

    # 2. Without the env secrets: dump B, a regenerated .env (new database
    #    password, new signing key; the names and the provider client unchanged).
    host.env_set(
        POSTGRES_PASSWORD=secrets.token_hex(16), MCP_OAUTH_SIGNING_KEY=secrets.token_hex(32)
    )
    host.restore("/root/gate-dump-B.dump")
    checks = t13_checks(ctx, "without env", credential, pat)
    seen = mcp_verify(ctx, link)
    relinked = mcp_link(ctx)
    ok = t13_partial_restore_ok(checks, seen)
    ctx.results.record(
        "T13 restore: without the env secrets",
        describe(checks)
        + f" old access {seen['old_access_initialize']}, refresh {seen['refresh_status']}"
        f" {seen.get('refresh_error', '')}, relink ok",
        ok,
    )
    link = relinked

    # 3. Without the store: dump A (before the link) with the original .env.
    host.run("cp /root/gate-env-A .env")
    host.restore("/root/gate-dump-A.dump")
    checks = t13_checks(ctx, "without store", credential, pat)
    seen = mcp_verify(ctx, link)
    relinked = mcp_link(ctx)
    ok = t13_partial_restore_ok(checks, seen)
    ctx.results.record(
        "T13 restore: without the store",
        describe(checks)
        + f" old access {seen['old_access_initialize']}, refresh {seen['refresh_status']}"
        f" {seen.get('refresh_error', '')}, relink ok",
        ok,
    )
    ctx.save("mcp-link.json", json.dumps(relinked) + "\n")


def phase_tunnel(ctx: Context) -> None:
    if not (ctx.tunnel_base and ctx.tunnel_proxy and ctx.host_ip and ctx.tunnel_visitor):
        raise GateError(
            "the tunnel phase needs --tunnel-base, --tunnel-proxy, --host-ip and "
            "--tunnel-visitor (this workstation's public address as Cloudflare sees it: "
            "`curl -s https://cloudflare.com/cdn-cgi/trace | sed -n s/^ip=//p`)"
        )
    host = ctx.host
    tunnel = ctx.tunnel_base
    host.env_set(
        WEB_BIND=ctx.host_ip, PUBLIC_BASE_URL=tunnel, ALLOWED_HOSTS=None, TRUSTED_PROXIES=None
    )
    host.up()
    expect(ctx, "tunnel: reachable", get(ctx, "/api/healthz", base=tunnel), 200)
    before = host.web_last_address()
    host.env_set(TRUSTED_PROXIES=ctx.tunnel_proxy)
    host.up()
    get(ctx, "/api/healthz", base=tunnel)
    after = host.web_last_address()
    # Not "changed" — an edge address, a wrong hop or a gateway would also change.
    # nginx must resolve exactly this workstation's independently-known public
    # address, and only after the connector is trusted (before it, the connector).
    ok = before == ctx.tunnel_proxy and after == ctx.tunnel_visitor
    ctx.results.record(
        f"tunnel: TRUSTED_PROXIES={ctx.tunnel_proxy}",
        f"nginx $remote_addr before: {before}; after: {after};"
        f" expected the visitor {ctx.tunnel_visitor}",
        ok,
    )
    if not ok:
        raise GateError("the tunnel did not resolve to the expected visitor address")
    credential = oidc_login(ctx, None, base=tunnel)
    credential_file = save_credential(ctx, "credential-tunnel.json", credential)
    ctx.results.record("tunnel: OIDC login", "provider sign-in on the tunnel name → owner session")
    pat = ctx.state("pat-tunnel")
    log_secrets = ctx.state("log-secrets-tunnel.json")
    failures, ok_rows, skipped = run_matrix(
        ctx,
        [
            tunnel,
            "--mode",
            "oidc",
            "--public-base-url",
            tunnel,
            f"--credential-file={credential_file}",
            f"--token-out={pat}",
            f"--log-secrets-out={log_secrets}",
            "--behind-proxy",
            "--skip-rate-limits",
            "--hold-stream",
            str(max(ctx.hold, 130)),
        ],
    )
    ctx.results.record(
        "tunnel: matrix (oidc, signed in)",
        f"{failures} failing / {ok_rows} ok rows, {skipped} skipped;"
        " limiter checks skipped — a CDN's latency and URL normalisation make nginx's"
        " per-address, per-spelling keying unobservable here (proven at the packaged layer)",
        failures == 0,
    )
    # The app's own attribution, independent of nginx's $remote_addr: the matrix
    # minted tokens through the tunnel, so the newest mint's audit row must name
    # the same visitor — the tunnel counterpart of the trusted-proxies phase.
    minted = host.psql(
        "select client_address from audit_event where event_type = 'auth.token_minted'"
        " order by occurred_at desc limit 1;"
    )
    recorded = minted[0] if minted else ""
    ctx.results.record("tunnel: audit client_address", recorded, recorded == ctx.tunnel_visitor)
    scan_logs(ctx, [log_secrets])
    host.env_set(WEB_BIND="127.0.0.1", PUBLIC_BASE_URL=ctx.base, TRUSTED_PROXIES="127.0.0.1")
    host.up()
    ctx.results.record(
        "tunnel: restored", "WEB_BIND, PUBLIC_BASE_URL and TRUSTED_PROXIES back to mode R"
    )


PHASES = {
    "precheck": phase_precheck,
    "lockout": phase_lockout,
    "local": phase_local,
    "modern-hold": phase_modern_hold,
    "break-glass": phase_break_glass,
    "trusted-proxies": phase_trusted_proxies,
    "oidc": phase_oidc,
    "t13": phase_t13,
    "tunnel": phase_tunnel,
}
ALL = (
    "precheck",
    "lockout",
    "local",
    "modern-hold",
    "break-glass",
    "trusted-proxies",
    "oidc",
    "t13",
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", required=True, help="https://NAME — the instance through Caddy")
    parser.add_argument("--ssh", required=True, help="user@host for the host-side steps")
    parser.add_argument("--remote-dir", default="/opt/plamotrack")
    parser.add_argument("--idp", default=None, help="https://idp.NAME — the gate's Keycloak")
    parser.add_argument("--idp-user", default="owner")
    parser.add_argument(
        "--idp-password-env",
        default="GATE_IDP_PASSWORD",
        help="the environment variable holding the provider password (never an argument)",
    )
    parser.add_argument("--hold", type=int, default=75, help="seconds to hold the MCP stream")
    parser.add_argument("--ca-cert", default=None)
    parser.add_argument("--host-ip", default=None, help="the host's LAN address (tunnel phase)")
    parser.add_argument("--tunnel-base", default=None, help="https://TUNNEL-NAME (tunnel phase)")
    parser.add_argument(
        "--tunnel-proxy", default=None, help="the connector's address (tunnel phase)"
    )
    parser.add_argument(
        "--tunnel-visitor",
        default=None,
        help="this workstation's public address as Cloudflare forwards it (tunnel phase); "
        "curl -s https://cloudflare.com/cdn-cgi/trace | sed -n s/^ip=//p",
    )
    parser.add_argument("--phase", choices=(*PHASES, "all"), default="all")
    parser.add_argument("--state-dir", default=None, help="where the run's secrets live (0700)")
    parser.add_argument("--results-out", default=None, help="write the results block here")
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    name = urlsplit(base).hostname or "gate"
    state_dir = pathlib.Path(args.state_dir or (pathlib.Path.home() / ".plamotrack-gate" / name))
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    if args.ca_cert:
        matrix.TLS_CONTEXT = ssl.create_default_context(cafile=args.ca_cert)
    ctx = Context(
        base=base,
        host=Host(args.ssh, args.remote_dir),
        results=Results(),
        state_dir=state_dir,
        idp=args.idp.rstrip("/") if args.idp else None,
        idp_user=args.idp_user,
        idp_password=os.environ.get(args.idp_password_env),
        hold=args.hold,
        ca_cert=args.ca_cert,
        host_ip=args.host_ip,
        tunnel_base=args.tunnel_base.rstrip("/") if args.tunnel_base else None,
        tunnel_proxy=args.tunnel_proxy,
        tunnel_visitor=args.tunnel_visitor,
    )
    phases = list(ALL) if args.phase == "all" else [args.phase]
    if args.phase == "all" and args.tunnel_base:
        phases.append("tunnel")
    started = time.strftime("%Y-%m-%d %H:%M %Z")
    for phase in phases:
        print(f"\n=== {phase} ===")
        try:
            PHASES[phase](ctx)
        except GateError as error:
            ctx.results.record(f"{phase}: stopped", str(error), ok=False)
            break
    header = [
        f"### Deployment gate (T12/T13) — {started}, {name}",
        f"Phases: {', '.join(phases)}. Stream hold {ctx.hold} s.",
    ]
    block = ctx.results.markdown(header)
    print("\n" + block)
    if args.results_out:
        pathlib.Path(args.results_out).write_text(block, encoding="utf-8")
    return ctx.results.failures


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

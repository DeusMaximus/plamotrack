"""The database URL assembled from POSTGRES_* (#299), and its way into alembic (#300).

`Settings._assemble_database_url` writes one URL; its readers do not read a host
the same way, so each is asserted on what it actually receives:

- **SQLAlchemy** (`app/db.py`, `tests/conftest.py`) takes the bracketed host
  verbatim — `make_url` does not percent-decode it — and its asyncpg dialect hands
  that string to `asyncpg.connect(host=…)`. A zone id stays raw: `[fe80::1%eth0]`.
  RFC 6874's `%25` would parse, and reach the resolver as `fe80::1%25eth0`.
- **asyncpg's own DSN parser** (`app/auth/mcp_oauth_state.asyncpg_dsn`, the MCP
  OAuth state store) percent-decodes the host, so there the zone is `%25`.
- **alembic** (`alembic/env.py`) stores the URL in a ConfigParser, which
  interpolates `%` — a percent-encoded password, a zone id.

Pure, no database: the alembic leg runs offline (`--sql`), which parses the URL
and writes the DDL without connecting.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from asyncpg.connect_utils import _parse_connect_dsn_and_args
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect
from sqlalchemy.engine import make_url

from app.auth.mcp_oauth_state import asyncpg_dsn
from app.config import Settings

BACKEND = Path(__file__).resolve().parents[1]

PORT = 6543
DATABASE = "plamotrack_299"

#: POSTGRES_HOST as written, and the host every reader must end up with.
HOSTS = [
    ("127.0.0.1", "127.0.0.1"),
    ("db", "db"),
    ("localhost", "localhost"),
    ("::1", "::1"),
    ("2001:db8::1", "2001:db8::1"),
    ("[::1]", "::1"),
    ("fe80::1%eth0", "fe80::1%eth0"),
    # A numeric zone (an interface index): two hex digits after the `%`, which a
    # percent-decoder turns into one control character if the zone reaches it raw.
    ("fe80::1%12", "fe80::1%12"),
]

#: (user, password): the plain pair, and one that must be percent-encoded — `@`, `/`
#: and `:` split a URL's authority, `%` is what ConfigParser interpolates (#300), and
#: a space is the one character SQLAlchemy's renderer leaves raw.
CREDENTIALS = [
    ("plamotrack", "plamotrack"),
    ("pl@mo:user", "p@ss w/%rd:+=#?"),
]


def _settings(host: str, user: str = "plamotrack", password: str = "plamotrack") -> Settings:
    # `_env_file=None` and an explicit `database_url=""`: a developer's .env, or the
    # DATABASE_URL conftest exports, must not stand in for the assembled URL.
    return Settings(
        _env_file=None,
        database_url="",
        postgres_host=host,
        postgres_port=PORT,
        postgres_db=DATABASE,
        postgres_user=user,
        postgres_password=password,
    )


@pytest.mark.parametrize(("user", "password"), CREDENTIALS)
@pytest.mark.parametrize(("setting", "host"), HOSTS)
def test_assembled_url_round_trips_through_sqlalchemy(setting, host, user, password):
    url = make_url(_settings(setting, user, password).database_url)

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == host
    assert url.port == PORT
    assert url.database == DATABASE
    assert url.username == user
    assert url.password == password


@pytest.mark.parametrize(("setting", "host"), HOSTS)
def test_engine_hands_asyncpg_the_bare_host(setting, host):
    # What `create_async_engine` passes to `asyncpg.connect` — the resolver sees
    # this string, so brackets or an encoded zone here are a failed connect.
    _, kwargs = asyncpg_dialect().create_connect_args(make_url(_settings(setting).database_url))

    assert kwargs["host"] == host
    assert kwargs["port"] == PORT


@pytest.mark.parametrize(("user", "password"), CREDENTIALS)
@pytest.mark.parametrize(("setting", "host"), HOSTS)
def test_state_store_dsn_round_trips_through_asyncpg(setting, host, user, password):
    # The MCP OAuth state store gives asyncpg a DSN string; this is the parser
    # `asyncpg.create_pool` runs on it.
    addrs, params = _parse_connect_dsn_and_args(
        dsn=asyncpg_dsn(_settings(setting, user, password).database_url),
        host=None,
        port=None,
        user=None,
        password=None,
        passfile=None,
        database=None,
        ssl=None,
        service=None,
        servicefile=None,
        direct_tls=None,
        server_settings=None,
        target_session_attrs=None,
        krbsrvname=None,
        gsslib=None,
    )

    assert addrs == [(host, PORT)]
    assert params.user == user
    assert params.password == password
    assert params.database == DATABASE


def test_default_host_is_loopback_ipv4(monkeypatch):
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    settings = Settings(_env_file=None, database_url="")

    assert make_url(settings.database_url).host == "127.0.0.1"


@pytest.mark.parametrize(
    "setting", ["db:5433", "127.0.0.1:5432", "[::1]:5432", "[db:5433]", "::zz"]
)
def test_a_colon_outside_an_ipv6_literal_is_refused(setting):
    # The port is POSTGRES_PORT. Unrefused, `db:5433` would be bracketed as if it
    # were an address and fail at the resolver, far from the setting that caused it.
    with pytest.raises(ValidationError, match="POSTGRES_HOST"):
        _settings(setting)


def test_an_explicit_database_url_is_left_alone():
    # POSTGRES_HOST is only read to assemble the URL; set DATABASE_URL and the
    # host is inert, so a stale or odd value there refuses nothing.
    explicit = "postgresql+asyncpg://someone:secret@[2001:db8::7]:5433/elsewhere"
    settings = Settings(_env_file=None, database_url=explicit, postgres_host="db:5433")

    assert settings.database_url == explicit


#: env.py run for real, in a fresh interpreter (it reads `get_settings()`, which
#: this process has cached): offline, so it parses the URL without connecting,
#: then the URL read back the way each mode reads it — `get_main_option` offline,
#: `get_section` online (the dict `async_engine_from_config` is given).
_ALEMBIC_PROBE = """
import io, json, sys
from alembic import command
from alembic.config import Config
from app.config import get_settings

cfg = Config("alembic.ini", output_buffer=io.StringIO())
command.upgrade(cfg, "head", sql=True)
with open(sys.argv[1], "w") as out:
    json.dump(
        {
            "assembled": get_settings().database_url,
            "offline": cfg.get_main_option("sqlalchemy.url"),
            "online": cfg.get_section(cfg.config_ini_section)["sqlalchemy.url"],
            "ddl": "CREATE TABLE kits" in cfg.output_buffer.getvalue(),
        },
        out,
    )
"""


@pytest.mark.parametrize(
    ("setting", "host", "user", "password"),
    [
        ("127.0.0.1", "127.0.0.1", *CREDENTIALS[1]),  # #300 alone
        ("::1", "::1", *CREDENTIALS[0]),  # #299 alone
        ("2001:db8::1", "2001:db8::1", *CREDENTIALS[1]),
        ("fe80::1%eth0", "fe80::1%eth0", *CREDENTIALS[0]),  # a `%` from the host
    ],
)
def test_alembic_reads_the_url_it_was_given(tmp_path, setting, host, user, password):
    result = tmp_path / "alembic.json"
    env = {
        **os.environ,
        "DATABASE_URL": "",
        "POSTGRES_HOST": setting,
        "POSTGRES_PORT": str(PORT),
        "POSTGRES_DB": DATABASE,
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
    }
    run = subprocess.run(
        [sys.executable, "-c", _ALEMBIC_PROBE, str(result)],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr[-2000:]

    seen = json.loads(result.read_text())
    assert seen["ddl"]
    assert make_url(seen["assembled"]).host == host
    assert seen["offline"] == seen["assembled"]
    assert seen["online"] == seen["assembled"]

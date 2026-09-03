import re
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import quote, urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.hostnames import validate_host_pattern

_CURRENCY_RE = re.compile(r"[A-Z]{3}")


def split_csv(value: str) -> list[str]:
    """A comma-separated setting as its non-empty, stripped entries."""
    return [entry.strip() for entry in value.split(",") if entry.strip()]


# Anchored on this file, not the working directory: `uv run uvicorn` from
# backend/ and `pytest` from the repo root must resolve the same config.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent

# The repo-root .env is the one file to edit — docker compose reads it too, so
# the database credentials are stated once. backend/.env is an optional
# override for anything backend-specific; later files win. Missing files are
# ignored, which is what happens in a container where config arrives as real
# environment variables.
_ENV_FILES = (_REPO_ROOT / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    # Shared with the docker-compose db service (§8).
    postgres_user: str = "plamotrack"
    postgres_password: str = "plamotrack"
    postgres_db: str = "plamotrack"
    # Where the API reaches Postgres: the host port mapped by compose in dev,
    # the service name inside the compose network once the API is containerised.
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    # Left empty, this is assembled from the POSTGRES_* values above so the
    # password lives in exactly one place. Set DATABASE_URL explicitly to point
    # at an external Postgres or to override the assembled DSN wholesale.
    database_url: str = ""

    # "null" disables connection pooling; used by the test suite where each test
    # runs in its own event loop and pooled connections would cross loops.
    database_pool: str = "default"

    # The currency this instance converts foreign purchases into for comparison
    # (§6). It supplies the *default* for new entries only — every converted
    # amount stores the code it was captured under, so changing this later never
    # reinterprets a snapshot that was already taken.
    reference_currency: str = "AUD"

    # --- Ingress identity (§5.6, M6-1 / #186) ----------------------------------
    # The instance's own address, as a browser reaches it: scheme, host and port,
    # nothing after. It is never derived from Host or X-Forwarded-* (§5.6, proxy
    # trust). Its host joins the Host allowlist and its origin the Origin
    # allowlist — behind TLS the app sees plain http on the socket while the
    # browser sends https://…, and this entry is what lets that match. Empty
    # means the loopback install: http://localhost:<WEB_PORT>, which the loopback
    # rules already cover, so nothing extra is listed.
    public_base_url: str = ""
    # Comma-separated host names the instance may be reached by, on top of the
    # loopback names, PUBLIC_BASE_URL's host and WEB_BIND. Ports are ignored
    # (the Host header's port is not identity). `*.example.lan` wildcards are
    # accepted; a bare `*` is not — an allowlist of everything is the DNS-
    # rebinding hole the setting exists to close. A Host outside the list is 421.
    allowed_hosts: str = ""
    # Comma-separated browser origins (scheme://host[:port]) trusted on unsafe
    # methods beyond the three-way rule (listed, loopback-to-loopback, or equal
    # to the request's own origin). Only needed for a non-canonical alias
    # reached over a scheme the app does not see. A miss is 403.
    allowed_origins: str = ""
    # Comma-separated IPs or CIDRs whose X-Forwarded-For is believed for the
    # *client address* (rate limiting and audit, later M6 items). Never for the
    # app's identity, never for the raw peer `/readyz` reads. Empty: ignored.
    trusted_proxies: str = ""
    # The interface the published port binds to (compose reads the same key).
    # A non-loopback bind address is a name the instance answers to, so it joins
    # the Host allowlist; 0.0.0.0 and :: are unspecified and add nothing.
    web_bind: str = "127.0.0.1"

    @field_validator("public_base_url")
    @classmethod
    def _validate_public_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(
                "PUBLIC_BASE_URL must be an absolute http:// or https:// URL "
                f"with a host (got {value!r})"
            )
        if parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError(
                "PUBLIC_BASE_URL is scheme, host and port only — no path, query, "
                f"fragment or credentials (got {value!r})"
            )
        try:
            _ = parsed.port  # raises on a non-numeric or out-of-range port
        except ValueError as exc:
            raise ValueError(f"PUBLIC_BASE_URL has an invalid port (got {value!r})") from exc
        # The host joins the allowlist, so it obeys the allowlist grammar — a
        # `*` here would otherwise admit every Host (PR #196 review, P3-1).
        validate_host_pattern(parsed.hostname, setting="PUBLIC_BASE_URL", allow_wildcard=False)
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def _validate_allowed_hosts(cls, value: str) -> str:
        # Judged on the normalised form the guard matches, not the raw spelling:
        # `*:8080` loses its port on the way to matching and becomes `*` (PR
        # #196 review, P3-1). `*.example.lan` is the one accepted wildcard.
        for entry in split_csv(value):
            validate_host_pattern(entry, setting="ALLOWED_HOSTS", allow_wildcard=True)
        return value

    @field_validator("web_bind")
    @classmethod
    def _validate_web_bind(cls, value: str) -> str:
        # Also a name the instance answers to, so the same grammar; the
        # unspecified addresses are the exception — they bind everything and
        # name nothing.
        value = value.strip()
        if value in ("", "0.0.0.0", "::", "[::]"):
            return value
        validate_host_pattern(value, setting="WEB_BIND", allow_wildcard=False)
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _validate_allowed_origins(cls, value: str) -> str:
        for entry in split_csv(value):
            parsed = urlsplit(entry)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError(
                    f"ALLOWED_ORIGINS entries are origins — scheme://host[:port] (got {entry!r})"
                )
            if parsed.path.strip("/") or parsed.query or parsed.fragment or parsed.username:
                raise ValueError(f"ALLOWED_ORIGINS entry {entry!r} is not a bare origin")
            # Origins are exact: `http://*:8080` would be a wildcard pattern to
            # the guard's fnmatch (PR #196 review, the P3-1 sweep).
            validate_host_pattern(parsed.hostname, setting="ALLOWED_ORIGINS", allow_wildcard=False)
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _validate_trusted_proxies(cls, value: str) -> str:
        for entry in split_csv(value):
            try:
                ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"TRUSTED_PROXIES entries are IP addresses or CIDR ranges (got {entry!r})"
                ) from exc
        return value

    @field_validator("reference_currency")
    @classmethod
    def _validate_reference_currency(cls, value: str) -> str:
        code = value.strip().upper()
        if not _CURRENCY_RE.fullmatch(code):
            raise ValueError(f"REFERENCE_CURRENCY must be a 3-letter ISO 4217 code (got {value!r})")
        return code

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if not self.database_url:
            # quote() the credentials — a password containing @ or / would
            # otherwise produce a DSN that parses into the wrong host.
            user = quote(self.postgres_user, safe="")
            password = quote(self.postgres_password, safe="")
            self.database_url = (
                f"postgresql+asyncpg://{user}:{password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

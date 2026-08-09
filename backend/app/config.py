import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_CURRENCY_RE = re.compile(r"[A-Z]{3}")

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

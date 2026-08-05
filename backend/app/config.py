from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://plamotrack:plamotrack@127.0.0.1:5432/plamotrack"
    # "null" disables connection pooling; used by the test suite where each test
    # runs in its own event loop and pooled connections would cross loops.
    database_pool: str = "default"


@lru_cache
def get_settings() -> Settings:
    return Settings()

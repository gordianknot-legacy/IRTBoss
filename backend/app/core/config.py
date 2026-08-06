"""Application settings.

Everything the application needs to talk to the outside world is declared here
and nowhere else. v1 read ``os.getenv`` at import time in four modules with
different defaults, which is how it ended up shipping ``allow_origins=["*"]``
alongside ``allow_credentials=True`` and an upload path that no configuration
could move (P5).

Two rules this module enforces rather than documents:

1. **No usable default for a secret.** ``secret_key`` has a development
   placeholder that is rejected outright when ``environment == "production"``,
   so a deployment that forgot to set it fails to start instead of signing
   session tokens with a value that is in the git history.
2. **CORS is an allowlist.** ``cors_allow_origins`` defaults to the local dev
   origin. ``"*"`` is rejected by a validator, because the combination the
   product needs (cookies) is one browsers refuse against a wildcard anyway.

Upload caps live here too: v1 read whole request bodies into RAM with no size,
row or column bound (P5), so the limits have to be a first-class, testable
setting rather than a constant buried in a route.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Sentinel value. Present so that `pytest` and `uvicorn --reload` work with an
# empty environment; refused in production by `_reject_default_secret`.
DEV_PLACEHOLDER_SECRET = "dev-insecure-do-not-use-in-production"


class Settings(BaseSettings):
    """Runtime configuration, populated from the environment or a ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="IRTBOSS_",
        extra="ignore",
    )

    environment: str = "development"

    # --- persistence -----------------------------------------------------
    # Async driver URLs only. The worker runs the same URL through asyncio,
    # so there is no second sync driver to forget from requirements (P5 killed
    # the v1 worker exactly that way, with a psycopg2 import that was never
    # declared).
    database_url: str = "postgresql+asyncpg://irtboss:irtboss@localhost:5432/irtboss"
    redis_url: str = "redis://localhost:6379/0"
    sql_echo: bool = False

    # --- auth ------------------------------------------------------------
    secret_key: SecretStr = SecretStr(DEV_PLACEHOLDER_SECRET)
    session_ttl_seconds: int = 60 * 60 * 12
    session_cookie_name: str = "irtboss_session"
    # Login throttling. In-process by default; see app.auth.ratelimit for the
    # multi-worker caveat.
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    # --- uploads ---------------------------------------------------------
    upload_dir: Path = Path("var/uploads")
    max_upload_bytes: int = 25 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 1_000

    # --- HTTP ------------------------------------------------------------
    # `NoDecode` because pydantic-settings would otherwise insist on JSON for a
    # list-typed env var, before `_split_origins` gets to accept a plain
    # comma-separated string.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        # Env vars arrive as a single string; accept comma separation so the
        # allowlist is expressible without JSON quoting in a shell.
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("cors_allow_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        if any(origin.strip() == "*" for origin in value):
            raise ValueError(
                "cors_allow_origins must be an explicit allowlist; '*' is not "
                "usable with credentialed requests and was the v1 defect"
            )
        return value

    @model_validator(mode="after")
    def _reject_default_secret(self) -> Settings:
        if self.is_production and self.secret_key.get_secret_value() == DEV_PLACEHOLDER_SECRET:
            raise ValueError(
                "IRTBOSS_SECRET_KEY must be set to a real value in production"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings.

    Cached so that a request handler does not re-read the environment, and so
    that tests can clear the cache to install a different configuration.
    """

    return Settings()

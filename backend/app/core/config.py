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

A third rule joins them, for the same reason as the first: **local upload storage
is refused in production.** A directory shared between the API and the worker
works only while the two processes sit on one machine, and the failure when they
do not is a run that dies with a missing file — which reads as corrupted data
rather than as a deployment mistake. That is a thing to fail at start-up over,
not to discover from a support request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

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
    csrf_cookie_name: str = "irtboss_csrf"
    # `None` means "decide from the environment", and the decision is made by
    # `session_cookie_is_secure` below rather than by `is_production`. Set this
    # explicitly only to force it; `False` is refused in production.
    session_cookie_secure: bool | None = None
    # Login throttling. In-process by default; see app.auth.ratelimit for the
    # multi-worker caveat.
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    # --- uploads ---------------------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 1_000

    # --- upload storage --------------------------------------------------
    # See app/storage/. `local` is for development and tests and is rejected
    # below in production. S3 credentials are *not* settings: botocore's own
    # chain (environment, shared config, instance role) resolves them, so there
    # is one place to look for them and one fewer secret for this file to avoid
    # logging.
    storage_backend: Literal["local", "s3"] = "local"
    upload_dir: Path = Path("var/uploads")  # root for the local backend only
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_endpoint_url: str | None = None  # set for R2, B2, MinIO; omit for AWS
    s3_region: str | None = None

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

    @model_validator(mode="after")
    def _reject_unusable_storage(self) -> Settings:
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError(
                "IRTBOSS_S3_BUCKET must be set when IRTBOSS_STORAGE_BACKEND is 's3'"
            )
        if self.is_production and self.storage_backend == "local":
            raise ValueError(
                "local upload storage is not usable in production: the API and the "
                "worker would have to share a filesystem, and a worker that does "
                "not fails the run with a missing file. Set "
                "IRTBOSS_STORAGE_BACKEND=s3 and IRTBOSS_S3_BUCKET"
            )
        return self

    @model_validator(mode="after")
    def _reject_insecure_cookie_in_production(self) -> Settings:
        if self.is_production and self.session_cookie_secure is False:
            raise ValueError(
                "IRTBOSS_SESSION_COOKIE_SECURE=false would send the session cookie "
                "over plaintext HTTP in production"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def is_local_development(self) -> bool:
        """Named environments where plaintext HTTP is expected.

        The complement of this — not ``is_production`` — is what decides whether
        the session cookie is marked ``Secure``. The distinction matters because
        ``environment`` is a free string: ``staging``, ``uat`` and ``demo`` are
        all not-production, and under the previous rule each of them silently
        served a session cookie that a browser would send over plaintext. An
        environment name this list does not recognise now fails safe.
        """

        return self.environment.lower() in {
            "development",
            "dev",
            "local",
            "test",
            "testing",
        }

    @property
    def session_cookie_is_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return not self.is_local_development


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings.

    Cached so that a request handler does not re-read the environment, and so
    that tests can clear the cache to install a different configuration.
    """

    return Settings()

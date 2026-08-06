"""Configuration and schema guarantees.

CORS and the secret key are covered here because both were shipped wrong in v1
(P5: ``allow_origins=["*"]`` with credentials). The migration test is here
because v1 had no migrations at all, and a migration that has drifted from the
models is the same outage as having none.
"""

from __future__ import annotations

import pytest
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from app.core.config import DEV_PLACEHOLDER_SECRET, Settings
from app.db.models import Base
from app.main import create_app


def test_wildcard_cors_origin_is_rejected():
    with pytest.raises(ValueError, match="allowlist"):
        Settings(cors_allow_origins=["*"], secret_key="x" * 32)


def test_configured_cors_is_an_allowlist_not_a_wildcard(settings):
    app = create_app(settings)
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1

    options = cors[0].kwargs
    assert options["allow_origins"] == settings.cors_allow_origins
    assert "*" not in options["allow_origins"]
    assert options["allow_credentials"] is True
    assert "*" not in options["allow_methods"]
    assert "*" not in options["allow_headers"]


async def test_cors_response_echoes_only_allowed_origins(client, settings):
    allowed = await client.get(
        "/api/v1/health", headers={"Origin": settings.cors_allow_origins[0]}
    )
    assert allowed.headers.get("access-control-allow-origin") == settings.cors_allow_origins[0]

    denied = await client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_production_refuses_the_placeholder_secret():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(environment="production", secret_key=DEV_PLACEHOLDER_SECRET)

    # A real secret in production is fine.
    ok = Settings(environment="production", secret_key="a-real-deployment-secret-value")
    assert ok.is_production


def test_secret_key_is_not_printable():
    settings = Settings(secret_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings.secret_key)


def test_migration_head_matches_the_models(tmp_path, settings, monkeypatch):
    """`alembic upgrade head` must produce the schema the ORM expects.

    Compared on tables and column names rather than types, because SQLite
    normalises several of the types the models declare; a type-level comparison
    belongs in CI against a real Postgres (see the report notes).
    """

    from alembic.config import Config

    from alembic import command

    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("IRTBOSS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    from app.core.config import get_settings

    get_settings.cache_clear()

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        migrated = set(inspector.get_table_names()) - {"alembic_version"}
        assert migrated == set(Base.metadata.tables)

        for table_name, table in Base.metadata.tables.items():
            columns = {c["name"] for c in inspector.get_columns(table_name)}
            assert columns == set(table.columns.keys()), table_name
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_owner_scoped_tables_carry_an_owner_and_an_index():
    """Every user-reachable root table is filterable by owner.

    The IDOR fix depends on this being true of the schema, not only of today's
    queries.
    """

    for table_name in ("projects", "datasets", "analysis_runs"):
        table = Base.metadata.tables[table_name]
        assert "owner_id" in table.columns
        indexed = {tuple(c.name for c in index.columns) for index in table.indexes}
        assert ("owner_id",) in indexed
        assert ("owner_id", "created_at") in indexed

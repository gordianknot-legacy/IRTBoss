"""Fixtures for the application-layer tests.

The test database is SQLite via aiosqlite by default, so the suite runs with no
services. Setting ``IRTBOSS_TEST_DATABASE_URL`` points the same tests at a
disposable PostgreSQL instead, which is what CI does — the differences below are
invisible on SQLite, so a green local run is not on its own evidence that the
schema behaves the way it will in production.

Two consequences of the SQLite default, worth stating rather than discovering:

* ``JSONB`` degrades to ``JSON`` through the variant in :mod:`app.db.models`, so
  these tests exercise JSON round-tripping but not PostgreSQL operators. Nothing
  in the application uses those operators today.
* SQLite does not enforce foreign keys unless asked, and enum ``CHECK``
  constraints are the only enum enforcement on either backend, because the models
  use ``native_enum=False``. Foreign keys are turned on below so cascade
  behaviour is actually tested.

The queue is fakeredis-backed and **not** run inline: an inline queue would make
"is the enqueue wired?" untestable, which is the one question v1 got wrong.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import fakeredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from rq import Queue
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.ratelimit import set_login_rate_limiter
from app.core.config import Settings, get_settings
from app.db.database import create_all, drop_all, set_engine
from app.main import create_app
from app.storage import set_object_store
from app.workers.queue import QUEUE_NAME, set_queue

TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    # SQLite by default so the suite runs with no services. Point
    # IRTBOSS_TEST_DATABASE_URL at a disposable Postgres to run the same tests
    # against the database the product actually deploys on — JSONB rather than
    # JSON, native uuid columns, real ON DELETE CASCADE. Those differences are
    # invisible on SQLite, so a green local run is not evidence the schema
    # behaves in production.
    monkeypatch.setenv(
        "IRTBOSS_DATABASE_URL",
        os.environ.get("IRTBOSS_TEST_DATABASE_URL")
        or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    monkeypatch.setenv("IRTBOSS_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("IRTBOSS_SECRET_KEY", "test-secret-key-not-the-placeholder")
    monkeypatch.setenv("IRTBOSS_CORS_ALLOW_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("IRTBOSS_MAX_UPLOAD_BYTES", "4096")
    monkeypatch.setenv("IRTBOSS_MAX_ROWS", "500")
    monkeypatch.setenv("IRTBOSS_MAX_COLUMNS", "20")
    get_settings.cache_clear()
    set_login_rate_limiter(None)
    # Cleared on the way in as well as out, so a test that installs a store
    # override cannot leak it into the next one through a failed teardown. The
    # default backend is local and rooted at tmp_path, so every test gets its own
    # upload directory.
    set_object_store(None)
    yield get_settings()
    get_settings.cache_clear()
    set_login_rate_limiter(None)
    set_object_store(None)


@pytest_asyncio.fixture
async def engine(settings):
    engine = create_async_engine(settings.database_url)

    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked. Postgres does not need this
        # and rejects the pragma.
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        # A file-backed SQLite database is new for every test because the path
        # is under tmp_path. A shared Postgres database is not, so it is reset
        # explicitly — otherwise state leaks between tests and the failures
        # depend on execution order.
        await drop_all(engine)

    await create_all(engine)
    set_engine(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def queue(settings) -> Queue:
    connection = fakeredis.FakeStrictRedis()
    q = Queue(QUEUE_NAME, connection=connection, is_async=True)
    set_queue(q)
    yield q
    set_queue(None)


@pytest_asyncio.fixture
async def client(settings, engine, queue) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def register(client: AsyncClient, email: str | None = None) -> str:
    """Register an account and return its bearer token."""

    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 201, response.text
    # The register response also sets a session cookie, and the dependency
    # prefers cookies over bearer headers. Dropping it here keeps a single
    # client usable as several different users via explicit headers.
    client.cookies.clear()
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


CSV_BODY = "\n".join(
    ["id,i1,i2,i3"] + [f"p{n},{n % 2},{(n + 1) % 2},1" for n in range(20)]
)

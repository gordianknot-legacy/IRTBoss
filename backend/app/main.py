"""ASGI application factory.

Two things this file does not do, both of them v1 defects (P5):

* It does not set ``allow_origins=["*"]``. The allowlist comes from settings and
  a wildcard is rejected there, because the wildcard was paired with
  ``allow_credentials=True`` — a combination browsers refuse and which would
  have been wide open if they did not.
* It does not create tables. Schema comes from Alembic.

Unhandled exceptions are converted to a generic 500 body. v1 returned raw
exception strings to clients, which leaks paths, driver internals and query
fragments to anyone able to provoke an error.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.auth.csrf import CSRF_HEADER_NAME, CSRFMiddleware
from app.core.config import Settings, get_settings
from app.db.database import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="IRTBoss API",
        version="2.0.0",
        description="Assessment validation: fit, diagnose, and report on item response models.",
        lifespan=_lifespan,
    )

    # Order matters, and `add_middleware` inserts at the front of the stack — so
    # the CORS layer added second is the outer one. That is the arrangement we
    # want: a CSRF rejection comes back through CORS and therefore carries the
    # headers a browser needs to read the 403, instead of surfacing in the console
    # as an opaque network error.
    app.add_middleware(CSRFMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", CSRF_HEADER_NAME],
    )

    app.include_router(api_router)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Logged in full server-side, generic to the client.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


app = create_app()

"""Assembly of the versioned API surface."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import analyses, auth, datasets, projects

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(datasets.router)
api_router.include_router(analyses.router)


@api_router.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness only — no database round trip.

    The container healthcheck must probe *this* path. v1's Dockerfile probed
    ``/health``, which did not exist, with curl, which was not installed (P5).
    """

    return {"status": "ok"}

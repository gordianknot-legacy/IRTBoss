# API routes for IRTBoss
"""
FastAPI routes for the IRT assessment platform.

Provides endpoints for:
- File upload and validation
- Model fitting jobs
- Results retrieval
- Report generation
"""

from .routes import router
from .schemas import (
    ProjectCreate,
    ProjectResponse,
    UploadResponse,
    FittingJobResponse,
    ModelResultResponse,
    ReportRequest,
)

__all__ = [
    "router",
    "ProjectCreate",
    "ProjectResponse",
    "UploadResponse",
    "FittingJobResponse",
    "ModelResultResponse",
    "ReportRequest",
]

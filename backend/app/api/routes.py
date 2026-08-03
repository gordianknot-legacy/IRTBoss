"""
FastAPI routes for the IRT assessment platform.

This module defines all HTTP endpoints for the API.
Each endpoint is documented with its purpose and expected behavior.
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..services.project_service import ProjectService
from ..reports.generator import ReportGenerator, ReportData
from .schemas import (
    ProjectCreate,
    ProjectResponse,
    UploadResponse,
    FittingJobCreate,
    FittingJobResponse,
    FittingProgress,
    ModelResultResponse,
    DiagnosticsResponse,
    RecommendationsResponse,
    ReportRequest,
    ReportResponse,
    ReportFormat,
    JobStatus,
    ValidationMessage,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    """Dependency for ProjectService."""
    return ProjectService(db)


# --- Health Check ---

@router.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns the service status for monitoring and load balancers.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
    }


# --- Projects ---

@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    service: ProjectService = Depends(get_project_service),
):
    """
    Create a new assessment project.

    A project is the top-level container for an IRT analysis.
    Users specify the stakes level and intended use upfront,
    which affects recommendations and thresholds later.
    """
    return await service.create_project(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get details of an existing project.
    """
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return project


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    limit: int = 20,
    offset: int = 0,
    service: ProjectService = Depends(get_project_service),
):
    """
    List all projects, with pagination.
    """
    return await service.list_projects(limit=limit, offset=offset)


# --- Data Upload ---

@router.post("/projects/{project_id}/upload", response_model=UploadResponse)
async def upload_data(
    project_id: UUID,
    file: UploadFile = File(...),
    service: ProjectService = Depends(get_project_service),
):
    """
    Upload response data for a project.

    Accepts CSV files only. The file is validated immediately:
    - Structure detection (items, respondents)
    - Response type detection (dichotomous/polytomous)
    - Data quality checks
    - Sample size warnings

    Returns detailed feedback so users know immediately if
    their data is suitable for IRT analysis.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return UploadResponse(
            is_valid=False,
            summary=None,
            messages=[
                ValidationMessage(
                    severity="error",
                    code="INVALID_FILE_TYPE",
                    message="Only CSV files are accepted",
                    details=f"Received: {file.filename}",
                )
            ],
        )

    # Read file content
    try:
        contents = await file.read()
        if len(contents) == 0:
            return UploadResponse(
                is_valid=False,
                summary=None,
                messages=[
                    ValidationMessage(
                        severity="error",
                        code="EMPTY_FILE",
                        message="The uploaded file is empty",
                    )
                ],
            )
    except Exception as e:
        logger.exception("Error reading uploaded file")
        return UploadResponse(
            is_valid=False,
            summary=None,
            messages=[
                ValidationMessage(
                    severity="error",
                    code="READ_ERROR",
                    message="Error reading file",
                    details=str(e),
                )
            ],
        )

    # Process upload through service
    return await service.upload_data(
        project_id=project_id,
        filename=file.filename,
        content=contents,
    )


# --- Model Fitting ---

@router.post("/projects/{project_id}/fit", response_model=FittingJobResponse)
async def start_fitting(
    project_id: UUID,
    request: FittingJobCreate,
    service: ProjectService = Depends(get_project_service),
):
    """
    Start async model fitting for a project.

    This initiates a background job that fits the requested IRT models.
    Returns immediately with a job ID that can be polled for progress.

    Models are fitted in order of complexity (1PL -> 2PL -> 3PL).
    The 3PL is only fitted if sample size permits.
    """
    job = await service.start_fitting(
        project_id=project_id,
        fit_1pl=request.fit_1pl,
        fit_2pl=request.fit_2pl,
        fit_3pl=request.fit_3pl,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    return FittingJobResponse(
        job_id=job.id,
        project_id=job.project_id,
        status=JobStatus(job.status),
        progress=job.progress,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
    )


@router.get("/jobs/{job_id}", response_model=FittingJobResponse)
async def get_job_status(
    job_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get the status of a fitting job.

    Poll this endpoint to track progress of model fitting.
    """
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return FittingJobResponse(
        job_id=job.id,
        project_id=job.project_id,
        status=JobStatus(job.status),
        progress=job.progress,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
    )


@router.get("/jobs/{job_id}/progress", response_model=FittingProgress)
async def get_job_progress(
    job_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get detailed progress of a fitting job.

    Returns more detailed progress information including
    which model is currently being fitted.
    """
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return FittingProgress(
        job_id=job.id,
        status=JobStatus(job.status),
        progress=job.progress,
        current_model=job.current_model,
        message=None,
    )


# --- Results ---

@router.get("/projects/{project_id}/results", response_model=ModelResultResponse)
async def get_results(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get model fitting results for a project.

    Returns the complete results including:
    - Model comparison summary
    - Selected model recommendation
    - Item parameters
    - Reliability estimate

    Only available after fitting is complete.
    """
    result = await service.get_results(project_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No results found. Ensure model fitting has completed.",
        )
    return result


@router.get("/projects/{project_id}/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get diagnostic information for a project.

    Returns data for visualization:
    - Test Information Function
    - Item-level diagnostics and flags
    - Reliability estimates
    """
    result = await service.get_diagnostics(project_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No diagnostics found. Ensure model fitting has completed.",
        )
    return result


@router.get("/projects/{project_id}/diagnostics/icc/{item_id}")
async def get_item_icc(
    project_id: UUID,
    item_id: str,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get ICC data for a specific item.

    Returns the data needed to plot the Item Characteristic Curve.
    """
    result = await service.get_icc_data(project_id, item_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ICC data not found for item {item_id}",
        )
    return result


# --- Recommendations ---

@router.get("/projects/{project_id}/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    Get actionable recommendations for a project.

    Returns prioritized recommendations based on:
    - Item quality issues
    - Model fit concerns
    - Reliability thresholds

    Each recommendation includes:
    - What the issue is
    - Why it matters
    - What action to take
    """
    result = await service.get_recommendations(project_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recommendations found. Ensure model fitting has completed.",
        )
    return result


# --- Reports ---

# Report output directory
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/app/reports"))


@router.post("/projects/{project_id}/report", response_model=ReportResponse)
async def generate_report(
    project_id: UUID,
    request: ReportRequest,
    service: ProjectService = Depends(get_project_service),
):
    """
    Generate an exportable report.

    Creates a report in the requested format (PDF, HTML, JSON)
    containing:
    - Executive summary
    - Model selection justification
    - Item parameters
    - Diagnostic visualizations
    - Reproducibility metadata

    Returns a download URL for the generated report.
    """
    # Get project details
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Get results
    results = await service.get_results(project_id)
    if results is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No results found. Ensure model fitting has completed.",
        )

    # Get recommendations
    recommendations = await service.get_recommendations(project_id)

    # Get diagnostics for item data
    diagnostics = await service.get_diagnostics(project_id)

    # Build report data
    report_data = ReportData(
        project_id=str(project_id),
        project_name=project.name,
        project_description=project.description,
        stakes_level=project.stakes_level.value,
        intended_use=project.intended_use.value,
        n_respondents=0,  # Would need to get from dataset
        n_items=len(results.item_parameters),
        response_type="dichotomous",
        missing_percentage=0.0,
        recommended_model=results.comparison.recommended_model,
        models_compared=results.comparison.models_fitted,
        selection_reasons=results.comparison.selection_reasons,
        comparison_table=results.comparison.comparison_table,
        reliability_estimate=results.reliability_estimate,
        reliability_threshold=0.80,  # Default threshold
        reliability_acceptable=results.reliability_estimate >= 0.80,
        item_parameters=[
            {
                "item_id": p.item_id,
                "discrimination": p.discrimination,
                "difficulty": p.difficulty,
                "guessing": p.guessing,
                "status": "good",  # Would get from diagnostics
            }
            for p in results.item_parameters
        ],
        n_flagged_items=diagnostics.n_flagged if diagnostics else 0,
        flagged_items=[
            item.item_id
            for item in (diagnostics.items if diagnostics else [])
            if item.status in ("flagged", "problematic")
        ],
        recommendations=[
            {
                "priority": r.priority,
                "category": r.category,
                "title": r.title,
                "description": r.description,
                "action": r.action,
            }
            for r in (recommendations.recommendations if recommendations else [])
        ],
        overall_assessment=recommendations.overall_assessment if recommendations else "",
        is_ready_for_use=recommendations.is_ready_for_use if recommendations else False,
        generated_at=datetime.utcnow().isoformat(),
        software_version="0.1.0",
    )

    # Generate report
    generator = ReportGenerator(output_dir=REPORTS_DIR)
    format_str = request.format.value

    try:
        filepath = generator.save_report(report_data, format_str)
        filename = filepath.name
    except Exception as e:
        logger.exception("Error generating report")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating report: {str(e)}",
        )

    # Return response with download URL
    generated_at = datetime.utcnow()
    expires_at = generated_at + timedelta(hours=24)

    return ReportResponse(
        project_id=project_id,
        format=request.format,
        download_url=f"/api/v1/projects/{project_id}/report/{format_str}/{filename}",
        generated_at=generated_at,
        expires_at=expires_at,
    )


@router.get("/projects/{project_id}/report/{format}/{filename}")
async def download_report(
    project_id: UUID,
    format: str,
    filename: str,
):
    """
    Download a previously generated report.
    """
    filepath = REPORTS_DIR / filename

    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report file not found. It may have expired.",
        )

    # Determine content type
    content_types = {
        "pdf": "application/pdf",
        "html": "text/html",
        "json": "application/json",
    }
    content_type = content_types.get(format.lower(), "application/octet-stream")

    return FileResponse(
        path=filepath,
        media_type=content_type,
        filename=filename,
    )

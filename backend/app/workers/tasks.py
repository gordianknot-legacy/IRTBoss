"""
Background tasks for IRT model fitting.

These tasks run asynchronously to avoid blocking the API.
Uses Redis Queue (RQ) for job management.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..core.config import StakesLevel, IntendedUse, SAMPLE_SIZE
from ..core.model_selection import ModelSelector, ModelComparisonResult, IRTModel
from ..core.recommendations import RecommendationEngine, RecommendationReport
from ..core.diagnostics import DiagnosticsGenerator, TestDiagnostics
from ..irt.models import FittingResult, compute_reliability
from ..irt.mirt_wrapper import get_fitter
from ..db.models import FittingJob, ModelResult, ItemParameter, Project, Dataset

logger = logging.getLogger(__name__)

# Sync database URL (workers use sync engine)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://irtboss:irtboss_dev@localhost:5432/irtboss"
)
# Convert asyncpg URL to psycopg2 if needed
if "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")


def get_sync_db_session() -> Session:
    """Get a synchronous database session for workers."""
    engine = create_engine(DATABASE_URL)
    return Session(engine)


@dataclass
class FittingTaskResult:
    """
    Complete result of a model fitting task.

    Contains all outputs needed for the frontend:
    - Fitted models and comparison
    - Diagnostics
    - Recommendations
    - Reliability estimate
    """
    job_id: UUID
    project_id: UUID
    status: str  # "completed", "failed"
    completed_at: datetime

    # Fitting results
    fitting_results: Optional[dict[str, FittingResult]] = None
    comparison: Optional[ModelComparisonResult] = None
    selected_model_type: Optional[str] = None

    # Diagnostics
    diagnostics: Optional[TestDiagnostics] = None
    reliability: Optional[float] = None

    # Recommendations
    recommendations: Optional[RecommendationReport] = None

    # Metadata
    fitting_time_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def update_job_progress(
    session: Session,
    job_id: UUID,
    progress: float,
    current_model: Optional[str] = None,
    status: str = "running",
) -> None:
    """Update job progress in database."""
    job = session.get(FittingJob, job_id)
    if job:
        job.progress = progress
        job.current_model = current_model
        job.status = status
        if status == "running" and job.started_at is None:
            job.started_at = datetime.utcnow()
        session.commit()


def store_model_result(
    session: Session,
    job_id: UUID,
    model_type: str,
    fitting_result: FittingResult,
    is_recommended: bool,
    selection_reasons: list[str],
    reliability: Optional[float],
) -> ModelResult:
    """Store a model result in the database."""
    model = fitting_result.model
    if model is None:
        return None

    result = ModelResult(
        fitting_job_id=job_id,
        model_type=model_type,
        log_likelihood=model.fit_statistics.log_likelihood,
        aic=model.fit_statistics.aic,
        bic=model.fit_statistics.bic,
        n_parameters=model.fit_statistics.n_parameters,
        converged=model.fit_statistics.converged,
        reliability_estimate=reliability if is_recommended else None,
        is_recommended=is_recommended,
        selection_reasons=selection_reasons if is_recommended else [],
        warnings=fitting_result.warnings,
    )
    session.add(result)
    session.flush()

    # Store item parameters
    for idx, item_param in enumerate(model.item_parameters):
        param = ItemParameter(
            model_result_id=result.id,
            item_id=item_param.item_id,
            item_index=idx,
            discrimination=item_param.discrimination,
            difficulty=item_param.difficulty,
            guessing=item_param.guessing,
            se_discrimination=item_param.se_discrimination,
            se_difficulty=item_param.se_difficulty,
            se_guessing=item_param.se_guessing,
            status="good",  # Will be updated based on diagnostics
            flags=[],
        )
        session.add(param)

    return result


def fit_models_task(
    job_id: UUID,
    project_id: UUID,
    data: pd.DataFrame,
    stakes_level: str = "medium",
    intended_use: str = "operational",
    fit_3pl: bool = False,
    progress_callback=None,
) -> FittingTaskResult:
    """
    Main task for fitting IRT models.

    This is the entry point for background model fitting.
    It orchestrates the entire fitting, comparison, and recommendation pipeline.

    Args:
        job_id: Unique identifier for this job
        project_id: Project this job belongs to
        data: Response data (rows=respondents, columns=items)
        stakes_level: Assessment stakes level
        intended_use: Intended use of assessment
        fit_3pl: Whether to attempt 3PL fitting
        progress_callback: Optional callback for progress updates

    Returns:
        FittingTaskResult with complete analysis results
    """
    import time
    start_time = time.time()

    logger.info(f"Starting fitting task {job_id} for project {project_id}")

    # Convert string enums
    stakes = StakesLevel(stakes_level)
    use = IntendedUse(intended_use)

    # Get fitter
    fitter = get_fitter()

    # Report progress
    if progress_callback:
        progress_callback(job_id, 0.0, "Starting model fitting...")

    # Determine which models to fit based on sample size
    n_respondents = len(data)
    include_3pl = fit_3pl and n_respondents >= SAMPLE_SIZE.WARNING_RESPONDENTS_3PL

    if fit_3pl and not include_3pl:
        logger.warning(
            f"3PL requested but sample size ({n_respondents}) is too small. "
            f"Minimum: {SAMPLE_SIZE.WARNING_RESPONDENTS_3PL}"
        )

    # Fit models
    try:
        if progress_callback:
            progress_callback(job_id, 0.1, "Fitting 1PL (Rasch) model...")

        results = {}

        # Fit 1PL
        results[IRTModel.RASCH] = fitter.fit(data, IRTModel.RASCH)

        if progress_callback:
            progress_callback(job_id, 0.3, "Fitting 2PL model...")

        # Fit 2PL
        results[IRTModel.TWO_PL] = fitter.fit(data, IRTModel.TWO_PL)

        if include_3pl:
            if progress_callback:
                progress_callback(job_id, 0.5, "Fitting 3PL model...")
            results[IRTModel.THREE_PL] = fitter.fit(data, IRTModel.THREE_PL)

        if progress_callback:
            progress_callback(job_id, 0.6, "Comparing models...")

    except Exception as e:
        logger.exception("Error during model fitting")
        return FittingTaskResult(
            job_id=job_id,
            project_id=project_id,
            status="failed",
            completed_at=datetime.utcnow(),
            errors=[f"Model fitting failed: {str(e)}"],
            fitting_time_seconds=time.time() - start_time,
        )

    # Collect warnings from fitting
    warnings = []
    for model_type, result in results.items():
        warnings.extend(result.warnings)

    # Filter to successfully fitted models
    fitted_models = {
        k: v.model for k, v in results.items()
        if v.model is not None
    }

    if not fitted_models:
        return FittingTaskResult(
            job_id=job_id,
            project_id=project_id,
            status="failed",
            completed_at=datetime.utcnow(),
            errors=["No models converged successfully"],
            warnings=warnings,
            fitting_time_seconds=time.time() - start_time,
        )

    # Compare models and select best
    try:
        selector = ModelSelector(stakes=stakes, intended_use=use)
        comparison = selector.compare_models(fitted_models, n_respondents)
        selected_model = fitted_models[comparison.selected_model]

        if progress_callback:
            progress_callback(job_id, 0.7, "Generating diagnostics...")

    except Exception as e:
        logger.exception("Error during model comparison")
        return FittingTaskResult(
            job_id=job_id,
            project_id=project_id,
            status="failed",
            completed_at=datetime.utcnow(),
            errors=[f"Model comparison failed: {str(e)}"],
            warnings=warnings,
            fitting_time_seconds=time.time() - start_time,
        )

    # Generate diagnostics
    try:
        diag_generator = DiagnosticsGenerator()
        diagnostics = diag_generator.generate(selected_model)
        reliability = compute_reliability(selected_model)

        if progress_callback:
            progress_callback(job_id, 0.85, "Generating recommendations...")

    except Exception as e:
        logger.exception("Error generating diagnostics")
        diagnostics = None
        reliability = None
        warnings.append(f"Diagnostics generation failed: {str(e)}")

    # Generate recommendations
    try:
        rec_engine = RecommendationEngine(stakes=stakes, intended_use=use)
        recommendations = rec_engine.generate_recommendations(
            fitted_model=selected_model,
            comparison_result=comparison,
            reliability=reliability,
        )

        if progress_callback:
            progress_callback(job_id, 0.95, "Finalizing results...")

    except Exception as e:
        logger.exception("Error generating recommendations")
        recommendations = None
        warnings.append(f"Recommendations generation failed: {str(e)}")

    # Build final result
    fitting_time = time.time() - start_time

    if progress_callback:
        progress_callback(job_id, 1.0, "Complete")

    logger.info(
        f"Fitting task {job_id} completed in {fitting_time:.1f}s. "
        f"Selected model: {comparison.selected_model.value}"
    )

    return FittingTaskResult(
        job_id=job_id,
        project_id=project_id,
        status="completed",
        completed_at=datetime.utcnow(),
        fitting_results={k.value: v for k, v in results.items()},
        comparison=comparison,
        selected_model_type=comparison.selected_model.value,
        diagnostics=diagnostics,
        reliability=reliability,
        recommendations=recommendations,
        fitting_time_seconds=fitting_time,
        warnings=warnings,
    )


def rq_fit_models_task(
    job_id: str,
    project_id: str,
    stakes_level: str = "medium",
    intended_use: str = "operational",
    fit_3pl: bool = False,
) -> dict:
    """
    RQ-compatible wrapper for fit_models_task.

    This function is designed to be called by RQ workers.
    It handles:
    - Loading data from database
    - Progress updates via database
    - Storing results in database

    Args:
        job_id: Job ID as string
        project_id: Project ID as string
        stakes_level: Stakes level string
        intended_use: Intended use string
        fit_3pl: Whether to fit 3PL

    Returns:
        Dictionary with results summary
    """
    from uuid import UUID as UUIDClass

    job_uuid = UUIDClass(job_id)
    project_uuid = UUIDClass(project_id)

    # Get database session
    session = get_sync_db_session()

    try:
        # Update job status to running
        update_job_progress(session, job_uuid, 0.0, None, "running")

        # Load data from database
        dataset = session.query(Dataset).filter(
            Dataset.project_id == project_uuid,
            Dataset.is_valid == True
        ).order_by(Dataset.created_at.desc()).first()

        if not dataset:
            update_job_progress(session, job_uuid, 0.0, None, "failed")
            job = session.get(FittingJob, job_uuid)
            if job:
                job.error_message = "No valid dataset found for project"
                job.completed_at = datetime.utcnow()
                session.commit()
            return {"status": "failed", "error": "No valid dataset found"}

        # Load CSV data
        if dataset.file_path and os.path.exists(dataset.file_path):
            data = pd.read_csv(dataset.file_path)
        else:
            update_job_progress(session, job_uuid, 0.0, None, "failed")
            job = session.get(FittingJob, job_uuid)
            if job:
                job.error_message = "Dataset file not found"
                job.completed_at = datetime.utcnow()
                session.commit()
            return {"status": "failed", "error": "Dataset file not found"}

        # Progress callback that updates database
        def db_progress_callback(jid, progress, message):
            current_model = None
            if "1PL" in message:
                current_model = "1PL"
            elif "2PL" in message:
                current_model = "2PL"
            elif "3PL" in message:
                current_model = "3PL"
            update_job_progress(session, jid, progress, current_model)

        # Run fitting task
        result = fit_models_task(
            job_id=job_uuid,
            project_id=project_uuid,
            data=data,
            stakes_level=stakes_level,
            intended_use=intended_use,
            fit_3pl=fit_3pl,
            progress_callback=db_progress_callback,
        )

        # Store results in database
        if result.status == "completed" and result.fitting_results:
            for model_type, fitting_result in result.fitting_results.items():
                is_recommended = model_type == result.selected_model_type
                store_model_result(
                    session,
                    job_uuid,
                    model_type,
                    fitting_result,
                    is_recommended,
                    result.comparison.selection_reasons if result.comparison else [],
                    result.reliability if is_recommended else None,
                )

        # Update final job status
        job = session.get(FittingJob, job_uuid)
        if job:
            job.status = result.status
            job.progress = 1.0 if result.status == "completed" else job.progress
            job.completed_at = result.completed_at
            if result.errors:
                job.error_message = "; ".join(result.errors)

        # Update project status
        project = session.get(Project, project_uuid)
        if project:
            project.status = "completed" if result.status == "completed" else "failed"
            project.updated_at = datetime.utcnow()

        session.commit()

        # Return summary
        return {
            "job_id": str(result.job_id),
            "project_id": str(result.project_id),
            "status": result.status,
            "completed_at": result.completed_at.isoformat(),
            "selected_model_type": result.selected_model_type,
            "reliability": result.reliability,
            "fitting_time_seconds": result.fitting_time_seconds,
            "errors": result.errors,
            "warnings": result.warnings,
        }

    except Exception as e:
        logger.exception(f"Error in rq_fit_models_task: {e}")
        # Update job as failed
        try:
            job = session.get(FittingJob, job_uuid)
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
            session.commit()
        except Exception:
            pass
        return {"status": "failed", "error": str(e)}

    finally:
        session.close()


def enqueue_fitting_job(
    job_id: UUID,
    project_id: UUID,
    stakes_level: str = "medium",
    intended_use: str = "operational",
    fit_3pl: bool = False,
) -> bool:
    """
    Enqueue a fitting job to Redis Queue.

    Args:
        job_id: The fitting job ID
        project_id: The project ID
        stakes_level: Stakes level
        intended_use: Intended use
        fit_3pl: Whether to fit 3PL

    Returns:
        True if job was enqueued successfully
    """
    import redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    try:
        redis_conn = redis.from_url(redis_url)
        queue = Queue("irtboss", connection=redis_conn)

        queue.enqueue(
            rq_fit_models_task,
            job_id=str(job_id),
            project_id=str(project_id),
            stakes_level=stakes_level,
            intended_use=intended_use,
            fit_3pl=fit_3pl,
            job_timeout="30m",  # Allow up to 30 minutes for fitting
        )

        logger.info(f"Enqueued fitting job {job_id} for project {project_id}")
        return True

    except Exception as e:
        logger.exception(f"Failed to enqueue fitting job: {e}")
        return False

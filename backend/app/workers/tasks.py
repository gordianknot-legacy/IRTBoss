"""
Background tasks for IRT model fitting.

These tasks run asynchronously to avoid blocking the API.
Uses Redis Queue (RQ) for job management.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

import pandas as pd

from ..core.config import StakesLevel, IntendedUse, SAMPLE_SIZE
from ..core.model_selection import ModelSelector, ModelComparisonResult, IRTModel
from ..core.recommendations import RecommendationEngine, RecommendationReport
from ..core.diagnostics import DiagnosticsGenerator, TestDiagnostics
from ..irt.models import FittingResult, compute_reliability
from ..irt.mirt_wrapper import get_fitter

logger = logging.getLogger(__name__)


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


# RQ task wrapper (for use with Redis Queue)
def rq_fit_models_task(
    job_id: str,
    project_id: str,
    data_path: str,
    stakes_level: str = "medium",
    intended_use: str = "operational",
    fit_3pl: bool = False,
) -> dict:
    """
    RQ-compatible wrapper for fit_models_task.

    This function is designed to be called by RQ workers.
    It handles serialization of inputs/outputs.

    Args:
        job_id: Job ID as string
        project_id: Project ID as string
        data_path: Path to CSV file with response data
        stakes_level: Stakes level string
        intended_use: Intended use string
        fit_3pl: Whether to fit 3PL

    Returns:
        Dictionary with results (serializable)
    """
    from uuid import UUID

    # Load data
    data = pd.read_csv(data_path)

    # Run task
    result = fit_models_task(
        job_id=UUID(job_id),
        project_id=UUID(project_id),
        data=data,
        stakes_level=stakes_level,
        intended_use=intended_use,
        fit_3pl=fit_3pl,
    )

    # Convert to serializable dict
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
        # Note: Full objects would need custom serialization
    }

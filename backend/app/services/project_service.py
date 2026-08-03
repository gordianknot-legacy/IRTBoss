"""
Project service layer for IRTBoss.

Handles all project-related business logic and database operations.
"""

import hashlib
import io
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..api.schemas import (
    DataSummary,
    DiagnosticsResponse,
    FittedModelSummary,
    FitStatistics,
    ICCDataPoint,
    ICCResponse,
    ItemDiagnosticSummary,
    ItemParameter as ItemParameterSchema,
    ModelComparisonSummary,
    ModelResultResponse,
    ModelType,
    ProjectCreate,
    ProjectResponse,
    RecommendationItem,
    RecommendationsResponse,
    ResponseType,
    StakesLevel,
    IntendedUse,
    TIFDataPoint,
    TIFResponse,
    UploadResponse,
    ValidationMessage,
)
from ..core.data_validation import DataValidator, ResponseType as CoreResponseType
from ..core.config import MODEL_FIT, get_reliability_threshold
from ..db.models import Dataset, FittingJob, ModelResult, ItemParameter, Project

logger = logging.getLogger(__name__)

# Upload directory
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))


class ProjectService:
    """Service for managing projects."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._validator = DataValidator()

    async def create_project(self, project_data: ProjectCreate) -> ProjectResponse:
        """Create a new project."""
        project = Project(
            name=project_data.name,
            description=project_data.description,
            stakes_level=project_data.stakes_level.value,
            intended_use=project_data.intended_use.value,
            status="created",
        )

        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)

        return self._to_response(project)

    async def get_project(self, project_id: UUID) -> Optional[ProjectResponse]:
        """Get a project by ID."""
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if project is None:
            return None

        return self._to_response(project)

    async def list_projects(self, limit: int = 20, offset: int = 0) -> list[ProjectResponse]:
        """List all projects with pagination."""
        result = await self.db.execute(
            select(Project)
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        projects = result.scalars().all()

        return [self._to_response(p) for p in projects]

    async def upload_data(
        self,
        project_id: UUID,
        filename: str,
        content: bytes,
    ) -> UploadResponse:
        """
        Upload and validate response data for a project.

        Args:
            project_id: The project ID
            filename: Original filename
            content: File content as bytes

        Returns:
            UploadResponse with validation results
        """
        messages: list[ValidationMessage] = []

        # Check project exists
        project = await self.db.get(Project, project_id)
        if project is None:
            return UploadResponse(
                is_valid=False,
                summary=None,
                messages=[
                    ValidationMessage(
                        severity="error",
                        code="PROJECT_NOT_FOUND",
                        message=f"Project {project_id} not found",
                    )
                ],
            )

        # Parse CSV content
        try:
            df = pd.read_csv(io.BytesIO(content))
        except pd.errors.EmptyDataError:
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
        except pd.errors.ParserError as e:
            return UploadResponse(
                is_valid=False,
                summary=None,
                messages=[
                    ValidationMessage(
                        severity="error",
                        code="PARSE_ERROR",
                        message="Could not parse CSV file",
                        details=str(e),
                    )
                ],
            )
        except Exception as e:
            logger.exception("Error parsing CSV file")
            return UploadResponse(
                is_valid=False,
                summary=None,
                messages=[
                    ValidationMessage(
                        severity="error",
                        code="PROCESSING_ERROR",
                        message="Error processing file",
                        details=str(e),
                    )
                ],
            )

        # Run validation
        validation_result = self._validator.validate_dataframe(df)

        # Convert validation messages to API format
        for msg in validation_result.messages:
            messages.append(
                ValidationMessage(
                    severity=msg.severity.value,
                    code=msg.code,
                    message=msg.message,
                    details=msg.details,
                    affected_items=msg.affected_items,
                )
            )

        if not validation_result.is_valid:
            return UploadResponse(
                is_valid=False,
                summary=None,
                messages=messages,
            )

        # Create data summary for API
        summary = validation_result.summary
        api_summary = DataSummary(
            n_respondents=summary.n_respondents,
            n_items=summary.n_items,
            response_type=(
                ResponseType.DICHOTOMOUS
                if summary.response_type == CoreResponseType.DICHOTOMOUS
                else ResponseType.POLYTOMOUS
            ),
            n_categories=summary.n_categories,
            missing_percentage=summary.missing_percentage,
            item_names=summary.item_names,
        )

        # Calculate file hash for reproducibility
        file_hash = hashlib.sha256(content).hexdigest()

        # Save file to disk (if configured)
        file_path = None
        if UPLOAD_DIR.exists():
            file_path = str(UPLOAD_DIR / f"{project_id}_{file_hash[:8]}.csv")
            try:
                with open(file_path, "wb") as f:
                    f.write(content)
            except Exception as e:
                logger.warning(f"Could not save upload file: {e}")
                file_path = None

        # Store dataset in database
        dataset = Dataset(
            project_id=project_id,
            filename=filename,
            file_path=file_path,
            file_hash=file_hash,
            n_respondents=summary.n_respondents,
            n_items=summary.n_items,
            response_type=summary.response_type.value,
            n_categories=summary.n_categories,
            missing_percentage=summary.missing_percentage,
            item_names=summary.item_names,
            is_valid=True,
            validation_messages=[m.model_dump() for m in messages],
        )

        self.db.add(dataset)

        # Update project status
        project.status = "data_uploaded"
        project.updated_at = datetime.utcnow()

        await self.db.flush()

        # Add success message
        messages.append(
            ValidationMessage(
                severity="info",
                code="UPLOAD_SUCCESS",
                message="Data uploaded and validated successfully",
                details=f"Found {summary.n_respondents} respondents and {summary.n_items} items",
            )
        )

        return UploadResponse(
            is_valid=True,
            summary=api_summary,
            messages=messages,
        )

    async def start_fitting(
        self,
        project_id: UUID,
        fit_1pl: bool = True,
        fit_2pl: bool = True,
        fit_3pl: bool = False,
    ) -> Optional[FittingJob]:
        """
        Start model fitting for a project.

        Returns the created FittingJob, or None if project not found.
        """
        project = await self.db.get(Project, project_id)
        if project is None:
            return None

        # Create fitting job
        job = FittingJob(
            project_id=project_id,
            fit_1pl=fit_1pl,
            fit_2pl=fit_2pl,
            fit_3pl=fit_3pl,
            status="pending",
            progress=0.0,
        )

        self.db.add(job)

        # Update project status
        project.status = "fitting"
        project.updated_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(job)

        return job

    async def get_job(self, job_id: UUID) -> Optional[FittingJob]:
        """Get a fitting job by ID."""
        result = await self.db.execute(
            select(FittingJob)
            .where(FittingJob.id == job_id)
            .options(selectinload(FittingJob.results))
        )
        return result.scalar_one_or_none()

    async def get_project_dataset(self, project_id: UUID) -> Optional[Dataset]:
        """Get the most recent dataset for a project."""
        result = await self.db.execute(
            select(Dataset)
            .where(Dataset.project_id == project_id)
            .where(Dataset.is_valid == True)
            .order_by(Dataset.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _to_response(self, project: Project) -> ProjectResponse:
        """Convert a Project model to ProjectResponse schema."""
        return ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            stakes_level=StakesLevel(project.stakes_level),
            intended_use=IntendedUse(project.intended_use),
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    async def get_results(self, project_id: UUID) -> Optional[ModelResultResponse]:
        """Get model fitting results for a project."""
        # Get the latest completed fitting job
        result = await self.db.execute(
            select(FittingJob)
            .where(FittingJob.project_id == project_id)
            .where(FittingJob.status == "completed")
            .order_by(FittingJob.completed_at.desc())
            .limit(1)
            .options(selectinload(FittingJob.results).selectinload(ModelResult.item_parameters))
        )
        job = result.scalar_one_or_none()

        if job is None or not job.results:
            return None

        # Find recommended model
        recommended = next((r for r in job.results if r.is_recommended), job.results[0])

        # Build comparison summary
        models_fitted = [ModelType(r.model_type) for r in job.results]
        comparison_table = {}
        for r in job.results:
            comparison_table[r.model_type] = {
                "log_likelihood": r.log_likelihood,
                "aic": r.aic,
                "bic": r.bic,
                "n_parameters": r.n_parameters,
            }

        comparison = ModelComparisonSummary(
            models_fitted=models_fitted,
            recommended_model=ModelType(recommended.model_type),
            selection_reasons=recommended.selection_reasons or [],
            comparison_table=comparison_table,
        )

        # Build selected model summary
        selected_model = FittedModelSummary(
            model_type=ModelType(recommended.model_type),
            fit_stats=FitStatistics(
                log_likelihood=recommended.log_likelihood,
                aic=recommended.aic,
                bic=recommended.bic,
                n_parameters=recommended.n_parameters,
                converged=recommended.converged,
            ),
            n_items=len(recommended.item_parameters),
            warnings=recommended.warnings or [],
        )

        # Build item parameters
        item_params = [
            ItemParameterSchema(
                item_id=p.item_id,
                discrimination=p.discrimination,
                difficulty=p.difficulty,
                guessing=p.guessing,
                se_discrimination=p.se_discrimination,
                se_difficulty=p.se_difficulty,
                se_guessing=p.se_guessing,
            )
            for p in sorted(recommended.item_parameters, key=lambda x: x.item_index)
        ]

        return ModelResultResponse(
            project_id=project_id,
            comparison=comparison,
            selected_model=selected_model,
            item_parameters=item_params,
            reliability_estimate=recommended.reliability_estimate or 0.0,
        )

    async def get_diagnostics(self, project_id: UUID) -> Optional[DiagnosticsResponse]:
        """Get diagnostic information for a project."""
        # Get the latest completed fitting job with recommended model
        result = await self.db.execute(
            select(FittingJob)
            .where(FittingJob.project_id == project_id)
            .where(FittingJob.status == "completed")
            .order_by(FittingJob.completed_at.desc())
            .limit(1)
            .options(selectinload(FittingJob.results).selectinload(ModelResult.item_parameters))
        )
        job = result.scalar_one_or_none()

        if job is None or not job.results:
            return None

        # Find recommended model
        recommended = next((r for r in job.results if r.is_recommended), job.results[0])

        # Generate TIF data
        tif_data = self._generate_tif_data(recommended.item_parameters)

        # Find peak and coverage
        peak_idx = max(range(len(tif_data)), key=lambda i: tif_data[i].information)
        peak_theta = tif_data[peak_idx].theta
        peak_information = tif_data[peak_idx].information

        # Find coverage range (where information > 1.0)
        coverage_low = -4.0
        coverage_high = 4.0
        for dp in tif_data:
            if dp.information >= 1.0:
                coverage_low = dp.theta
                break
        for dp in reversed(tif_data):
            if dp.information >= 1.0:
                coverage_high = dp.theta
                break

        tif = TIFResponse(
            data=tif_data,
            peak_theta=peak_theta,
            peak_information=peak_information,
            coverage_low=coverage_low,
            coverage_high=coverage_high,
        )

        # Build item diagnostics
        items = []
        n_flagged = 0
        for p in sorted(recommended.item_parameters, key=lambda x: x.item_index):
            # Determine status based on parameters
            status = "good"
            flags = list(p.flags) if p.flags else []

            if p.discrimination < MODEL_FIT.MIN_DISCRIMINATION:
                status = "flagged"
                if "LOW_DISCRIMINATION" not in flags:
                    flags.append("LOW_DISCRIMINATION")
            elif p.discrimination > MODEL_FIT.MAX_DISCRIMINATION:
                status = "flagged"
                if "HIGH_DISCRIMINATION" not in flags:
                    flags.append("HIGH_DISCRIMINATION")

            if abs(p.difficulty) > 3.5:
                if status == "good":
                    status = "acceptable"
                if "EXTREME_DIFFICULTY" not in flags:
                    flags.append("EXTREME_DIFFICULTY")

            if status in ("flagged", "problematic"):
                n_flagged += 1

            # Calculate max information for this item
            max_info = self._item_max_info(p.discrimination, p.difficulty, p.guessing)

            items.append(ItemDiagnosticSummary(
                item_id=p.item_id,
                status=status,
                discrimination=p.discrimination,
                difficulty=p.difficulty,
                guessing=p.guessing,
                max_information=max_info,
                flags=flags,
            ))

        return DiagnosticsResponse(
            project_id=project_id,
            tif=tif,
            items=items,
            reliability=recommended.reliability_estimate or 0.0,
            n_flagged=n_flagged,
        )

    async def get_recommendations(self, project_id: UUID) -> Optional[RecommendationsResponse]:
        """Get recommendations for a project."""
        # Get project info
        project = await self.db.get(Project, project_id)
        if project is None:
            return None

        # Get diagnostics data
        diagnostics = await self.get_diagnostics(project_id)
        if diagnostics is None:
            return None

        from ..core.config import StakesLevel as CoreStakesLevel

        stakes = StakesLevel(project.stakes_level)
        reliability_threshold = get_reliability_threshold(CoreStakesLevel(stakes.value))

        recommendations = []

        # Check reliability
        if diagnostics.reliability < reliability_threshold:
            recommendations.append(RecommendationItem(
                priority="critical" if stakes == StakesLevel.HIGH else "high",
                category="Reliability",
                title="Reliability below threshold",
                description=(
                    f"The estimated reliability ({diagnostics.reliability:.2f}) is below "
                    f"the threshold ({reliability_threshold:.2f}) for {stakes.value} stakes assessments."
                ),
                action="Consider adding more items or reviewing low-discrimination items.",
                affected_items=[],
            ))

        # Check flagged items
        flagged_items = [i for i in diagnostics.items if i.status in ("flagged", "problematic")]
        if flagged_items:
            recommendations.append(RecommendationItem(
                priority="high" if len(flagged_items) > 3 else "medium",
                category="Item Quality",
                title=f"{len(flagged_items)} items flagged for review",
                description=(
                    "These items have parameter values outside typical ranges, "
                    "which may indicate poor discrimination or extreme difficulty."
                ),
                action="Review and consider revising or removing flagged items.",
                affected_items=[i.item_id for i in flagged_items],
            ))

        # Check coverage
        coverage_range = diagnostics.tif.coverage_high - diagnostics.tif.coverage_low
        if coverage_range < 3.0:
            recommendations.append(RecommendationItem(
                priority="medium",
                category="Test Information",
                title="Limited ability coverage",
                description=(
                    f"The test provides adequate information only for a narrow ability range "
                    f"({diagnostics.tif.coverage_low:.1f} to {diagnostics.tif.coverage_high:.1f})."
                ),
                action="Consider adding items with different difficulty levels to broaden coverage.",
                affected_items=[],
            ))

        # Determine overall assessment
        if diagnostics.reliability >= reliability_threshold and diagnostics.n_flagged <= 2:
            overall = "The assessment demonstrates acceptable psychometric properties."
            ready = True
        elif diagnostics.reliability >= reliability_threshold * 0.9:
            overall = "The assessment shows adequate properties but some items need review."
            ready = stakes != StakesLevel.HIGH
        else:
            overall = "The assessment requires revision before operational use."
            ready = False

        return RecommendationsResponse(
            project_id=project_id,
            overall_assessment=overall,
            is_ready_for_use=ready,
            reliability=diagnostics.reliability,
            recommendations=recommendations,
        )

    def _generate_tif_data(self, item_params: list[ItemParameter]) -> list[TIFDataPoint]:
        """Generate Test Information Function data."""
        import numpy as np

        theta_range = np.linspace(-4, 4, 81)
        tif_data = []

        for theta in theta_range:
            total_info = 0.0
            for p in item_params:
                a = p.discrimination
                b = p.difficulty
                c = p.guessing

                # Calculate item information
                z = a * (theta - b)
                exp_neg_z = np.exp(-z)
                prob = c + (1 - c) / (1 + exp_neg_z)

                if prob > c and prob < 1:
                    info = (a ** 2 * (prob - c) ** 2 * (1 - prob)) / ((1 - c) ** 2 * prob)
                    total_info += info

            se = 1 / np.sqrt(total_info) if total_info > 0 else 10.0

            tif_data.append(TIFDataPoint(
                theta=float(theta),
                information=float(total_info),
                standard_error=float(min(se, 10.0)),
            ))

        return tif_data

    def _item_max_info(self, a: float, b: float, c: float) -> float:
        """Calculate maximum information for an item."""
        import numpy as np

        # For 2PL/3PL, max info is at theta where P = (1+c)/2
        # Information = a^2 * (P-c)^2 * (1-P) / ((1-c)^2 * P)
        # For 2PL (c=0): max at theta=b, info = a^2 * 0.25
        if c < 0.01:
            return a ** 2 * 0.25
        else:
            # Approximate max info for 3PL
            p_max = (1 + c) / 2
            return (a ** 2 * (p_max - c) ** 2 * (1 - p_max)) / ((1 - c) ** 2 * p_max)

    async def get_icc_data(self, project_id: UUID, item_id: str) -> Optional[ICCResponse]:
        """Get ICC data for a specific item."""
        import numpy as np

        # Get diagnostics to find the item
        diagnostics = await self.get_diagnostics(project_id)
        if diagnostics is None:
            return None

        item = next((i for i in diagnostics.items if i.item_id == item_id), None)
        if item is None:
            return None

        # Generate ICC data
        theta_range = np.linspace(-4, 4, 81)
        data = []

        a = item.discrimination
        b = item.difficulty
        c = item.guessing

        for theta in theta_range:
            z = a * (theta - b)
            exp_neg_z = np.exp(-z)
            prob = c + (1 - c) / (1 + exp_neg_z)

            if prob > c and prob < 1:
                info = (a ** 2 * (prob - c) ** 2 * (1 - prob)) / ((1 - c) ** 2 * prob)
            else:
                info = 0.0

            data.append(ICCDataPoint(
                theta=float(theta),
                probability=float(prob),
                information=float(info),
            ))

        return ICCResponse(
            item_id=item_id,
            data=data,
            difficulty=b,
            discrimination=a,
        )

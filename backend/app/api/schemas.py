"""
Pydantic schemas for API request/response validation.

These schemas define the contract between the frontend and backend,
ensuring type safety and validation at API boundaries.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class StakesLevel(str, Enum):
    """Stakes level for the assessment."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntendedUse(str, Enum):
    """Intended use of the assessment."""
    RESEARCH = "research"
    OPERATIONAL = "operational"
    CERTIFICATION = "certification"


class ResponseType(str, Enum):
    """Type of response data."""
    DICHOTOMOUS = "dichotomous"
    POLYTOMOUS = "polytomous"


class JobStatus(str, Enum):
    """Status of an async fitting job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelType(str, Enum):
    """IRT model type."""
    RASCH = "1PL"
    TWO_PL = "2PL"
    THREE_PL = "3PL"


class ReportFormat(str, Enum):
    """Output format for reports."""
    PDF = "pdf"
    HTML = "html"
    JSON = "json"


# --- Project Schemas ---

class ProjectCreate(BaseModel):
    """Request schema for creating a new project."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    stakes_level: StakesLevel = StakesLevel.MEDIUM
    intended_use: IntendedUse = IntendedUse.OPERATIONAL


class ProjectResponse(BaseModel):
    """Response schema for project details."""
    id: UUID
    name: str
    description: Optional[str]
    stakes_level: StakesLevel
    intended_use: IntendedUse
    status: str  # "created", "data_uploaded", "fitting", "completed"
    created_at: datetime
    updated_at: datetime


# --- Upload Schemas ---

class ValidationMessage(BaseModel):
    """A single validation message."""
    severity: str  # "info", "warning", "error"
    code: str
    message: str
    details: Optional[str] = None
    affected_items: Optional[list[str]] = None


class DataSummary(BaseModel):
    """Summary of uploaded data."""
    n_respondents: int
    n_items: int
    response_type: ResponseType
    n_categories: int
    missing_percentage: float
    item_names: list[str]


class UploadResponse(BaseModel):
    """Response after uploading data."""
    is_valid: bool
    summary: Optional[DataSummary]
    messages: list[ValidationMessage]


# --- Model Fitting Schemas ---

class FittingJobCreate(BaseModel):
    """Request to start model fitting."""
    project_id: UUID
    fit_1pl: bool = True
    fit_2pl: bool = True
    fit_3pl: bool = False  # Only when sample size permits


class FittingJobResponse(BaseModel):
    """Response for a fitting job."""
    job_id: UUID
    project_id: UUID
    status: JobStatus
    progress: float = Field(ge=0, le=1)  # 0 to 1
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class FittingProgress(BaseModel):
    """Progress update for model fitting."""
    job_id: UUID
    status: JobStatus
    progress: float
    current_model: Optional[str] = None
    message: Optional[str] = None


# --- Model Results Schemas ---

class ItemParameter(BaseModel):
    """Item parameters from fitted model."""
    item_id: str
    discrimination: float
    difficulty: float
    guessing: float = 0.0
    se_discrimination: Optional[float] = None
    se_difficulty: Optional[float] = None
    se_guessing: Optional[float] = None


class FitStatistics(BaseModel):
    """Model fit statistics."""
    log_likelihood: float
    aic: float
    bic: float
    n_parameters: int
    converged: bool


class FittedModelSummary(BaseModel):
    """Summary of a fitted model."""
    model_type: ModelType
    fit_stats: FitStatistics
    n_items: int
    warnings: list[str] = []


class ModelComparisonSummary(BaseModel):
    """Summary of model comparison."""
    models_fitted: list[ModelType]
    recommended_model: ModelType
    selection_reasons: list[str]
    comparison_table: dict[str, dict[str, float]]


class ModelResultResponse(BaseModel):
    """Complete model fitting results."""
    project_id: UUID
    comparison: ModelComparisonSummary
    selected_model: FittedModelSummary
    item_parameters: list[ItemParameter]
    reliability_estimate: float


# --- Diagnostics Schemas ---

class ICCDataPoint(BaseModel):
    """Data point for ICC visualization."""
    theta: float
    probability: float
    information: float


class ICCResponse(BaseModel):
    """ICC data for an item."""
    item_id: str
    data: list[ICCDataPoint]
    difficulty: float
    discrimination: float


class TIFDataPoint(BaseModel):
    """Data point for TIF visualization."""
    theta: float
    information: float
    standard_error: float


class TIFResponse(BaseModel):
    """Test Information Function data."""
    data: list[TIFDataPoint]
    peak_theta: float
    peak_information: float
    coverage_low: float
    coverage_high: float


class ItemDiagnosticSummary(BaseModel):
    """Summary diagnostics for an item."""
    item_id: str
    status: str  # "good", "acceptable", "flagged", "problematic"
    discrimination: float
    difficulty: float
    guessing: float
    max_information: float
    flags: list[str]


class DiagnosticsResponse(BaseModel):
    """Complete diagnostics response."""
    project_id: UUID
    tif: TIFResponse
    items: list[ItemDiagnosticSummary]
    reliability: float
    n_flagged: int


# --- Recommendations Schemas ---

class RecommendationItem(BaseModel):
    """A single recommendation."""
    priority: str  # "critical", "high", "medium", "low"
    category: str
    title: str
    description: str
    action: str
    affected_items: list[str] = []


class RecommendationsResponse(BaseModel):
    """Complete recommendations response."""
    project_id: UUID
    overall_assessment: str
    is_ready_for_use: bool
    reliability: Optional[float]
    recommendations: list[RecommendationItem]


# --- Report Schemas ---

class ReportRequest(BaseModel):
    """Request to generate a report."""
    project_id: UUID
    format: ReportFormat
    include_technical_appendix: bool = True
    include_item_details: bool = True


class ReportResponse(BaseModel):
    """Response with generated report."""
    project_id: UUID
    format: ReportFormat
    download_url: str
    generated_at: datetime
    expires_at: datetime


# --- Reproducibility Schemas ---

class ReproducibilityMetadata(BaseModel):
    """Metadata for reproducibility."""
    project_id: UUID
    software_version: str
    model_type: str
    fitting_timestamp: datetime
    data_hash: str  # Hash of input data
    random_seed: Optional[int]
    convergence_settings: dict

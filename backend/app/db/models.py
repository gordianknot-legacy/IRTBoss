"""
SQLAlchemy models for IRTBoss.

These models represent the core domain entities persisted in the database.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Project(Base):
    """
    An assessment project - the top-level container for an IRT analysis.

    Projects store the context (stakes level, intended use) which affects
    the recommendations and thresholds applied during analysis.
    """
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stakes_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium"
    )  # low, medium, high
    intended_use: Mapped[str] = mapped_column(
        String(20), nullable=False, default="operational"
    )  # research, operational, certification
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="created"
    )  # created, data_uploaded, fitting, completed, failed

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    datasets: Mapped[list["Dataset"]] = relationship(
        "Dataset", back_populates="project", cascade="all, delete-orphan"
    )
    fitting_jobs: Mapped[list["FittingJob"]] = relationship(
        "FittingJob", back_populates="project", cascade="all, delete-orphan"
    )


class Dataset(Base):
    """
    Uploaded response data for a project.

    Stores both the validated data and metadata about the data
    (number of respondents, items, response type, etc.).
    """
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # File info
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=True)  # Path to stored file
    file_hash: Mapped[str] = mapped_column(String(64), nullable=True)  # SHA256 for reproducibility

    # Data summary
    n_respondents: Mapped[int] = mapped_column(Integer, nullable=False)
    n_items: Mapped[int] = mapped_column(Integer, nullable=False)
    response_type: Mapped[str] = mapped_column(String(20), nullable=False)  # dichotomous, polytomous
    n_categories: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    missing_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    item_names: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Validation info
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_messages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="datasets")


class FittingJob(Base):
    """
    A background job for fitting IRT models.

    Tracks the status and progress of model fitting tasks.
    """
    __tablename__ = "fitting_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # Job configuration
    fit_1pl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fit_2pl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fit_3pl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, running, completed, failed
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_model: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="fitting_jobs")
    results: Mapped[list["ModelResult"]] = relationship(
        "ModelResult", back_populates="fitting_job", cascade="all, delete-orphan"
    )


class ModelResult(Base):
    """
    Results from fitting a single IRT model.

    Contains fit statistics and the recommended model flag.
    """
    __tablename__ = "model_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fitting_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fitting_jobs.id", ondelete="CASCADE"), nullable=False
    )

    # Model identification
    model_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 1PL, 2PL, 3PL

    # Fit statistics
    log_likelihood: Mapped[float] = mapped_column(Float, nullable=False)
    aic: Mapped[float] = mapped_column(Float, nullable=False)
    bic: Mapped[float] = mapped_column(Float, nullable=False)
    n_parameters: Mapped[int] = mapped_column(Integer, nullable=False)
    converged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Reliability
    reliability_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Selection
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selection_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Warnings
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    fitting_job: Mapped["FittingJob"] = relationship("FittingJob", back_populates="results")
    item_parameters: Mapped[list["ItemParameter"]] = relationship(
        "ItemParameter", back_populates="model_result", cascade="all, delete-orphan"
    )


class ItemParameter(Base):
    """
    Item parameters from a fitted model.

    Stores discrimination, difficulty, and guessing parameters along with
    their standard errors and diagnostic flags.
    """
    __tablename__ = "item_parameters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_results.id", ondelete="CASCADE"), nullable=False
    )

    # Item identification
    item_id: Mapped[str] = mapped_column(String(100), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)  # Order in original data

    # Parameters
    discrimination: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False)
    guessing: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Standard errors
    se_discrimination: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    se_difficulty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    se_guessing: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Diagnostics
    max_information: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="good"
    )  # good, acceptable, flagged, problematic
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Relationships
    model_result: Mapped["ModelResult"] = relationship("ModelResult", back_populates="item_parameters")

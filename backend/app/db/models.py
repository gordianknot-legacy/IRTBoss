"""Persistence schema.

The shape of this schema is a direct response to two v1 defects.

**Ownership is structural, not procedural.** Every row a user can reach carries
an ``owner_id``, including the rows that could have been reached by joining
through their parent. v1 had no authentication at all and resolved reports by
guessable filename (P5); the fix is not "remember to check the owner in the
route" but a schema where the owner is a column on the row being fetched, so the
repository layer can filter on it in a single predicate and the check cannot be
forgotten one route at a time.

**Nothing stores a number the engine did not produce.** :class:`ModelFit` mirrors
:class:`app.irt.FitResult`, where an unconverged fit carries no parameters and
``log_likelihood`` is ``None``. The columns are nullable for the same reason the
dataclass fields are optional: a non-converged fit must be storable as
non-converged, not as zeros that read like measurements downstream (P0/P4).

Type portability: UUID and JSON use SQLAlchemy's generic types with a
PostgreSQL variant, so production gets ``uuid``/``jsonb`` while the test suite
runs on SQLite. Enums are emitted as ``VARCHAR`` + ``CHECK`` (``native_enum=
False``) so that adding a status value is an ordinary migration rather than a
PostgreSQL ``ALTER TYPE``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB where it exists, JSON everywhere else. The payloads here are read whole
# and never queried by key, so the fallback loses nothing but indexability.
JSONType = JSON().with_variant(JSONB, "postgresql")


def _values(enum_cls: type[enum.Enum]) -> list[str]:
    """Persist enum *values*, not member names.

    Without this SQLAlchemy stores ``"MEDIUM"`` while the API speaks
    ``"medium"``, and the two only diverge once a raw SQL query appears.
    """

    return [member.value for member in enum_cls]


class Base(DeclarativeBase):
    """Declarative base. Alembic autogenerate targets ``Base.metadata``."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunStatus(str, enum.Enum):
    """Lifecycle of an analysis run.

    The row is written as ``QUEUED`` *before* the job is handed to Redis, so a
    run that never reaches a worker is visible as a stuck queued row rather than
    silently absent. v1's dispatcher had no call sites at all and nothing in the
    schema could have revealed it (P0.1).
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StakesLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntendedUse(str, enum.Enum):
    RESEARCH = "research"
    OPERATIONAL = "operational"
    CERTIFICATION = "certification"


class User(Base):
    """An account. The only entity not owned by another entity."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Stored lower-cased by the repository so uniqueness is not defeated by
    # casing; a functional index would be PostgreSQL-only.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    # Argon2id encoded hash (``$argon2id$v=19$...``). Never logged, never
    # serialised into a response schema.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set when the account revokes its sessions. Every token signed before this
    # instant is rejected on read, which is how "log out everywhere" works with no
    # server-side session table: one timestamp per account instead of one row per
    # session. The cost is that it is all-or-nothing — there is no way to end one
    # device's session and keep another's.
    sessions_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()

    projects: Mapped[list[Project]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )


class Project(Base):
    """A body of work: one assessment, its data, and its analyses.

    ``stakes_level`` and ``intended_use`` are not decoration — the reporting
    thresholds a psychometrician would apply differ between a classroom quiz and
    a licensure exam, so they are declared up front and carried into the report.
    """

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stakes_level: Mapped[StakesLevel] = mapped_column(
        SAEnum(StakesLevel, native_enum=False, length=20, values_callable=_values),
        nullable=False,
        default=StakesLevel.MEDIUM,
    )
    intended_use: Mapped[IntendedUse] = mapped_column(
        SAEnum(IntendedUse, native_enum=False, length=20, values_callable=_values),
        nullable=False,
        default=IntendedUse.OPERATIONAL,
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner: Mapped[User] = relationship(back_populates="projects")
    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class Dataset(Base):
    """An uploaded response matrix.

    ``owner_id`` is duplicated from the parent project deliberately. Ownership
    filtering then costs one predicate on the table being read instead of a join
    that a future query might omit — the same reasoning applies to
    :class:`AnalysisRun`.

    ``checksum_sha256`` is over the raw bytes as received. Together with the run
    seed and engine version it is what makes a report reproducible rather than
    merely repeatable (P4).
    """

    __tablename__ = "datasets"
    __table_args__ = (
        Index("ix_datasets_owner_created", "owner_id", "created_at"),
        CheckConstraint("n_persons > 0", name="ck_datasets_n_persons_positive"),
        CheckConstraint("n_items > 0", name="ck_datasets_n_items_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Where the bytes live. A local path today, an object-storage key once the
    # deployment moves off container-local disk (see ARCHITECTURE §6).
    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)

    n_persons: Mapped[int] = mapped_column(Integer, nullable=False)
    n_items: Mapped[int] = mapped_column(Integer, nullable=False)
    # Which columns are items, which is the respondent id, which are grouping
    # variables for DIF, and the observed category counts. Declared at upload
    # rather than inferred: v1 inferred, and fitted respondent-id columns as
    # bogus items (P2).
    column_metadata: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    created_at: Mapped[datetime] = _created_at()

    project: Mapped[Project] = relationship(back_populates="datasets")
    runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class AnalysisRun(Base):
    """One execution of the analysis pipeline over one dataset.

    Status lives in the database rather than in the queue so that progress
    survives both a worker restart and an API restart, and so that polling reads
    a durable row instead of interrogating Redis.
    """

    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, native_enum=False, length=20, values_callable=_values),
        nullable=False,
        default=RunStatus.QUEUED,
        index=True,
    )
    # ModelKey values, kept as strings so a new family is a code change and not
    # a database migration.
    requested_models: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # RQ job id, for operator forensics only. The API never reads run state from
    # the queue.
    queue_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Operator-facing text. Routes surface a generic message; v1 returned raw
    # exception strings to clients (P5).
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    dataset: Mapped[Dataset] = relationship(back_populates="runs")
    fits: Mapped[list[ModelFit]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    diagnostics: Mapped[DiagnosticsBlob | None] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class ModelFit(Base):
    """One fitted model within a run — the persisted form of ``FitResult``.

    Every fit statistic is nullable because :class:`app.irt.FitResult` makes them
    optional: when ``converged`` is false there is no likelihood, and writing a
    zero would manufacture a comparison the engine refused to make.

    AIC and BIC are stored rather than recomputed on read. They are properties of
    the engine version that produced them, and a report must show the numbers
    that were computed at the time, not what today's code would derive.
    """

    __tablename__ = "model_fits"
    __table_args__ = (
        Index("ix_model_fits_run_model", "run_id", "model_key", unique=True),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    model_key: Mapped[str] = mapped_column(String(20), nullable=False)
    converged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    n_cycles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_likelihood: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_free_parameters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_persons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aic: Mapped[float | None] = mapped_column(Float, nullable=True)
    bic: Mapped[float | None] = mapped_column(Float, nullable=True)
    latent_sd: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    run: Mapped[AnalysisRun] = relationship(back_populates="fits")
    item_parameters: Mapped[list[ItemParameterRow]] = relationship(
        back_populates="fit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ItemParameterRow.position",
    )


class ItemParameterRow(Base):
    """One item's parameters under one fit, with their standard errors.

    A ``None`` standard error means "not estimated" and must render as such.
    Storing 0.0 in its place is how a report ends up claiming certainty it does
    not have, which is the class of defect this rebuild exists to remove.
    """

    __tablename__ = "item_parameters"
    __table_args__ = (
        Index("ix_item_parameters_fit_position", "fit_id", "position", unique=True),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    fit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_fits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    item_id: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    n_categories: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    discrimination: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    guessing: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Polytomous category boundaries; empty for dichotomous items.
    thresholds: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    se_discrimination: Mapped[float | None] = mapped_column(Float, nullable=True)
    se_difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    se_guessing: Mapped[float | None] = mapped_column(Float, nullable=True)
    se_thresholds: Mapped[list | None] = mapped_column(JSONType, nullable=True)

    fit: Mapped[ModelFit] = relationship(back_populates="item_parameters")


class DiagnosticsBlob(Base):
    """The diagnostics report for a run, stored whole.

    Item fit, assumption checks, DIF, reliability and the comparison dossier are
    a nested document that is read entirely or not at all, and whose shape tracks
    :mod:`app.psychometrics` rather than the database. Normalising it would mean
    a migration every time a diagnostic gains a field, so it is one JSONB column
    with the engine version on the parent run to say how to read it.
    """

    __tablename__ = "diagnostics_blobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()

    run: Mapped[AnalysisRun] = relationship(back_populates="diagnostics")

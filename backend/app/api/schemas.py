"""Wire schemas (Pydantic v2).

Response models are declared explicitly and never built from the ORM object by
default, so a column added to :mod:`app.db.models` cannot start leaking through
the API by accident — ``password_hash`` being the case that matters.

Enums are real enums on the wire. ARCHITECTURE §5 makes the TypeScript client a
generated artifact of this schema, and v1's bare ``str`` status fields are what
made the frontend's narrower unions a fiction (P6).

Optional fields are ``T | None`` with an explicit ``None`` default rather than
omitted, so the generated client sees ``T | null`` — matching what FastAPI
actually sends, which is the other half of the same P6 drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.db.models import IntendedUse, RunStatus, StakesLevel


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ----------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class LoginRequest(BaseModel):
    email: EmailStr
    # No length validation on login: rejecting a short password here would
    # report a policy that only applies at registration, and would let a caller
    # distinguish "no such account" from "wrong shape of password".
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class SessionOut(BaseModel):
    """The token is also set as an HttpOnly cookie; it is returned in the body
    for non-browser clients, which cannot read the cookie jar."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --- projects ------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    stakes_level: StakesLevel = StakesLevel.MEDIUM
    intended_use: IntendedUse = IntendedUse.OPERATIONAL


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    stakes_level: StakesLevel | None = None
    intended_use: IntendedUse | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    stakes_level: StakesLevel
    intended_use: IntendedUse
    created_at: datetime
    updated_at: datetime


# --- datasets ------------------------------------------------------------

class DatasetOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    checksum_sha256: str
    size_bytes: int
    n_persons: int
    n_items: int
    column_metadata: dict
    created_at: datetime


# --- analyses ------------------------------------------------------------

class AnalysisCreate(BaseModel):
    # Model keys are validated against app.irt.ModelKey in the route rather than
    # here, so the error message can name the supported set without this module
    # importing the engine.
    models: list[str] = Field(min_length=1, max_length=7)
    seed: int = Field(default=20260803, ge=0, le=2**31 - 1)
    # Validated against app.psychometrics.ScoreMethod in the route, for the same
    # reason as the model keys: this module does not import the numerical stack.
    # EAP by default because it is the estimator that produces a finite score for
    # every respondent who answered anything.
    score_method: str = "eap"


class AnalysisRunOut(ORMModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    status: RunStatus
    requested_models: list[str]
    score_method: str
    seed: int
    engine_version: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Present only for failed runs, and a fixed operator-safe phrase — v1
    # returned raw exception text to clients (P5).
    failure_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class ItemParameterOut(ORMModel):
    item_id: str
    position: int
    n_categories: int
    discrimination: float
    difficulty: float | None = None
    guessing: float | None = None
    thresholds: list[float] = Field(default_factory=list)
    se_discrimination: float | None = None
    se_difficulty: float | None = None
    se_guessing: float | None = None
    se_thresholds: list[float] | None = None


class ModelFitOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    model_key: str
    converged: bool
    log_likelihood: float | None = None
    n_free_parameters: int | None = None
    aic: float | None = None
    bic: float | None = None
    latent_sd: float | None = None
    elapsed_seconds: float | None = None
    failure_reason: str | None = None
    notes: list[str] = Field(default_factory=list)
    item_parameters: list[ItemParameterOut] = Field(default_factory=list)


class AnalysisResultOut(BaseModel):
    run: AnalysisRunOut
    fits: list[ModelFitOut]
    # None until the run succeeds. An empty dict would read as "diagnostics were
    # computed and found nothing", which is a different claim.
    diagnostics: dict | None = None

"""Analysis run reads and writes.

Two access paths, deliberately named apart:

* :class:`AnalysisRepository` — owner-scoped, the only one an HTTP route may
  use.
* :class:`SystemRunAccess` — unscoped, for the worker, which acts on behalf of
  the system and is handed a run id by the queue rather than by a client. It is
  a separate class so that "unscoped access" is a visible import in a review
  diff instead of an optional argument someone forgets to pass.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AnalysisRun,
    DiagnosticsBlob,
    ItemParameterRow,
    ModelFit,
    RunStatus,
    User,
)


def _now() -> datetime:
    return datetime.now(UTC)


class AnalysisRepository:
    def __init__(self, session: AsyncSession, owner: User) -> None:
        self._session = session
        self._owner = owner

    async def get(self, run_id: uuid.UUID) -> AnalysisRun | None:
        stmt = select(AnalysisRun).where(
            AnalysisRun.id == run_id, AnalysisRun.owner_id == self._owner.id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_with_results(self, run_id: uuid.UUID) -> AnalysisRun | None:
        """Same ownership predicate, with the result graph eagerly loaded.

        Eager loading matters here beyond performance: lazy loads on an async
        session raise at attribute access, which would turn a results page into
        a 500 at serialisation time.
        """

        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id, AnalysisRun.owner_id == self._owner.id)
            .options(
                selectinload(AnalysisRun.fits).selectinload(ModelFit.item_parameters),
                selectinload(AnalysisRun.diagnostics),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_dataset(self, dataset_id: uuid.UUID) -> Sequence[AnalysisRun]:
        stmt = (
            select(AnalysisRun)
            .where(
                AnalysisRun.owner_id == self._owner.id,
                AnalysisRun.dataset_id == dataset_id,
            )
            .order_by(AnalysisRun.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def create(
        self,
        *,
        dataset_id: uuid.UUID,
        requested_models: list[str],
        seed: int,
        engine_version: str,
    ) -> AnalysisRun:
        """Persist the run as QUEUED before anything is enqueued.

        Ordering is the point: the durable row exists first, so a job that never
        reaches Redis leaves a visible stuck run rather than nothing at all.
        """

        run = AnalysisRun(
            owner_id=self._owner.id,
            dataset_id=dataset_id,
            status=RunStatus.QUEUED,
            requested_models=requested_models,
            seed=seed,
            engine_version=engine_version,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def attach_queue_job(self, run: AnalysisRun, job_id: str) -> None:
        # Not an `assert`: stripped under `python -O`. See ProjectRepository.update.
        if run.owner_id != self._owner.id:
            raise PermissionError("run does not belong to the acting user")
        run.queue_job_id = job_id
        await self._session.flush()


class SystemRunAccess:
    """Unscoped run access for the worker process. Never used by a route."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: uuid.UUID) -> AnalysisRun | None:
        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .options(selectinload(AnalysisRun.dataset))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_running(self, run: AnalysisRun) -> None:
        run.status = RunStatus.RUNNING
        run.started_at = _now()
        await self._session.flush()

    async def mark_failed(self, run: AnalysisRun, reason: str) -> None:
        run.status = RunStatus.FAILED
        run.finished_at = _now()
        # Truncated: the reason is operator-facing and an unbounded traceback in
        # a database column is a log, not a status.
        run.failure_reason = reason[:2000]
        await self._session.flush()

    async def store_success(
        self,
        run: AnalysisRun,
        *,
        fits: list[ModelFit],
        diagnostics: dict,
        notes: list[str],
    ) -> None:
        for fit in fits:
            fit.run_id = run.id
            self._session.add(fit)
        self._session.add(DiagnosticsBlob(run_id=run.id, payload=diagnostics))
        run.notes = list(notes)
        run.status = RunStatus.SUCCEEDED
        run.finished_at = _now()
        await self._session.flush()


def fit_to_row(fit_result: object) -> ModelFit:
    """Map an :class:`app.irt.FitResult` onto its persisted form.

    ``aic``/``bic`` are properties on the dataclass that return ``None`` when the
    fit did not converge; they are copied across as-is rather than defaulted, so
    a failed fit stores nulls and a report has nothing to mistake for a
    measurement.
    """

    fit = ModelFit(
        model_key=getattr(fit_result.model, "value", str(fit_result.model)),
        converged=bool(fit_result.converged),
        n_cycles=getattr(fit_result, "n_cycles", None),
        log_likelihood=fit_result.log_likelihood,
        n_free_parameters=fit_result.n_free_parameters,
        n_persons=getattr(fit_result, "n_persons", None),
        aic=fit_result.aic,
        bic=fit_result.bic,
        latent_sd=getattr(fit_result, "latent_sd", None),
        elapsed_seconds=getattr(fit_result, "elapsed_seconds", None),
        failure_reason=getattr(fit_result, "failure_reason", None),
        notes=list(getattr(fit_result, "notes", []) or []),
    )
    fit.item_parameters = [
        ItemParameterRow(
            item_id=str(params.item_id),
            position=position,
            n_categories=int(getattr(params, "n_categories", 2)),
            discrimination=float(params.discrimination),
            difficulty=params.difficulty,
            guessing=params.guessing,
            thresholds=[float(t) for t in (params.thresholds or [])],
            se_discrimination=params.se_discrimination,
            se_difficulty=params.se_difficulty,
            se_guessing=params.se_guessing,
            se_thresholds=(
                [float(t) for t in params.se_thresholds]
                if params.se_thresholds is not None
                else None
            ),
        )
        for position, params in enumerate(fit_result.item_parameters)
    ]
    return fit

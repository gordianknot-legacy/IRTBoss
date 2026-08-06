"""Triggering analyses, polling status, fetching results.

The contract from ARCHITECTURE §4.1: validate, persist, **enqueue**, return 202
with a run id. No estimation happens in this file, and none can — the only
outbound call is :func:`app.workers.queue.enqueue_analysis`, and the engine is
never imported except to validate the requested model keys.

Ordering is deliberate. The run row is committed as QUEUED *before* the job is
handed to Redis, so the failure mode of a dead queue is a visible stuck run plus
a 503, not a client holding an id for a row that does not exist.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from functools import lru_cache

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse

from app.api.deps import (
    AnalysisRepoDep,
    DatasetRepoDep,
    SessionDep,
    SettingsDep,
    not_found,
)
from app.api.schemas import (
    AnalysisCreate,
    AnalysisResultOut,
    AnalysisRunOut,
    ModelFitOut,
)
from app.core.version import ENGINE_VERSION
from app.db.models import RunStatus

router = APIRouter(tags=["analyses"])

logger = logging.getLogger(__name__)


@lru_cache
def _supported_models() -> tuple[str, ...]:
    # Imported lazily: the web process has no other reason to load numpy.
    from app.irt import ModelKey

    return tuple(key.value for key in ModelKey)


@router.post(
    "/datasets/{dataset_id}/analyses",
    response_model=AnalysisRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis(
    dataset_id: uuid.UUID,
    payload: AnalysisCreate,
    settings: SettingsDep,
    session: SessionDep,
    datasets: DatasetRepoDep,
    runs: AnalysisRepoDep,
) -> AnalysisRunOut:
    dataset = await datasets.get(dataset_id)
    if dataset is None:
        raise not_found("Dataset")

    supported = _supported_models()
    requested = [m.strip().lower() for m in payload.models]
    unknown = sorted(set(requested) - set(supported))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported models {unknown}; supported: {list(supported)}",
        )

    run = await runs.create(
        dataset_id=dataset.id,
        requested_models=sorted(set(requested)),
        seed=payload.seed,
        engine_version=ENGINE_VERSION,
    )
    await session.commit()

    from app.workers.queue import enqueue_analysis

    try:
        # In a thread: the Redis client is synchronous, and a blocking socket on
        # the event loop is the same defect class as blocking CPU work.
        job_id = await asyncio.to_thread(enqueue_analysis, settings, run.id)
    except Exception:
        # Deliberately blind. Anything at all going wrong here must still leave
        # the run recorded: it stays QUEUED and can be re-enqueued by an
        # operator, rather than being silently dropped as v1 did (P0.1).
        #
        # Logged at exception level because the 503 body cannot distinguish
        # "Redis is down" from "enqueue_analysis has a bug", and without a
        # traceback the second one would look like the first forever.
        logger.exception("Failed to enqueue analysis run %s", run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis queue unavailable; the run has been recorded and can be retried",
        ) from None

    await runs.attach_queue_job(run, job_id)
    await session.commit()
    return AnalysisRunOut.model_validate(run)


@router.get("/analyses/{run_id}", response_model=AnalysisRunOut)
async def get_run(run_id: uuid.UUID, runs: AnalysisRepoDep) -> AnalysisRunOut:
    """Poll target. Reads the durable row, never the queue — so status survives
    a worker restart and an API restart alike."""

    run = await runs.get(run_id)
    if run is None:
        raise not_found("Analysis run")
    return AnalysisRunOut.model_validate(run)


@router.get("/datasets/{dataset_id}/analyses", response_model=list[AnalysisRunOut])
async def list_runs(
    dataset_id: uuid.UUID, datasets: DatasetRepoDep, runs: AnalysisRepoDep
) -> list[AnalysisRunOut]:
    if await datasets.get(dataset_id) is None:
        raise not_found("Dataset")
    return [AnalysisRunOut.model_validate(r) for r in await runs.list_for_dataset(dataset_id)]


@router.get("/analyses/{run_id}/report", response_class=HTMLResponse)
async def get_report(run_id: uuid.UUID, runs: AnalysisRepoDep) -> HTMLResponse:
    """The rendered report, as a self-contained HTML document.

    Rendered on demand from the stored result rather than at completion time and
    cached: the run's stored payload is immutable, so rendering is a pure
    function of it, and a template improvement then applies to every past run
    instead of only to runs analysed after the deploy.
    """

    run = await runs.get_for_report(run_id)
    if run is None:
        raise not_found("Analysis run")
    if run.status is not RunStatus.SUCCEEDED:
        # Consistent with the results endpoint. A report for an incomplete run
        # would be a document of absent numbers laid out as findings, which is
        # more misleading than no document at all.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is {run.status.value}; there is no report to render",
        )

    from app.reports import render_run

    html = render_run(run=run, dataset=run.dataset, project=run.dataset.project)
    return HTMLResponse(content=html)


@router.get("/analyses/{run_id}/results", response_model=AnalysisResultOut)
async def get_results(run_id: uuid.UUID, runs: AnalysisRepoDep) -> AnalysisResultOut:
    run = await runs.get_with_results(run_id)
    if run is None:
        raise not_found("Analysis run")
    if run.status is not RunStatus.SUCCEEDED:
        # 409, not an empty 200. A results document for an incomplete run would
        # be a set of absent numbers presented as findings.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is {run.status.value}; results are not available",
        )
    return AnalysisResultOut(
        run=AnalysisRunOut.model_validate(run),
        fits=[ModelFitOut.model_validate(f) for f in run.fits],
        diagnostics=run.diagnostics.payload if run.diagnostics else None,
    )

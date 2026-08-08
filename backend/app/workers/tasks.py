"""The analysis job.

This is the only place estimation runs. Nothing under :mod:`app.api` may call
:func:`run_analysis_task` directly — that would put minutes of numpy on the event
loop, which is the P5 blocking defect in its most expensive form.

The job is written to be re-runnable: it reads the run row, re-reads the stored
CSV by its storage reference, and overwrites the run's results. Re-running a
succeeded run is therefore safe, which is what makes a stuck or lost job an
operational nuisance rather than a data-loss event.

The reference is resolved through :mod:`app.storage`, not opened as a path, so
this process does not have to share a filesystem with the API that wrote it. A
reference written by a backend this worker is not configured for fails the run
with a message naming that mismatch — see :mod:`app.storage.base`.

Failure handling has one rule: a run that fails is stored as ``FAILED`` with a
reason, never as a succeeded run carrying partial results. The engine already
refuses to emit parameters for an unconverged fit; this layer refuses to invent a
run outcome for the same reason.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.repositories.analyses import SystemRunAccess, fit_to_row
from app.storage import ObjectStore, get_object_store

logger = logging.getLogger(__name__)


def run_analysis_task(run_id: str) -> None:
    """RQ entrypoint. Synchronous by necessity — RQ workers are not async.

    The async work is bounded by ``asyncio.run`` rather than run against a
    long-lived loop, so each job gets a fresh engine and connection pool and a
    crashed job cannot poison the next one's connections.
    """

    asyncio.run(_execute(uuid.UUID(str(run_id))))


async def _execute(run_id: uuid.UUID) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=settings.sql_echo)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            access = SystemRunAccess(session)
            run = await access.get(run_id)
            if run is None:
                # A deleted project cascades its runs away; a job for one is a
                # no-op, not an error worth retrying.
                logger.warning("analysis run %s no longer exists", run_id)
                return

            await access.mark_running(run)
            await session.commit()

            try:
                fits, diagnostics, notes = await asyncio.to_thread(
                    _analyse,
                    get_object_store(settings),
                    run.dataset.storage_ref,
                    run.dataset.column_metadata or {},
                    list(run.requested_models or []),
                    int(run.seed),
                )
            except Exception as exc:
                logger.exception("analysis run %s failed", run_id)
                await access.mark_failed(run, f"{type(exc).__name__}: {exc}")
                await session.commit()
                return

            await access.store_success(
                run,
                fits=[fit_to_row(fit) for fit in fits],
                diagnostics=diagnostics,
                notes=notes,
            )
            await session.commit()
    finally:
        await engine.dispose()


def _analyse(
    store: ObjectStore,
    storage_ref: str,
    column_metadata: dict,
    models: list[str],
    seed: int,
) -> tuple[list, dict, list[str]]:
    """Load the stored CSV and run the orchestrator. Runs in a thread.

    ``app.analysis`` is imported here rather than at module scope for two
    reasons: it drags in the whole numerical stack, and it lets tests
    monkeypatch the orchestrator without the import order mattering.

    The whole object is read into memory before parsing. That is bounded by
    ``max_upload_bytes`` at the point of upload, so it is a known quantity rather
    than an open one — and streaming would buy nothing here, since pandas
    materialises the frame anyway.
    """

    import io

    import pandas as pd

    from app.analysis import run_analysis

    frame = pd.read_csv(io.BytesIO(store.get(storage_ref)))
    item_columns = column_metadata.get("item_columns") or list(frame.columns)
    group_columns = column_metadata.get("group_columns") or []

    data = frame[item_columns]
    groups = frame[group_columns] if group_columns else None

    result = run_analysis(data, models, groups=groups, seed=seed)
    return list(result.fits), dict(result.diagnostics), list(result.notes)

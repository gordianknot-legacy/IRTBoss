"""Dataset upload and listing.

The upload route does no parsing itself: :mod:`app.api.ingest` streams the body
under a cap and does the CPU work in a thread. What stays here is the ownership
check on the parent project and the translation of ingest failures into status
codes — 413 for a body over the cap, 422 for bytes that arrived intact but are
not a usable response matrix.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import (
    DatasetRepoDep,
    ObjectStoreDep,
    ProjectRepoDep,
    SessionDep,
    SettingsDep,
    not_found,
)
from app.api.ingest import InvalidUpload, UploadTooLarge, ingest_csv
from app.api.schemas import DatasetOut
from app.storage import StorageError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["datasets"])


@router.post(
    "/projects/{project_id}/datasets",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_dataset(
    project_id: uuid.UUID,
    settings: SettingsDep,
    session: SessionDep,
    store: ObjectStoreDep,
    projects: ProjectRepoDep,
    datasets: DatasetRepoDep,
    file: UploadFile = File(...),
    # Declared, not inferred — v1 guessed and fitted id columns as items (P2).
    id_column: str | None = Form(default=None),
    group_columns: str | None = Form(default=None),
) -> DatasetOut:
    if await projects.get(project_id) is None:
        raise not_found("Project")

    try:
        groups = json.loads(group_columns) if group_columns else []
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="group_columns must be a JSON array of column names",
        ) from None

    try:
        parsed = await ingest_csv(
            file,
            store=store,
            max_bytes=settings.max_upload_bytes,
            max_rows=settings.max_rows,
            max_columns=settings.max_columns,
            id_column=id_column,
            group_columns=groups,
        )
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {exc.limit_bytes} byte limit",
        ) from None
    except InvalidUpload as exc:
        # Safe to surface: these messages are authored here, not exception text
        # from a third-party library (P5's raw-exception leak).
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from None
    except StorageError:
        logger.exception("upload storage rejected a dataset for project %s", project_id)
        # The bytes were fine and the store was not. 503 rather than 500 for the
        # same reason the analyses route uses it for an unreachable queue: the
        # request is worth retrying, and nothing was written. The underlying
        # message stays in the log — it names a bucket.
        raise HTTPException(
            status_code=503, detail="Upload storage is unavailable"
        ) from None

    dataset = await datasets.create(
        project_id=project_id,
        original_filename=file.filename or "upload.csv",
        checksum_sha256=parsed.checksum_sha256,
        size_bytes=parsed.size_bytes,
        storage_ref=parsed.storage_ref,
        n_persons=parsed.n_persons,
        n_items=parsed.n_items,
        column_metadata=parsed.column_metadata,
    )
    await session.commit()
    return DatasetOut.model_validate(dataset)


@router.get("/projects/{project_id}/datasets", response_model=list[DatasetOut])
async def list_datasets(
    project_id: uuid.UUID, projects: ProjectRepoDep, datasets: DatasetRepoDep
) -> list[DatasetOut]:
    if await projects.get(project_id) is None:
        raise not_found("Project")
    rows = await datasets.list_for_project(project_id)
    return [DatasetOut.model_validate(d) for d in rows]


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
async def get_dataset(dataset_id: uuid.UUID, datasets: DatasetRepoDep) -> DatasetOut:
    dataset = await datasets.get(dataset_id)
    if dataset is None:
        raise not_found("Dataset")
    return DatasetOut.model_validate(dataset)

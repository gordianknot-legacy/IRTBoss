"""Dataset reads and writes, always filtered by owner."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dataset, User


class DatasetRepository:
    def __init__(self, session: AsyncSession, owner: User) -> None:
        self._session = session
        self._owner = owner

    async def get(self, dataset_id: uuid.UUID) -> Dataset | None:
        stmt = select(Dataset).where(
            Dataset.id == dataset_id, Dataset.owner_id == self._owner.id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> Sequence[Dataset]:
        # Both predicates are needed: the project filter alone would trust a
        # project id the caller supplied.
        stmt = (
            select(Dataset)
            .where(Dataset.owner_id == self._owner.id, Dataset.project_id == project_id)
            .order_by(Dataset.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        original_filename: str,
        checksum_sha256: str,
        size_bytes: int,
        storage_ref: str,
        n_persons: int,
        n_items: int,
        column_metadata: dict,
    ) -> Dataset:
        dataset = Dataset(
            owner_id=self._owner.id,
            project_id=project_id,
            original_filename=original_filename,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            storage_ref=storage_ref,
            n_persons=n_persons,
            n_items=n_items,
            column_metadata=column_metadata,
        )
        self._session.add(dataset)
        await self._session.flush()
        return dataset

"""Project reads and writes, always filtered by owner."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntendedUse, Project, StakesLevel, User


class ProjectRepository:
    """Owner-scoped. The owner is bound at construction, not per call, so a
    method physically cannot be invoked without one."""

    def __init__(self, session: AsyncSession, owner: User) -> None:
        self._session = session
        self._owner = owner

    async def get(self, project_id: uuid.UUID) -> Project | None:
        stmt = select(Project).where(
            Project.id == project_id, Project.owner_id == self._owner.id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[Project]:
        stmt = (
            select(Project)
            .where(Project.owner_id == self._owner.id)
            .order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        stakes_level: StakesLevel,
        intended_use: IntendedUse,
    ) -> Project:
        project = Project(
            owner_id=self._owner.id,
            name=name,
            description=description,
            stakes_level=stakes_level,
            intended_use=intended_use,
        )
        self._session.add(project)
        await self._session.flush()
        return project

    async def update(self, project: Project, **fields: object) -> Project:
        # The instance can only have come from `get`, so it is already
        # owner-checked; this guards against a future caller that constructs one
        # elsewhere. Deliberately not an `assert`: assertions are stripped under
        # `python -O`, and an ownership check that disappears under an
        # optimisation flag is not an ownership check.
        if project.owner_id != self._owner.id:
            raise PermissionError("project does not belong to the acting user")
        for key, value in fields.items():
            if value is not None:
                setattr(project, key, value)
        await self._session.flush()
        return project

    async def delete(self, project_id: uuid.UUID) -> bool:
        """Returns whether anything was deleted.

        Expressed as a single owner-filtered DELETE rather than read-then-delete
        so there is no window in which the ownership check and the write
        disagree.
        """

        stmt = delete(Project).where(
            Project.id == project_id, Project.owner_id == self._owner.id
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)

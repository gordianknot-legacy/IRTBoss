"""Project CRUD.

Every handler resolves the project through the owner-scoped repository and turns
``None`` into 404. There is no branch anywhere in this file that reads a project
by id alone, which is the whole point: the authorisation is the query.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import ProjectRepoDep, SessionDep, not_found
from app.api.schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, repo: ProjectRepoDep, session: SessionDep
) -> ProjectOut:
    project = await repo.create(
        name=payload.name,
        description=payload.description,
        stakes_level=payload.stakes_level,
        intended_use=payload.intended_use,
    )
    await session.commit()
    return ProjectOut.model_validate(project)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    repo: ProjectRepoDep, limit: int = 50, offset: int = 0
) -> list[ProjectOut]:
    # Capped server-side: an unbounded `limit` from the client is a cheap way to
    # turn one request into a full table scan.
    projects = await repo.list(limit=min(limit, 200), offset=max(offset, 0))
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, repo: ProjectRepoDep) -> ProjectOut:
    project = await repo.get(project_id)
    if project is None:
        raise not_found("Project")
    return ProjectOut.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    repo: ProjectRepoDep,
    session: SessionDep,
) -> ProjectOut:
    project = await repo.get(project_id)
    if project is None:
        raise not_found("Project")
    updated = await repo.update(project, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return ProjectOut.model_validate(updated)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, repo: ProjectRepoDep, session: SessionDep
) -> Response:
    if not await repo.delete(project_id):
        raise not_found("Project")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

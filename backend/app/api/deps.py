"""Request dependencies.

The important one is :func:`current_user`. It is the only place a request turns
into an identity, and every router that touches user data depends on it — so
"this route forgot to authenticate" is visible as a missing dependency in the
signature rather than as a missing ``if`` in the body.

The repository dependencies below build their repository *from* the authenticated
user, which is what makes owner scoping unavoidable downstream: a route cannot
obtain a repository without having obtained a user first.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenError, fingerprint_matches, read_token
from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import User
from app.repositories.analyses import AnalysisRepository
from app.repositories.datasets import DatasetRepository
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request, settings: Settings) -> str | None:
    # Cookie first (the browser client), bearer header second (scripts, the
    # generated API client, tests).
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        return cookie
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return None


async def current_user(
    request: Request, settings: SettingsDep, session: SessionDep
) -> User:
    raw = _extract_token(request, settings)
    if not raw:
        raise _UNAUTHENTICATED
    try:
        token = read_token(settings, raw)
    except TokenError:
        raise _UNAUTHENTICATED from None

    user = await UserRepository(session).get(token.user_id)
    # A deactivated account and a stale password fingerprint both fail here, so
    # a session cannot outlive either a password change or a disabled user.
    if user is None or not user.is_active or not fingerprint_matches(token, user.password_hash):
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def project_repository(session: SessionDep, user: CurrentUser) -> ProjectRepository:
    return ProjectRepository(session, user)


def dataset_repository(session: SessionDep, user: CurrentUser) -> DatasetRepository:
    return DatasetRepository(session, user)


def analysis_repository(session: SessionDep, user: CurrentUser) -> AnalysisRepository:
    return AnalysisRepository(session, user)


ProjectRepoDep = Annotated[ProjectRepository, Depends(project_repository)]
DatasetRepoDep = Annotated[DatasetRepository, Depends(dataset_repository)]
AnalysisRepoDep = Annotated[AnalysisRepository, Depends(analysis_repository)]


def not_found(what: str) -> HTTPException:
    """404 for both "absent" and "not yours".

    Returning 403 for the second case would confirm the row exists, which is a
    membership oracle over other users' identifiers.
    """

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")

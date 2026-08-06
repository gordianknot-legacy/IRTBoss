"""User lookup and creation.

The one repository that is not owner-scoped, because it is what establishes who
the owner is. It is deliberately narrow: lookup by id, lookup by email, create.
Nothing here returns a collection of users.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


def normalise_email(email: str) -> str:
    """Case-fold and trim.

    Addresses are stored normalised so the unique constraint actually prevents
    ``Alice@x.com`` and ``alice@x.com`` from being two accounts, without needing
    a PostgreSQL-only functional index.
    """

    return email.strip().lower()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == normalise_email(email))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, *, email: str, password_hash: str) -> User:
        user = User(email=normalise_email(email), password_hash=password_hash)
        self._session.add(user)
        await self._session.flush()
        return user

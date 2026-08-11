"""Add users.sessions_revoked_at.

Session revocation without a session table: one timestamp per account, compared
against each token's signature timestamp on read. Nullable with no default, so
existing rows mean "nothing revoked" rather than "everything revoked at the
moment of the migration" — the latter would log every user out on deploy.

Revision ID: 0002_session_revocation
Revises: 0001_initial
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_session_revocation'
down_revision: str | Sequence[str] | None = '0001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('sessions_revoked_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema.

    Dropping the column re-validates every token that a revocation had killed.
    That is inherent to reversing this migration and is the reason a downgrade
    here is an incident-recovery step rather than routine.
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('sessions_revoked_at')

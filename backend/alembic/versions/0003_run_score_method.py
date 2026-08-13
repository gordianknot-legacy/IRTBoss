"""Add analysis_runs.score_method.

The scoring estimator becomes a property of the run rather than a constant in the
orchestrator. ``server_default='eap'`` is kept rather than dropped after the
backfill: every existing run *was* scored by EAP, so the default is the truth
about them, and a run row that arrived without the column set would otherwise be
unwritable.

Revision ID: 0003_run_score_method
Revises: 0002_session_revocation
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003_run_score_method'
down_revision: str | Sequence[str] | None = '0002_session_revocation'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('analysis_runs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'score_method',
                sa.String(length=20),
                nullable=False,
                server_default='eap',
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('analysis_runs', schema=None) as batch_op:
        batch_op.drop_column('score_method')

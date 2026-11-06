"""Add jobs.regions: where each remote job can be done.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Filled by the next ingestion run, which refreshes derived fields on every job.
    op.add_column(
        "jobs",
        sa.Column(
            "regions",
            postgresql.ARRAY(sa.String(16)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.create_index("ix_jobs_regions", "jobs", ["regions"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_jobs_regions", table_name="jobs")
    op.drop_column("jobs", "regions")

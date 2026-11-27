"""Exámenes asíncronos: estado de la generación (pending, ready, failed) y su error.

Las filas anteriores quedan como `ready`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exams", sa.Column("status", sa.String(10), server_default="ready", nullable=False)
    )
    op.add_column("exams", sa.Column("error", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_exams_status", "exams", "status IN ('pending', 'ready', 'failed')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_exams_status", "exams", type_="check")
    op.drop_column("exams", "error")
    op.drop_column("exams", "status")

"""Exámenes mixtos: tipo, opciones, puntuación y criterio por pregunta, y duración del examen.

Las filas anteriores quedan como `completion` con 1 punto y 30 minutos de duración.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exams",
        sa.Column("duration_minutes", sa.SmallInteger(), server_default="30", nullable=False),
    )
    op.add_column(
        "exam_questions",
        sa.Column("kind", sa.String(20), server_default="completion", nullable=False),
    )
    op.add_column("exam_questions", sa.Column("options", postgresql.JSONB(), nullable=True))
    op.add_column(
        "exam_questions", sa.Column("points", sa.Float(), server_default="1", nullable=False)
    )
    op.add_column("exam_questions", sa.Column("criteria", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_exam_questions_kind",
        "exam_questions",
        "kind IN ('completion', 'development', 'case', 'multiple_choice', 'true_false')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_exam_questions_kind", "exam_questions", type_="check")
    for column in ("criteria", "points", "options", "kind"):
        op.drop_column("exam_questions", column)
    op.drop_column("exams", "duration_minutes")

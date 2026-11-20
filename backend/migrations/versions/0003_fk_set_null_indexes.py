"""Índices en claves foráneas ON DELETE SET NULL (issue #34).

PostgreSQL no indexa las FK: sin estos índices, borrar una fila padre recorre
la tabla hija entera para poner a NULL las referencias.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = [
    ("feedback", "answer_id"),
    ("feedback", "exam_id"),
    ("history_entries", "answer_id"),
    ("history_entries", "exam_id"),
    # La reindexación borra chunks y pone a NULL citations.chunk_id.
    ("citations", "chunk_id"),
]


def upgrade() -> None:
    # CREATE INDEX normal (sin CONCURRENTLY): la BD de demo en Neon tiene pocos datos.
    for table, column in INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, column in reversed(INDEXES):
        op.drop_index(f"ix_{table}_{column}", table_name=table)

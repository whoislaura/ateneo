"""Esquema inicial: usuarios, corpus, respuestas, citas, exámenes, historial y feedback.

Revision ID: 0001
Revises:
Create Date: 2026-11-19

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = {
    "user_role": ("student", "teacher", "admin"),
    "document_status": ("indexed", "partial", "retired"),
    "page_status": ("text", "no_text"),
    "answer_kind": ("query", "summary", "outline", "table", "diagram"),
    "answer_status": ("answered", "no_evidence"),
    "exam_difficulty": ("easy", "medium", "hard"),
    "history_action": (
        "query",
        "generation",
        "exam",
        "document_upload",
        "document_update",
        "document_retire",
    ),
    "feedback_kind": ("rating", "error", "suggestion"),
}


def enum(name: str) -> sa.Enum:
    # Cada tipo se usa en una sola tabla; create_table emite su CREATE TYPE.
    return sa.Enum(*ENUMS[name], name=name)


def created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # Normalmente ya la crea infra/db/init.sql; se repite para bases creadas por otra vía.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", enum("user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("status", enum("document_status"), nullable=False),
        sa.Column("chunk_settings", postgresql.JSONB(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("year BETWEEN 1 AND 4", name="ck_documents_year"),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_documents_uploaded_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("ix_documents_classification", "documents", ["year", "subject", "topic"])
    op.create_table(
        "pages",
        sa.Column("document_id", sa.String(200), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", enum("page_status"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_pages_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "number", name="pk_pages"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(200), nullable=False),
        sa.Column("document_version", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(), nullable=True),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset", name="ck_chunks_offsets"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "page_number"],
            ["pages.document_id", "pages.number"],
            name="fk_chunks_document_id_page_number_pages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_table(
        "answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", enum("answer_kind"), nullable=False),
        sa.Column("status", enum("answer_status"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        created_at(),
        sa.CheckConstraint("year IS NULL OR year BETWEEN 1 AND 4", name="ck_answers_year"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_answers_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_answers"),
    )
    op.create_index("ix_answers_user_id", "answers", ["user_id"])
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("difficulty", enum("exam_difficulty"), nullable=False),
        sa.Column("question_count", sa.SmallInteger(), nullable=False),
        created_at(),
        sa.CheckConstraint("year BETWEEN 1 AND 4", name="ck_exams_year"),
        sa.CheckConstraint("question_count BETWEEN 1 AND 50", name="ck_exams_question_count"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_exams_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exams"),
    )
    op.create_index("ix_exams_user_id", "exams", ["user_id"])
    op.create_table(
        "exam_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exams.id"], name="fk_exam_questions_exam_id_exams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exam_questions"),
        sa.UniqueConstraint("exam_id", "position", name="uq_exam_questions_exam_id_position"),
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=True),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("chunk_id", sa.String(64), nullable=True),
        sa.Column("document_id", sa.String(200), nullable=False),
        sa.Column("document_title", sa.Text(), nullable=False),
        sa.Column("document_version", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_label", sa.Text(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(answer_id IS NULL) <> (question_id IS NULL)", name="ck_citations_one_owner"
        ),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset", name="ck_citations_offsets"
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"], ["answers.id"], name="fk_citations_answer_id_answers", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["exam_questions.id"],
            name="fk_citations_question_id_exam_questions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.id"], name="fk_citations_chunk_id_chunks", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_citations"),
    )
    op.create_index("ix_citations_answer_id", "citations", ["answer_id"])
    op.create_index("ix_citations_question_id", "citations", ["question_id"])
    op.create_table(
        "history_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", enum("history_action"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=True),
        sa.Column("exam_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.String(200), nullable=True),
        created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_history_entries_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["answers.id"],
            name="fk_history_entries_answer_id_answers",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exams.id"], name="fk_history_entries_exam_id_exams", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_history_entries_document_id_documents",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_history_entries"),
    )
    op.create_index("ix_history_entries_user_created", "history_entries", ["user_id", "created_at"])
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("kind", enum("feedback_kind"), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("answer_id", sa.Integer(), nullable=True),
        sa.Column("exam_id", sa.Integer(), nullable=True),
        created_at(),
        sa.CheckConstraint(
            "(kind = 'rating') = (rating IS NOT NULL)", name="ck_feedback_rating_kind"
        ),
        sa.CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_feedback_user_id_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"], ["answers.id"], name="fk_feedback_answer_id_answers", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exams.id"], name="fk_feedback_exam_id_exams", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
    )


def downgrade() -> None:
    for table in (
        "feedback",
        "history_entries",
        "citations",
        "exam_questions",
        "exams",
        "answers",
        "chunks",
        "pages",
        "documents",
        "users",
    ):
        op.drop_table(table)
    for name in ENUMS:
        op.execute(f"DROP TYPE {name}")

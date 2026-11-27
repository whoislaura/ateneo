"""Conversaciones con memoria: hilos de mensajes que reutilizan `answers` y `citations`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
    "query",
    "generation",
    "exam",
    "document_upload",
    "document_update",
    "document_retire",
)


def upgrade() -> None:
    # ADD VALUE no puede usarse en la transacción que lo crea: se confirma antes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE history_action ADD VALUE IF NOT EXISTS 'conversation'")
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", name="message_role"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"], ["answers.id"], name="fk_messages_answer_id_answers", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_answer_id", "messages", ["answer_id"])
    op.add_column("history_entries", sa.Column("conversation_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_history_entries_conversation_id_conversations",
        "history_entries",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_history_entries_conversation_id", "history_entries", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_history_entries_conversation_id", table_name="history_entries")
    op.drop_constraint(
        "fk_history_entries_conversation_id_conversations", "history_entries", type_="foreignkey"
    )
    op.drop_column("history_entries", "conversation_id")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.execute("DROP TYPE message_role")
    # PostgreSQL no quita valores de un enum: se recrea el tipo sin 'conversation'.
    op.execute("DELETE FROM history_entries WHERE action = 'conversation'")
    op.execute("ALTER TYPE history_action RENAME TO history_action_old")
    values = ", ".join(f"'{v}'" for v in OLD_ACTIONS)
    op.execute(f"CREATE TYPE history_action AS ENUM ({values})")
    op.execute(
        "ALTER TABLE history_entries ALTER COLUMN action TYPE history_action "
        "USING action::text::history_action"
    )
    op.execute("DROP TYPE history_action_old")

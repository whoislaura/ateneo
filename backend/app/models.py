"""Modelo de datos PostgreSQL. El esquema se cambia solo mediante migraciones Alembic."""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DDL,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    true,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Nombres estables para que las migraciones puedan referirse a cada restricción.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def enum_type(enum_class: type[enum.Enum], name: str) -> Enum:
    """Enum PostgreSQL que guarda los valores (`student`), no los nombres de Python."""
    return Enum(enum_class, name=name, values_callable=lambda e: [m.value for m in e])


class Role(enum.StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class DocumentStatus(enum.StrEnum):
    INDEXED = "indexed"
    PARTIAL = "partial"
    RETIRED = "retired"


class PageStatus(enum.StrEnum):
    TEXT = "text"
    NO_TEXT = "no_text"


class AnswerKind(enum.StrEnum):
    QUERY = "query"
    SUMMARY = "summary"
    OUTLINE = "outline"
    TABLE = "table"
    DIAGRAM = "diagram"


class AnswerStatus(enum.StrEnum):
    ANSWERED = "answered"
    NO_EVIDENCE = "no_evidence"


class Difficulty(enum.StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionKind(enum.StrEnum):
    COMPLETION = "completion"  # exámenes antiguos: completar fragmento
    DEVELOPMENT = "development"
    CASE = "case"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"


class HistoryAction(enum.StrEnum):
    QUERY = "query"
    GENERATION = "generation"
    EXAM = "exam"
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_UPDATE = "document_update"
    DOCUMENT_RETIRE = "document_retire"
    CONVERSATION = "conversation"  # migración 0005


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class FeedbackKind(enum.StrEnum):
    RATING = "rating"
    ERROR = "error"
    SUGGESTION = "suggestion"


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(enum_type(Role, "user_role"))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = created_at()


class AuthSession(Base):
    """Sesión de CU-00. Se guarda el SHA-256 del token, nunca el token."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Document(Base):
    """Versión vigente de un documento; `id` es el `document_id` estable de la ingestión."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("year BETWEEN 1 AND 4", name="ck_documents_year"),
        Index("ix_documents_classification", "year", "subject", "topic"),
    )

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(64))  # SHA-256 de los bytes del PDF
    year: Mapped[int] = mapped_column(SmallInteger)
    subject: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text)
    status: Mapped[DocumentStatus] = mapped_column(enum_type(DocumentStatus, "document_status"))
    chunk_settings: Mapped[dict] = mapped_column(JSONB)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pages: Mapped[list["Page"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Page(Base):
    __tablename__ = "pages"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    number: Mapped[int] = mapped_column(primary_key=True)  # página física desde 1
    label: Mapped[str | None] = mapped_column(Text)  # etiqueta /PageLabels del PDF, si existe
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[PageStatus] = mapped_column(enum_type(PageStatus, "page_status"))


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "page_number"],
            ["pages.document_id", "pages.number"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset", name="ck_chunks_offsets"
        ),
        # Texto completo (migración 0004, que crea `ateneo_unaccent`); solo PostgreSQL.
        Index(
            "ix_chunks_text_fts",
            sql_text("to_tsvector('spanish'::regconfig, ateneo_unaccent(text))"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # chunk_id de la ingestión
    document_id: Mapped[str] = mapped_column(String(200), index=True)
    document_version: Mapped[str] = mapped_column(String(64))
    page_number: Mapped[int]
    # Offsets de caracteres sobre `pages.text`, final exclusivo.
    start_offset: Mapped[int]
    end_offset: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    # shortcut: sin dimensión ni índice ANN hasta elegir el modelo de embeddings (AT-14).
    embedding: Mapped[list[float] | None] = mapped_column(Vector())


# create_all (tests) no pasa por la migración 0004: crea lo que necesita ix_chunks_text_fts.
for _ddl in (
    "CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public",
    "CREATE OR REPLACE FUNCTION public.ateneo_unaccent(text) RETURNS text "
    "LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT "
    "AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$",
):
    event.listen(Chunk.__table__, "before_create", DDL(_ddl).execute_if(dialect="postgresql"))


class Answer(Base):
    """Resultado de CU-01 (consulta) o CU-02 (generación)."""

    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint("year IS NULL OR year BETWEEN 1 AND 4", name="ck_answers_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[AnswerKind] = mapped_column(enum_type(AnswerKind, "answer_kind"))
    status: Mapped[AnswerStatus] = mapped_column(enum_type(AnswerStatus, "answer_status"))
    question: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    subject: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    citations: Mapped[list["Citation"]] = relationship(order_by="Citation.position")


class Conversation(Base):
    """Hilo de chat de CU-01 con memoria: cada turno es un par de mensajes."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))  # primera pregunta, recortada
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(order_by="Message.id")


class Message(Base):
    """Mensaje del hilo. El del asistente apunta a su `Answer`, que guarda estado y citas."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(enum_type(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = created_at()

    answer: Mapped["Answer | None"] = relationship()


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint("year BETWEEN 1 AND 4", name="ck_exams_year"),
        CheckConstraint("question_count BETWEEN 1 AND 50", name="ck_exams_question_count"),
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_exams_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(SmallInteger)
    subject: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[Difficulty] = mapped_column(enum_type(Difficulty, "exam_difficulty"))
    question_count: Mapped[int] = mapped_column(SmallInteger)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, server_default="30")
    status: Mapped[str] = mapped_column(String(10), server_default="ready")  # pending|ready|failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    questions: Mapped[list["ExamQuestion"]] = relationship(order_by="ExamQuestion.position")

    @property
    def total_points(self) -> float:
        return round(sum(question.points for question in self.questions), 2)


class ExamQuestion(Base):
    __tablename__ = "exam_questions"
    __table_args__ = (
        UniqueConstraint("exam_id", "position"),
        CheckConstraint(
            "kind IN ('completion', 'development', 'case', 'multiple_choice', 'true_false')",
            name="ck_exam_questions_kind",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    statement: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    # Los exámenes anteriores a la 0006 son de completar fragmento, con 1 punto cada pregunta.
    kind: Mapped[str] = mapped_column(String(20), server_default="completion")
    options: Mapped[list | None] = mapped_column(JSONB)  # cuatro opciones de las de test
    points: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    criteria: Mapped[str | None] = mapped_column(Text)

    citations: Mapped[list["Citation"]] = relationship(order_by="Citation.position")


class Citation(Base):
    """Copia verificable de la referencia; sobrevive a la reindexación del documento."""

    __tablename__ = "citations"
    __table_args__ = (
        CheckConstraint(
            "(answer_id IS NULL) <> (question_id IS NULL)", name="ck_citations_one_owner"
        ),
        CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset", name="ck_citations_offsets"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_questions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger)  # orden [1], [2]… dentro del texto
    chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), index=True
    )
    document_id: Mapped[str] = mapped_column(String(200))
    document_title: Mapped[str] = mapped_column(Text)
    document_version: Mapped[str] = mapped_column(String(64))
    page_number: Mapped[int]
    page_label: Mapped[str | None] = mapped_column(Text)
    start_offset: Mapped[int]
    end_offset: Mapped[int]
    quote: Mapped[str] = mapped_column(Text)


class HistoryEntry(Base):
    """Registro CU-04: fecha, autor, acción y resumen."""

    __tablename__ = "history_entries"
    __table_args__ = (Index("ix_history_entries_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[HistoryAction] = mapped_column(enum_type(HistoryAction, "history_action"))
    summary: Mapped[str] = mapped_column(Text)
    answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL"), index=True
    )
    exam_id: Mapped[int | None] = mapped_column(
        ForeignKey("exams.id", ondelete="SET NULL"), index=True
    )
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    # Una conversación aparece una vez en el historial y se borra con ella.
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = created_at()


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("(kind = 'rating') = (rating IS NOT NULL)", name="ck_feedback_rating_kind"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[FeedbackKind] = mapped_column(enum_type(FeedbackKind, "feedback_kind"))
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL"), index=True
    )
    exam_id: Mapped[int | None] = mapped_column(
        ForeignKey("exams.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = created_at()

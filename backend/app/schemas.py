"""Esquemas Pydantic del contrato /api/v1. Ver docs/api-contract.md."""

from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import (
    AnswerKind,
    AnswerStatus,
    Difficulty,
    DocumentStatus,
    FeedbackKind,
    HistoryAction,
    MessageRole,
    PageStatus,
    QuestionKind,
    Role,
)

# Las columnas id son INTEGER de 32 bits: sin cota, Postgres daría 500 en vez de 404/422.
Id = Annotated[int, Field(ge=1, le=2**31 - 1)]
Limit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0, le=1_000_000)]
Year = Annotated[int, Field(ge=1, le=4)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Question = Annotated[str, Field(min_length=1, max_length=1000)]
RawPassword = Annotated[str, StringConstraints(strip_whitespace=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorBody(Contract):
    code: str = Field(examples=["not_found"])
    message: str
    details: list[Any] | None = None


class ErrorResponse(Contract):
    """Formato único de error de la versión 1 de la API."""

    error: ErrorBody


# CU-00


class LoginRequest(Contract):
    email: Annotated[str, Field(min_length=3, max_length=320)]
    password: Annotated[RawPassword, Field(min_length=1, max_length=200)]


class UserOut(Contract):
    id: int
    email: str
    full_name: str
    role: Role


class TokenResponse(Contract):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Segundos de validez del token.")
    user: UserOut


# CU-01, CU-02, CU-05


class Classification(Contract):
    """Filtro opcional por año, asignatura y tema; los campos omitidos no filtran."""

    year: Year | None = None
    subject: Text | None = None
    topic: Text | None = None


class QueryRequest(Classification):
    question: Question
    # No se guarda en Answer (sin migraciones); la respuesta no lo devuelve.
    mode: Literal["breve", "desarrollada"] = Field(
        default="breve",
        description="«breve» (por defecto): respuesta corta. «desarrollada»: más fragmentos y "
        "estructura Planteamiento, Desarrollo, Fundamentación, Conclusión y Límites del corpus.",
    )


class GenerationRequest(Classification):
    format: Literal["summary", "outline", "table", "diagram"]
    prompt: Question = Field(description="Contenido a sintetizar, p. ej. un tema o pregunta.")


class CitationOut(Contract):
    """Referencia verificable: `quote == página(document_version, page_number).text[start:end]`."""

    position: int = Field(ge=1, description="Número de la marca [n] en el contenido.")
    chunk_id: str | None = Field(description="Nulo si el fragmento ya no está indexado.")
    document_id: str
    document_title: str
    document_version: str = Field(description="SHA-256 del PDF citado.")
    page_number: int = Field(ge=1, description="Página física del PDF, desde 1.")
    page_label: str | None = Field(description="Etiqueta impresa del PDF, si existe.")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class AnswerOut(Contract):
    id: int
    kind: AnswerKind
    status: AnswerStatus
    question: str
    year: Year | None
    subject: str | None
    topic: str | None
    content: str
    citations: list[CitationOut]
    created_at: datetime

    @model_validator(mode="after")
    def citations_match_status(self) -> Self:
        if (self.status == AnswerStatus.ANSWERED) != bool(self.citations):
            raise ValueError("Una respuesta 'answered' exige citas; 'no_evidence' no admite citas.")
        return self


# CU-03


class DocumentFields(Contract):
    title: Text
    year: Year
    subject: Text
    topic: Text


class DocumentReplace(DocumentFields):
    """Formulario multipart de CU-03 (actualizar)."""

    file: UploadFile = Field(description="PDF con texto seleccionable.")


class DocumentUpload(DocumentReplace):
    """Formulario multipart de CU-03 (subir)."""

    # Va en las rutas /documents/{document_id}: sin barras, espacios ni caracteres a codificar.
    document_id: Text = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="Identificador estable proporcionado por el operador.",
    )


class DocumentOut(DocumentFields):
    id: str
    filename: str
    version: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime


class IngestionReport(Contract):
    """Resultado de procesar un PDF; misma forma que `app.rag.index.index_document`."""

    document_id: str
    version: str
    status: Literal["indexed", "partial"]
    pages: int
    chunks: int
    no_text_pages: list[int]
    warnings: list[str]
    chunk_settings: dict[str, int]


class PageOut(Contract):
    document_id: str
    version: str
    number: int
    label: str | None
    text: str
    status: PageStatus


# CU-04


class HistoryEntryOut(Contract):
    id: int
    action: HistoryAction
    summary: str
    answer_id: int | None
    exam_id: int | None
    document_id: str | None
    conversation_id: int | None
    created_at: datetime


# CU-01 (chat con memoria)


class TurnRequest(Classification):
    """Pregunta de un turno; el hilo anterior lo pone el servidor."""

    question: Question


class MessageOut(Contract):
    id: int
    role: MessageRole
    content: str
    status: AnswerStatus | None = Field(description="Solo en mensajes del asistente.")
    answer_id: int | None
    citations: list[CitationOut]
    created_at: datetime


class ConversationOut(Contract):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class TurnOut(Contract):
    conversation: ConversationOut
    messages: list[MessageOut] = Field(description="El mensaje del usuario y la respuesta.")


# CU-06


ExamKind = Literal["development", "case", "multiple_choice", "true_false"]


class ExamRequest(Contract):
    year: Year
    subject: Text
    topic: Text | None = None
    question_count: int = Field(ge=1, le=20)
    difficulty: Difficulty
    # Por defecto, mixto: test, verdadero/falso, desarrollo y caso práctico.
    types: list[ExamKind] | None = Field(default=None, min_length=1, max_length=4)


class ExamQuestionOut(Contract):
    id: int
    position: int
    kind: QuestionKind
    statement: str
    options: list[str] | None
    points: float


class ExamOut(Contract):
    id: int
    year: Year
    subject: str
    topic: str | None
    difficulty: Difficulty
    question_count: int
    duration_minutes: int
    total_points: float
    status: Literal["pending", "ready", "failed"]
    error: str | None
    questions: list[ExamQuestionOut]
    created_at: datetime


class ExamAnswerOut(Contract):
    question_id: int
    position: int
    answer: str
    criteria: str | None
    citations: list[CitationOut] = Field(min_length=1)


# CU-10


class FeedbackRequest(Contract):
    kind: FeedbackKind
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    answer_id: Id | None = None
    exam_id: Id | None = None

    @model_validator(mode="after")
    def kind_fields(self) -> Self:
        if (self.kind == FeedbackKind.RATING) != (self.rating is not None):
            raise ValueError("'rating' es obligatorio solo cuando kind es 'rating'.")
        if self.kind != FeedbackKind.RATING and self.comment is None:
            raise ValueError("Los reportes de error y las sugerencias requieren 'comment'.")
        return self


class FeedbackOut(FeedbackRequest):
    id: int
    created_at: datetime


# Administración


Password = Annotated[RawPassword, StringConstraints(min_length=8, max_length=200)]  # MIN_PASSWORD
Name = Annotated[str, Field(min_length=1, max_length=200)]


class AdminUserOut(Contract):
    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    active_sessions: int


class AdminUserCreate(Contract):
    email: Annotated[str, Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    full_name: Name
    role: Role
    password: Password


class AdminUserUpdate(Contract):
    full_name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None


class PasswordReset(Contract):
    password: Password


class UserRef(Contract):
    id: int
    email: str
    full_name: str


class UserStats(Contract):
    total: int
    active: int
    by_role: dict[Role, int]


class DocumentStats(Contract):
    total: int
    active: int
    retired: int
    pages: int
    pages_without_text: int


class DayActivity(Contract):
    date: date
    queries: int
    generations: int
    exams: int


class ActivityStats(Contract):
    queries: int
    generations: int
    exams: int
    feedback: int
    no_evidence: int
    last_7_days: list[DayActivity]


class AdminStats(Contract):
    users: UserStats
    documents: DocumentStats
    activity: ActivityStats


class AdminAnswerOut(Contract):
    id: int
    kind: AnswerKind
    status: AnswerStatus
    question: str
    user: UserRef
    citations: int
    created_at: datetime


class AdminFeedbackOut(Contract):
    id: int
    kind: FeedbackKind
    rating: int | None
    comment: str | None
    answer_id: int | None
    exam_id: int | None
    user: UserRef | None
    created_at: datetime

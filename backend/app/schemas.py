"""Esquemas Pydantic del contrato /api/v1. Ver docs/api-contract.md."""

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    AnswerKind,
    AnswerStatus,
    Difficulty,
    DocumentStatus,
    FeedbackKind,
    HistoryAction,
    PageStatus,
    Role,
)

Year = Annotated[int, Field(ge=1, le=4)]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Question = Annotated[str, Field(min_length=1, max_length=1000)]


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
    password: Annotated[str, Field(min_length=1, max_length=200)]


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

    document_id: Text = Field(description="Identificador estable proporcionado por el operador.")


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
    created_at: datetime


# CU-06


class ExamRequest(Contract):
    year: Year
    subject: Text
    topic: Text | None = None
    question_count: int = Field(ge=1, le=50)
    difficulty: Difficulty


class ExamQuestionOut(Contract):
    id: int
    position: int
    statement: str


class ExamOut(Contract):
    id: int
    year: Year
    subject: str
    topic: str | None
    difficulty: Difficulty
    question_count: int
    questions: list[ExamQuestionOut]
    created_at: datetime


class ExamAnswerOut(Contract):
    question_id: int
    position: int
    answer: str
    citations: list[CitationOut] = Field(min_length=1)


# CU-10


class FeedbackRequest(Contract):
    kind: FeedbackKind
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    answer_id: int | None = None
    exam_id: int | None = None

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

"""Rutas /api/v1 del contrato. Responden 501 hasta implementarse en AT-08…AT-12, AT-27 y AT-28."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.security import HTTPBearer

from app.schemas import (
    AnswerOut,
    DocumentOut,
    DocumentReplace,
    DocumentUpload,
    ErrorResponse,
    ExamAnswerOut,
    ExamOut,
    ExamRequest,
    FeedbackOut,
    FeedbackRequest,
    GenerationRequest,
    HistoryEntryOut,
    IngestionReport,
    LoginRequest,
    PageOut,
    QueryRequest,
    TokenResponse,
    UserOut,
    Year,
)

ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 422, 501)}
NOT_FOUND = {404: {"model": ErrorResponse}}

# auto_error=False: los stubs responden 501; AT-08 validará el token y devolverá 401.
bearer = HTTPBearer(auto_error=False)

public = APIRouter(prefix="/api/v1", responses=ERRORS)
router = APIRouter(prefix="/api/v1", responses=ERRORS, dependencies=[Depends(bearer)])


def not_implemented() -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Endpoint definido en el contrato.")


# CU-00


@public.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest):
    """Todos los roles. Credenciales inválidas o usuario inactivo: 401."""
    not_implemented()


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout():
    """Todos los roles. Invalida el token actual."""
    not_implemented()


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me():
    """Todos los roles."""
    not_implemented()


# CU-01, CU-02


@router.post("/queries", response_model=AnswerOut, status_code=201, tags=["consulta"])
def create_query(body: QueryRequest):
    """Estudiante, Profesor. Respuesta restringida al corpus con citas (CU-05)."""
    not_implemented()


@router.post("/generations", response_model=AnswerOut, status_code=201, tags=["consulta"])
def create_generation(body: GenerationRequest):
    """Estudiante, Profesor. Resumen, esquema, cuadro o diagrama en texto, con citas."""
    not_implemented()


@router.get(
    "/answers/{answer_id}", response_model=AnswerOut, responses=NOT_FOUND, tags=["consulta"]
)
def get_answer(answer_id: int):
    """Autor de la respuesta. Permite reabrir una respuesta desde el historial."""
    not_implemented()


# CU-03, CU-05


@router.get("/documents", response_model=list[DocumentOut], tags=["corpus"])
def list_documents(
    year: Annotated[Year | None, Query()] = None,
    subject: str | None = None,
    topic: str | None = None,
    include_retired: bool = False,
):
    """Todos los roles; `include_retired` solo para Profesor y Administrador."""
    not_implemented()


@router.post(
    "/documents",
    response_model=IngestionReport,
    status_code=201,
    responses={409: {"model": ErrorResponse}},
    tags=["corpus"],
)
def upload_document(form: Annotated[DocumentUpload, Form(media_type="multipart/form-data")]):
    """Profesor, Administrador. 409 si `document_id` ya existe."""
    not_implemented()


@router.get(
    "/documents/{document_id}", response_model=DocumentOut, responses=NOT_FOUND, tags=["corpus"]
)
def get_document(document_id: str):
    """Todos los roles."""
    not_implemented()


@router.put(
    "/documents/{document_id}",
    response_model=IngestionReport,
    responses=NOT_FOUND,
    tags=["corpus"],
)
def replace_document(
    document_id: str, form: Annotated[DocumentReplace, Form(media_type="multipart/form-data")]
):
    """Profesor, Administrador. Sustituye PDF y metadatos y reindexa el documento."""
    not_implemented()


@router.delete("/documents/{document_id}", status_code=204, responses=NOT_FOUND, tags=["corpus"])
def retire_document(document_id: str):
    """Profesor, Administrador. Retira el documento: deja de usarse en respuestas nuevas."""
    not_implemented()


@router.get(
    "/documents/{document_id}/pages/{page_number}",
    response_model=PageOut,
    responses=NOT_FOUND,
    tags=["corpus"],
)
def get_page(document_id: str, page_number: int):
    """Todos los roles. Texto de la página vigente para verificar una cita (CU-05)."""
    not_implemented()


# CU-04


@router.get("/history", response_model=list[HistoryEntryOut], tags=["historial"])
def list_history(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Estudiante, Profesor. Entradas propias, de la más reciente a la más antigua."""
    not_implemented()


# CU-06


@router.post("/exams", response_model=ExamOut, status_code=201, tags=["examenes"])
def create_exam(body: ExamRequest):
    """Estudiante, Profesor. Genera el examen; las respuestas no se incluyen."""
    not_implemented()


@router.get("/exams", response_model=list[ExamOut], tags=["examenes"])
def list_exams():
    """Estudiante, Profesor. Exámenes propios."""
    not_implemented()


@router.get("/exams/{exam_id}", response_model=ExamOut, responses=NOT_FOUND, tags=["examenes"])
def get_exam(exam_id: int):
    """Autor del examen."""
    not_implemented()


@router.get(
    "/exams/{exam_id}/answers",
    response_model=list[ExamAnswerOut],
    responses=NOT_FOUND,
    tags=["examenes"],
)
def get_exam_answers(exam_id: int):
    """Autor del examen. Respuestas con sus citas."""
    not_implemented()


# CU-10


@router.post("/feedback", response_model=FeedbackOut, status_code=201, tags=["feedback"])
def create_feedback(body: FeedbackRequest):
    """Todos los roles. Valoración, error reportado o sugerencia."""
    not_implemented()

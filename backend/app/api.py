"""Rutas /api/v1 del contrato. Responden 501 hasta implementarse en AT-09…AT-12, AT-27 y AT-28.

Los permisos por rol (AT-08) ya se aplican: 401 sin sesión y 403 sin rol antes del 501.
"""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import (
    TOKEN_TTL,
    authenticate,
    create_session,
    current_token,
    current_user,
    require_roles,
    revoke_session,
)
from app.db import get_db
from app.models import Role, User
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

public = APIRouter(prefix="/api/v1", responses=ERRORS)
router = APIRouter(prefix="/api/v1", responses=ERRORS, dependencies=[Depends(current_user)])

STUDY = [Depends(require_roles(Role.STUDENT, Role.TEACHER))]
CORPUS = [Depends(require_roles(Role.TEACHER, Role.ADMIN))]


def not_implemented() -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Endpoint definido en el contrato.")


# CU-00


@public.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    """Todos los roles. Credenciales inválidas o usuario inactivo: 401."""
    user = authenticate(db, body.email, body.password)
    if user is None:
        # Mismo mensaje para correo inexistente, contraseña errónea o usuario inactivo.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos.")
    return TokenResponse(
        access_token=create_session(db, user),
        expires_in=int(TOKEN_TTL.total_seconds()),
        user=UserOut.model_validate(user, from_attributes=True),
    )


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(token: Annotated[str, Depends(current_token)], db: Annotated[Session, Depends(get_db)]):
    """Todos los roles. Invalida el token actual."""
    revoke_session(db, token)


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: Annotated[User, Depends(current_user)]):
    """Todos los roles."""
    return UserOut.model_validate(user, from_attributes=True)


# CU-01, CU-02


@router.post(
    "/queries", response_model=AnswerOut, status_code=201, dependencies=STUDY, tags=["consulta"]
)
def create_query(body: QueryRequest):
    """Estudiante, Profesor. Respuesta restringida al corpus con citas (CU-05)."""
    not_implemented()


@router.post(
    "/generations",
    response_model=AnswerOut,
    status_code=201,
    dependencies=STUDY,
    tags=["consulta"],
)
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
    user: Annotated[User, Depends(current_user)],
    year: Annotated[Year | None, Query()] = None,
    subject: str | None = None,
    topic: str | None = None,
    include_retired: bool = False,
):
    """Todos los roles; `include_retired` solo para Profesor y Administrador."""
    if include_retired and user.role == Role.STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción.")
    not_implemented()


@router.post(
    "/documents",
    response_model=IngestionReport,
    status_code=201,
    responses={409: {"model": ErrorResponse}},
    dependencies=CORPUS,
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
    dependencies=CORPUS,
    tags=["corpus"],
)
def replace_document(
    document_id: str, form: Annotated[DocumentReplace, Form(media_type="multipart/form-data")]
):
    """Profesor, Administrador. Sustituye PDF y metadatos y reindexa el documento."""
    not_implemented()


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    responses=NOT_FOUND,
    dependencies=CORPUS,
    tags=["corpus"],
)
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


@router.get(
    "/history", response_model=list[HistoryEntryOut], dependencies=STUDY, tags=["historial"]
)
def list_history(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Estudiante, Profesor. Entradas propias, de la más reciente a la más antigua."""
    not_implemented()


# CU-06


@router.post(
    "/exams", response_model=ExamOut, status_code=201, dependencies=STUDY, tags=["examenes"]
)
def create_exam(body: ExamRequest):
    """Estudiante, Profesor. Genera el examen; las respuestas no se incluyen."""
    not_implemented()


@router.get("/exams", response_model=list[ExamOut], dependencies=STUDY, tags=["examenes"])
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

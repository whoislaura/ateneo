"""Rutas /api/v1 del contrato.

Los permisos por rol (AT-08) se aplican: 401 sin sesión y 403 sin rol.
"""

import logging
import math
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app import citations, corpus, exams, generation, query
from app.auth import (
    TOKEN_TTL,
    authenticate,
    client_ip,
    create_session,
    current_token,
    current_user,
    login_limiter,
    require_roles,
    revoke_session,
)
from app.db import get_db
from app.models import (
    Answer,
    AnswerKind,
    AnswerStatus,
    Citation,
    Document,
    Exam,
    ExamQuestion,
    Feedback,
    HistoryAction,
    HistoryEntry,
    Role,
    User,
)
from app.schemas import (
    AnswerOut,
    CitationOut,
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
    Id,
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
UNAVAILABLE = {503: {"model": ErrorResponse}}
ai_log = logging.getLogger("ateneo.ai")


def ai_unavailable(exc: Exception, message: str) -> HTTPException:
    """503 del contrato, registrando la causa (tipo, código HTTP y mensaje del proveedor)."""
    cause = f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()
    if hasattr(exc, "read"):  # HTTPError: el cuerpo trae el motivo del proveedor, nunca la clave
        try:
            cause += f": {exc.read()[:300].decode('utf-8', 'replace')}"
        except OSError:
            pass
    elif str(exc):
        cause += f": {str(exc)[:300]}"
    ai_log.warning("ai_error", extra={"error": cause})
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, message)


public = APIRouter(prefix="/api/v1", responses=ERRORS)
router = APIRouter(prefix="/api/v1", responses=ERRORS, dependencies=[Depends(current_user)])

STUDY = [Depends(require_roles(Role.STUDENT, Role.TEACHER))]
CORPUS = [Depends(require_roles(Role.TEACHER, Role.ADMIN))]


# CU-00


@public.post(
    "/auth/login",
    response_model=TokenResponse,
    responses={429: {"model": ErrorResponse}},
    tags=["auth"],
)
def login(body: LoginRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    """Todos los roles. Credenciales inválidas o usuario inactivo: 401. Demasiados fallos: 429."""
    ip = client_ip(request)
    wait = login_limiter.retry_after(body.email, ip)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Demasiados intentos fallidos. Vuelva a intentarlo en {math.ceil(wait / 60)} min.",
            headers={"Retry-After": str(wait)},
        )
    user = authenticate(db, body.email, body.password)
    if user is None:
        login_limiter.fail(body.email, ip)
        # Mismo mensaje para correo inexistente, contraseña errónea o usuario inactivo.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos.")
    login_limiter.succeed(body.email)
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


def citation_out(citation: Citation) -> CitationOut:
    fields = ("position", "chunk_id", "document_id", "document_title", "document_version")
    return CitationOut(
        **{field: getattr(citation, field) for field in fields},
        page_number=citation.page_number,
        page_label=citation.page_label,
        start=citation.start_offset,
        end=citation.end_offset,
        quote=citation.quote,
    )


def answer_out(answer: Answer) -> AnswerOut:
    return AnswerOut(
        id=answer.id,
        kind=answer.kind,
        status=answer.status,
        question=answer.question,
        year=answer.year,
        subject=answer.subject,
        topic=answer.topic,
        content=answer.content,
        citations=[citation_out(citation) for citation in answer.citations],
        created_at=answer.created_at,
    )


@router.post(
    "/queries",
    response_model=AnswerOut,
    status_code=201,
    responses={503: {"model": ErrorResponse}},
    dependencies=STUDY,
    tags=["consulta"],
)
def create_query(
    body: QueryRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Estudiante, Profesor. Respuesta restringida al corpus con citas (CU-05)."""
    filters = body.model_dump(exclude={"question", "mode"})
    try:
        result = query.ask(db, body.question, mode=body.mode, **filters)
    except (ValueError, OSError) as exc:
        raise ai_unavailable(exc, "El servicio de respuestas no está disponible.") from exc
    answer_status, content, valid = citations.validate(db, result)
    answer = Answer(
        user_id=user.id,
        kind=AnswerKind.QUERY,
        status=answer_status,
        question=body.question,
        content=content,
        citations=valid,
        **filters,
    )
    db.add(answer)
    db.flush()
    db.add(
        HistoryEntry(
            user_id=user.id, action=HistoryAction.QUERY, summary=body.question, answer_id=answer.id
        )
    )
    db.commit()
    return answer_out(answer)


@router.post(
    "/generations",
    response_model=AnswerOut,
    status_code=201,
    responses={503: {"model": ErrorResponse}},
    dependencies=STUDY,
    tags=["consulta"],
)
def create_generation(
    body: GenerationRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Estudiante, Profesor. Resumen, esquema, cuadro o diagrama en texto, con citas (CU-05)."""
    filters = body.model_dump(exclude={"format", "prompt"})
    try:
        result = generation.generate(db, body.format, body.prompt, **filters)
    except (ValueError, OSError) as exc:
        raise ai_unavailable(exc, "El servicio de generación no está disponible.") from exc
    answer_status, content, valid = citations.validate(db, result)
    # La salida final debe conservar la estructura pedida tras renumerar las citas.
    if answer_status == AnswerStatus.ANSWERED and not generation.well_formed(body.format, content):
        answer_status, content, valid = AnswerStatus.NO_EVIDENCE, citations.NO_EVIDENCE, []
    answer = Answer(
        user_id=user.id,
        kind=AnswerKind(body.format),
        status=answer_status,
        question=body.prompt,
        content=content,
        citations=valid,
        **filters,
    )
    db.add(answer)
    db.flush()
    db.add(
        HistoryEntry(
            user_id=user.id,
            action=HistoryAction.GENERATION,
            summary=body.prompt,
            answer_id=answer.id,
        )
    )
    db.commit()
    return answer_out(answer)


@router.get(
    "/answers/{answer_id}", response_model=AnswerOut, responses=NOT_FOUND, tags=["consulta"]
)
def get_answer(
    answer_id: Id,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Autor de la respuesta. Permite reabrir una respuesta desde el historial."""
    answer = db.get(Answer, answer_id)
    if answer is None or answer.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Respuesta no encontrada.")
    return answer_out(answer)


# CU-03, CU-05


@router.get("/documents", response_model=list[DocumentOut], tags=["corpus"])
def list_documents(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    year: Annotated[Year | None, Query()] = None,
    subject: str | None = None,
    topic: str | None = None,
    include_retired: bool = False,
):
    """Todos los roles; `include_retired` solo para Profesor y Administrador."""
    if include_retired and user.role == Role.STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción.")
    rows = corpus.documents(
        db, year=year, subject=subject, topic=topic, include_retired=include_retired
    )
    return [DocumentOut.model_validate(row, from_attributes=True) for row in rows]


@router.post(
    "/documents",
    response_model=IngestionReport,
    status_code=201,
    responses={409: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, **UNAVAILABLE},
    dependencies=CORPUS,
    tags=["corpus"],
)
def upload_document(
    form: Annotated[DocumentUpload, Form(media_type="multipart/form-data")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Profesor, Administrador. 409 si `document_id` ya existe (también si está retirado)."""
    if db.get(Document, form.document_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un documento con ese id.")
    return corpus.ingest(db, form.document_id, form, user, HistoryAction.DOCUMENT_UPLOAD)


@router.get(
    "/documents/{document_id}", response_model=DocumentOut, responses=NOT_FOUND, tags=["corpus"]
)
def get_document(
    document_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Todos los roles; un documento retirado es 404 para Estudiante."""
    return DocumentOut.model_validate(corpus.visible(db, document_id, user), from_attributes=True)


@router.put(
    "/documents/{document_id}",
    response_model=IngestionReport,
    responses=NOT_FOUND | {413: {"model": ErrorResponse}} | UNAVAILABLE,
    dependencies=CORPUS,
    tags=["corpus"],
)
def replace_document(
    document_id: str,
    form: Annotated[DocumentReplace, Form(media_type="multipart/form-data")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Profesor, Administrador. Sustituye PDF y metadatos y reindexa; reactiva un retirado."""
    corpus.existing(db, document_id)
    return corpus.ingest(db, document_id, form, user, HistoryAction.DOCUMENT_UPDATE)


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    responses=NOT_FOUND,
    dependencies=CORPUS,
    tags=["corpus"],
)
def retire_document(
    document_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Profesor, Administrador. Retira el documento: deja de usarse en respuestas nuevas."""
    corpus.retire(db, document_id, user)


@router.get(
    "/documents/{document_id}/pages/{page_number}",
    response_model=PageOut,
    responses=NOT_FOUND,
    tags=["corpus"],
)
def get_page(
    document_id: str,
    page_number: Id,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Todos los roles. Texto de la página vigente para verificar una cita (CU-05)."""
    row = corpus.page(db, document_id, page_number, user)
    return PageOut(
        document_id=row.document_id,
        version=db.get(Document, row.document_id).version,
        number=row.number,
        label=row.label,
        text=row.text,
        status=row.status,
    )


# CU-04


@router.get(
    "/history", response_model=list[HistoryEntryOut], dependencies=STUDY, tags=["historial"]
)
def list_history(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[HistoryEntryOut]:
    """Estudiante, Profesor. Consultas y generaciones propias, más recientes primero."""
    statement = (
        select(HistoryEntry)
        .where(
            HistoryEntry.user_id == user.id,
            HistoryEntry.action.in_((HistoryAction.QUERY, HistoryAction.GENERATION)),
        )
        .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(statement)
    return [HistoryEntryOut.model_validate(row, from_attributes=True) for row in rows]


def delete_answers(db: Session, answer_ids: list[int]) -> None:
    """Borra respuestas y citas; el feedback queda desvinculado."""
    if not answer_ids:
        return
    db.execute(update(Feedback).where(Feedback.answer_id.in_(answer_ids)).values(answer_id=None))
    db.execute(delete(Citation).where(Citation.answer_id.in_(answer_ids)))
    db.execute(delete(Answer).where(Answer.id.in_(answer_ids)))


def deletable_history(
    db: Session, entry_id: int, user: User, action: tuple[HistoryAction, ...]
) -> HistoryEntry:
    entry = db.get(HistoryEntry, entry_id)
    if entry is None or entry.user_id != user.id or entry.action not in action:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entrada de historial no encontrada.")
    return entry


@router.delete(
    "/history/{entry_id}",
    status_code=204,
    responses=NOT_FOUND,
    dependencies=STUDY,
    tags=["historial"],
)
def delete_history_entry(
    entry_id: Id,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Autor. Borra una consulta o generación y su respuesta guardada."""
    entry = deletable_history(db, entry_id, user, (HistoryAction.QUERY, HistoryAction.GENERATION))
    if entry.answer_id is not None:
        delete_answers(db, [entry.answer_id])
    db.delete(entry)
    db.commit()


@router.delete("/history", status_code=204, dependencies=STUDY, tags=["historial"])
def clear_history(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Autor. Borra todas sus consultas y generaciones con sus respuestas."""
    study = (HistoryAction.QUERY, HistoryAction.GENERATION)
    answer_ids = list(
        db.scalars(
            select(HistoryEntry.answer_id).where(
                HistoryEntry.user_id == user.id,
                HistoryEntry.action.in_(study),
                HistoryEntry.answer_id.is_not(None),
            )
        )
    )
    delete_answers(db, answer_ids)
    db.execute(
        delete(HistoryEntry).where(HistoryEntry.user_id == user.id, HistoryEntry.action.in_(study))
    )
    db.commit()


# CU-06


@router.post(
    "/exams", response_model=ExamOut, status_code=201, dependencies=STUDY, tags=["examenes"]
)
def create_exam(
    body: ExamRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ExamOut:
    """Estudiante, Profesor. Genera el examen; las respuestas no se incluyen."""
    exam = Exam(user_id=user.id, questions=exams.make_questions(db, body), **body.model_dump())
    db.add(exam)
    db.flush()
    db.add(
        HistoryEntry(
            user_id=user.id, action=HistoryAction.EXAM, summary=exam.subject, exam_id=exam.id
        )
    )
    db.commit()
    return ExamOut.model_validate(exam, from_attributes=True)


@router.get("/exams", response_model=list[ExamOut], dependencies=STUDY, tags=["examenes"])
def list_exams(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ExamOut]:
    """Estudiante, Profesor. Exámenes propios."""
    statement = (
        select(Exam)
        .where(Exam.user_id == user.id)
        .options(selectinload(Exam.questions))
        .order_by(Exam.created_at.desc(), Exam.id.desc())
    )
    return [ExamOut.model_validate(exam, from_attributes=True) for exam in db.scalars(statement)]


def owned_exam(db: Session, exam_id: int, user: User) -> Exam:
    exam = db.get(Exam, exam_id)
    if exam is None or exam.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Examen no encontrado.")
    return exam


@router.get(
    "/exams/{exam_id}",
    response_model=ExamOut,
    responses=NOT_FOUND,
    dependencies=STUDY,
    tags=["examenes"],
)
def get_exam(
    exam_id: Id,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ExamOut:
    """Autor del examen."""
    return ExamOut.model_validate(owned_exam(db, exam_id, user), from_attributes=True)


@router.get(
    "/exams/{exam_id}/answers",
    response_model=list[ExamAnswerOut],
    responses=NOT_FOUND,
    dependencies=STUDY,
    tags=["examenes"],
)
def get_exam_answers(
    exam_id: Id,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ExamAnswerOut]:
    """Autor del examen. Respuestas con sus citas."""
    exam = owned_exam(db, exam_id, user)
    questions = db.scalars(
        select(ExamQuestion)
        .where(ExamQuestion.exam_id == exam.id)
        .options(selectinload(ExamQuestion.citations))  # sin una consulta de citas por pregunta
        .order_by(ExamQuestion.position)
    )
    return [
        ExamAnswerOut(
            question_id=question.id,
            position=question.position,
            answer=question.answer,
            citations=[citation_out(citation) for citation in question.citations],
        )
        for question in questions
    ]


# CU-10


@router.post(
    "/feedback", response_model=FeedbackOut, status_code=201, responses=NOT_FOUND, tags=["feedback"]
)
def create_feedback(
    body: FeedbackRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FeedbackOut:
    """Todos los roles. Valoración, error reportado o sugerencia."""
    if body.answer_id is not None:
        answer = db.get(Answer, body.answer_id)
        if answer is None or answer.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Respuesta no encontrada.")
    if body.exam_id is not None:
        owned_exam(db, body.exam_id, user)
    feedback = Feedback(user_id=user.id, **body.model_dump())
    db.add(feedback)
    db.commit()
    return FeedbackOut.model_validate(feedback, from_attributes=True)

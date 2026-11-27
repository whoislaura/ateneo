"""Rutas /api/v1/admin del panel de administración. Solo rol Administrador.

Cada acción sobre cuentas deja un log `admin_action` sin correos ni contraseñas.
"""

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import logs
from app.api import ERRORS, NOT_FOUND, answer_out
from app.auth import create_user, current_user, guard_last_admin, require_roles, set_password
from app.db import get_db
from app.models import (
    Answer,
    AnswerKind,
    AnswerStatus,
    AuthSession,
    Citation,
    Document,
    DocumentStatus,
    Exam,
    Feedback,
    FeedbackKind,
    Page,
    PageStatus,
    Role,
    User,
)
from app.schemas import (
    ActivityStats,
    AdminAnswerOut,
    AdminFeedbackOut,
    AdminStats,
    AdminUserCreate,
    AdminUserOut,
    AdminUserUpdate,
    AnswerOut,
    DayActivity,
    DocumentStats,
    ErrorResponse,
    Id,
    PasswordReset,
    UserRef,
    UserStats,
)

log = logging.getLogger("ateneo.admin")
CONFLICT = {409: {"model": ErrorResponse}}

router = APIRouter(
    prefix="/api/v1/admin",
    responses=ERRORS,
    dependencies=[Depends(require_roles(Role.ADMIN))],
    tags=["admin"],
)

Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(current_user)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]


def audit(action: str, target: int, admin: User) -> None:
    log.info(
        "admin_action",
        extra={"action": action, "target_user_id": target, "admin_user_id": admin.id},
    )


def conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


# Resumen


@router.get("/stats", response_model=AdminStats)
def stats(db: Db) -> AdminStats:
    users = db.execute(
        select(User.role, User.is_active, func.count()).group_by(User.role, User.is_active)
    )
    by_role = dict.fromkeys(Role, 0)
    active = 0
    for role, is_active, count in users:
        by_role[role] += count
        active += count if is_active else 0
    documents = dict(
        db.execute(select(Document.status, func.count()).group_by(Document.status)).all()
    )
    pages = dict(db.execute(select(Page.status, func.count()).group_by(Page.status)).all())
    answers = db.execute(
        select(Answer.kind, Answer.status, func.count()).group_by(Answer.kind, Answer.status)
    ).all()

    # Días UTC de hace 6 días a hoy. SQLite guarda las fechas sin zona (ya en UTC).
    today = datetime.now(UTC).date()
    days = {
        (today - timedelta(days=n)).isoformat(): {"queries": 0, "generations": 0, "exams": 0}
        for n in range(6, -1, -1)
    }
    since = datetime.combine(today - timedelta(days=6), time(), UTC)

    def utc_day(column):
        if db.get_bind().dialect.name == "sqlite":
            return func.date(column)
        return func.date(func.timezone("UTC", column))

    for model, kind in ((Answer, Answer.kind), (Exam, None)):
        day = utc_day(model.created_at)
        columns = (day, kind, func.count()) if kind is not None else (day, func.count())
        for day_value, *rest in db.execute(
            select(*columns).where(model.created_at >= since).group_by(*columns[:-1])
        ):
            field = (
                "exams"
                if kind is None
                else ("queries" if rest[0] == AnswerKind.QUERY else "generations")
            )
            if (key := str(day_value)) in days:
                days[key][field] += rest[-1]

    return AdminStats(
        users=UserStats(total=sum(by_role.values()), active=active, by_role=by_role),
        documents=DocumentStats(
            total=sum(documents.values()),
            active=sum(n for s, n in documents.items() if s != DocumentStatus.RETIRED),
            retired=documents.get(DocumentStatus.RETIRED, 0),
            pages=sum(pages.values()),
            pages_without_text=pages.get(PageStatus.NO_TEXT, 0),
        ),
        activity=ActivityStats(
            queries=sum(n for kind, _, n in answers if kind == AnswerKind.QUERY),
            generations=sum(n for kind, _, n in answers if kind != AnswerKind.QUERY),
            exams=db.scalar(select(func.count()).select_from(Exam)),
            feedback=db.scalar(select(func.count()).select_from(Feedback)),
            no_evidence=sum(n for _, s, n in answers if s == AnswerStatus.NO_EVIDENCE),
            last_7_days=[DayActivity(date=day, **counts) for day, counts in days.items()],
        ),
    )


# Cuentas


def users_query():
    """Usuarios con el número de sesiones vigentes, en una sola consulta."""
    sessions = (
        select(func.count())
        .where(AuthSession.user_id == User.id, AuthSession.expires_at > datetime.now(UTC))
        .scalar_subquery()
    )
    return select(User, sessions).order_by(User.created_at.desc(), User.id.desc())


def user_out(user: User, active_sessions: int) -> AdminUserOut:
    fields = ("id", "email", "full_name", "role", "is_active", "created_at")
    return AdminUserOut(
        **{field: getattr(user, field) for field in fields}, active_sessions=active_sessions
    )


def get_user_out(db: Session, user_id: int) -> AdminUserOut:
    row = db.execute(users_query().where(User.id == user_id)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    return user_out(*row)


def existing_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    return user


def revoke_all(db: Session, user: User) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    db: Db,
    q: str | None = None,
    role: Role | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[AdminUserOut]:
    statement = users_query().limit(limit).offset(offset)
    if q:
        statement = statement.where(
            or_(
                User.email.icontains(q, autoescape=True),
                User.full_name.icontains(q, autoescape=True),
            )
        )
    if role is not None:
        statement = statement.where(User.role == role)
    return [user_out(*row) for row in db.execute(statement)]


@router.post("/users", response_model=AdminUserOut, status_code=201, responses=CONFLICT)
def create_account(body: AdminUserCreate, admin: Admin, db: Db) -> AdminUserOut:
    """409 si el correo (normalizado a minúsculas) ya existe."""
    try:
        user = create_user(db, body.email, body.full_name, body.password, body.role)
    except IntegrityError as error:
        db.rollback()
        raise conflict("Ya existe un usuario con ese correo.") from error
    audit("user_create", user.id, admin)
    return user_out(user, 0)


@router.patch("/users/{user_id}", response_model=AdminUserOut, responses=NOT_FOUND | CONFLICT)
def update_account(user_id: Id, body: AdminUserUpdate, admin: Admin, db: Db) -> AdminUserOut:
    """Desactivar revoca las sesiones. 409 si deja al propio admin sin acceso o sin admins."""
    user = existing_user(db, user_id)
    changes = body.model_dump(exclude_none=True)
    loses_admin = (
        user.role == Role.ADMIN
        and user.is_active
        and (changes.get("role", Role.ADMIN) != Role.ADMIN or not changes.get("is_active", True))
    )
    if loses_admin and user.id == admin.id:
        raise conflict("No puede desactivarse ni quitarse el rol de administrador a sí mismo.")
    if loses_admin:
        guard_last_admin(db, user.id)
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("is_active") is False:
        revoke_all(db, user)
    db.commit()
    audit("user_update", user.id, admin)
    return get_user_out(db, user.id)


@router.post("/users/{user_id}/password", status_code=204, responses=NOT_FOUND)
def reset_password(user_id: Id, body: PasswordReset, admin: Admin, db: Db) -> None:
    """Cambia la contraseña y revoca las sesiones del usuario."""
    set_password(db, existing_user(db, user_id), body.password)
    audit("password_reset", user_id, admin)


@router.delete("/users/{user_id}/sessions", status_code=204, responses=NOT_FOUND)
def revoke_sessions(user_id: Id, admin: Admin, db: Db) -> None:
    revoke_all(db, existing_user(db, user_id))
    db.commit()
    audit("sessions_revoke", user_id, admin)


# Consultas y generaciones


def user_ref(user: User | None) -> UserRef | None:
    return user and UserRef(id=user.id, email=user.email, full_name=user.full_name)


@router.get("/answers", response_model=list[AdminAnswerOut])
def list_answers(
    db: Db,
    kind: AnswerKind | None = None,
    answer_status: Annotated[AnswerStatus | None, Query(alias="status")] = None,
    user_id: Id | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[AdminAnswerOut]:
    citations = select(func.count()).where(Citation.answer_id == Answer.id).scalar_subquery()
    filters = {Answer.kind: kind, Answer.status: answer_status, Answer.user_id: user_id}
    statement = (
        select(Answer, User, citations)
        .join(User, Answer.user_id == User.id)
        .where(*(column == value for column, value in filters.items() if value is not None))
        .order_by(Answer.created_at.desc(), Answer.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        AdminAnswerOut(
            id=answer.id,
            kind=answer.kind,
            status=answer.status,
            question=answer.question,
            user=user_ref(user),
            citations=count,
            created_at=answer.created_at,
        )
        for answer, user, count in db.execute(statement)
    ]


@router.get("/answers/{answer_id}", response_model=AnswerOut, responses=NOT_FOUND)
def get_answer(answer_id: Id, db: Db) -> AnswerOut:
    """Detalle completo de cualquier respuesta, sin restricción de autor."""
    answer = db.get(Answer, answer_id)
    if answer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Respuesta no encontrada.")
    return answer_out(answer)


# Feedback


@router.get("/feedback", response_model=list[AdminFeedbackOut])
def list_feedback(
    db: Db, kind: FeedbackKind | None = None, limit: Limit = 20, offset: Offset = 0
) -> list[AdminFeedbackOut]:
    statement = (
        select(Feedback, User)
        .outerjoin(User, Feedback.user_id == User.id)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if kind is not None:
        statement = statement.where(Feedback.kind == kind)
    fields = ("id", "kind", "rating", "comment", "answer_id", "exam_id", "created_at")
    return [
        AdminFeedbackOut(**{field: getattr(item, field) for field in fields}, user=user_ref(user))
        for item, user in db.execute(statement)
    ]


# Logs

LEVELS = logging.getLevelNamesMapping()


@router.get("/logs", response_model=list[dict[str, Any]])
def list_logs(
    level: Literal["INFO", "WARNING", "ERROR"] | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    """Últimas entradas del proceso (búfer en memoria de `app.logs`), más recientes primero."""
    minimum = LEVELS[level] if level else 0
    needle = (q or "").lower()
    result = []
    for entry in reversed(list(logs.RECENT)):  # copia: otro hilo puede estar escribiendo
        if LEVELS.get(entry["level"], 0) < minimum:
            continue
        haystack = (str(entry.get(key, "")) for key in ("message", "path", "request_id"))
        if needle and not any(needle in text.lower() for text in haystack):
            continue
        result.append(entry)
        if len(result) == limit:
            break
    return result

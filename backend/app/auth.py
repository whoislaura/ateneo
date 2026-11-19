"""CU-00: contraseñas, sesiones y permisos por rol.

Mantenimiento de usuarios (no hay registro público), desde backend/ con DATABASE_URL definida:
    uv run python -m app.auth create-user admin@upr.edu.cu --name "Nombre" --role admin
    uv run python -m app.auth set-password admin@upr.edu.cu
    uv run python -m app.auth set-role admin@upr.edu.cu --role teacher
    uv run python -m app.auth deactivate|activate admin@upr.edu.cu
    uv run python -m app.auth list-users
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db, session_factory
from app.models import AuthSession, Role, User

TOKEN_TTL = timedelta(seconds=int(os.environ.get("ATENEO_TOKEN_TTL_SECONDS", 8 * 3600)))
# scrypt: 32 MiB por hash. Los parámetros viajan en el hash, así que pueden subirse sin migrar.
SCRYPT = {"n": 2**15, "r": 8, "p": 1}
MIN_PASSWORD = 8

bearer = HTTPBearer(auto_error=False)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 2**20, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        computed = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(computed, base64.b64decode(digest))


@cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe())


def _token_hash(token: str) -> str:
    # El token tiene 256 bits aleatorios: SHA-256 basta, no necesita sal ni KDF.
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    # Sin usuario se verifica igual contra un hash ficticio: mismo tiempo, sin enumeración.
    valid = verify_password(password, user.password_hash if user else _dummy_hash())
    return user if user and valid and user.is_active else None


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, expires_at=now + TOKEN_TTL))
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    db.commit()


def unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Sesión no válida o expirada.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None:
        raise unauthorized()
    return credentials.credentials


def current_user(
    token: Annotated[str, Depends(current_token)], db: Annotated[Session, Depends(get_db)]
) -> User:
    user = db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.expires_at > datetime.now(UTC),
            User.is_active,
        )
    )
    if user is None:
        raise unauthorized()
    return user


def require_roles(*roles: Role):
    """Dependencia: exige sesión válida (401) y uno de `roles` (403)."""

    def check(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción.")
        return user

    return check


def create_user(db: Session, email: str, full_name: str, password: str, role: Role) -> User:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    user = User(
        email=email.strip().lower(),
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def find_user(db: Session, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise LookupError(f"No existe un usuario con el correo {email.strip().lower()}.")
    return user


def set_password(db: Session, user: User, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    user.password_hash = hash_password(password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Crea un usuario; pide la contraseña.")
    create.add_argument("email")
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=[r.value for r in Role], required=True)
    password = commands.add_parser(
        "set-password", help="Cambia la contraseña y revoca las sesiones abiertas."
    )
    password.add_argument("email")
    role = commands.add_parser("set-role", help="Cambia el rol de un usuario.")
    role.add_argument("email")
    role.add_argument("--role", choices=[r.value for r in Role], required=True)
    for name, help_text in (
        ("deactivate", "Desactiva el usuario y revoca sus sesiones."),
        ("activate", "Reactiva el usuario."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("email")
    commands.add_parser("list-users", help="Lista usuarios, rol y estado.")
    args = parser.parse_args(argv)

    try:
        with session_factory()() as db:
            if args.command == "list-users":
                for user in db.scalars(select(User).order_by(User.id)):
                    estado = "activo" if user.is_active else "inactivo"
                    print(f"{user.id}\t{user.email}\t{user.role.value}\t{estado}")
                return
            if args.command == "create-user":
                # La contraseña nunca va en argumentos: quedaría en el historial del shell.
                user = create_user(
                    db, args.email, args.name, _ask_password(parser), Role(args.role)
                )
                print(f"Usuario {user.id} creado: {user.email} ({user.role.value}).")
                return
            user = find_user(db, args.email)
            if args.command == "set-password":
                set_password(db, user, _ask_password(parser))
                print(f"Contraseña actualizada: {user.email}.")
            elif args.command == "set-role":
                user.role = Role(args.role)
                db.commit()
                print(f"Rol actualizado: {user.email} ({user.role.value}).")
            elif args.command == "deactivate":
                user.is_active = False
                db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
                db.commit()
                print(f"Usuario desactivado: {user.email}.")
            else:
                user.is_active = True
                db.commit()
                print(f"Usuario reactivado: {user.email}.")
    except (ValueError, LookupError) as error:
        parser.exit(1, f"{error}\n")
    except IntegrityError:
        parser.exit(1, "Ya existe un usuario con ese correo.\n")


def _ask_password(parser: argparse.ArgumentParser) -> str:
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repetir contraseña: "):
        parser.exit(1, "Las contraseñas no coinciden.\n")
    return password


if __name__ == "__main__":
    main()

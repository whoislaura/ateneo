"""Búsqueda de texto completo en español sobre los fragmentos.

`unaccent` es STABLE y no se puede usar en un índice; la función envoltorio
IMMUTABLE fija el diccionario y el esquema para que el resultado no dependa
del search_path.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public")
    op.execute(
        "CREATE FUNCTION public.ateneo_unaccent(text) RETURNS text "
        "LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT "
        "AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$"
    )
    # La consulta debe repetir exactamente esta expresión para usar el índice.
    op.execute(
        "CREATE INDEX ix_chunks_text_fts ON chunks "
        "USING gin (to_tsvector('spanish'::regconfig, ateneo_unaccent(text)))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_chunks_text_fts")
    op.execute("DROP FUNCTION public.ateneo_unaccent(text)")
    # Como con `vector` en 0001, la extensión se conserva.

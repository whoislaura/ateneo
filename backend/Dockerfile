FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
RUN useradd --create-home ateneo
USER ateneo
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000
# Migra antes de servir: un fallo de migración impide arrancar (y el healthcheck lo delata).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]

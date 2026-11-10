FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN useradd --create-home ateneo
USER ateneo
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

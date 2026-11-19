from http import HTTPStatus
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app import api, logs

logs.setup()
app = FastAPI(title="Ateneo API", version="0.1.0")
app.include_router(api.public)
app.include_router(api.router)


def error_response(status: int, code: str, message: str, details=None, headers=None):
    body = {"error": {"code": code, "message": message, "details": details}}
    return JSONResponse(jsonable_encoder(body), status_code=status, headers=headers)


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    return error_response(exc.status_code, code, str(exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(422, "validation_error", "Solicitud inválida.", exc.errors())


@app.middleware("http")
async def log_requests(request: Request, call_next):
    def internal_error(request_id: str) -> JSONResponse:
        details = {"request_id": request_id}
        return error_response(500, "internal_error", "Error interno del servidor.", details)

    return await logs.request_logging(request, call_next, internal_error)


class HealthResponse(BaseModel):
    status: Literal["ok"]


@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Indica que la API responde; no comprueba corpus, base de datos ni IA."""
    return HealthResponse(status="ok")

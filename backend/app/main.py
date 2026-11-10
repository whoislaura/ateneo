from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Ateneo API", version="0.1.0")


class HealthResponse(BaseModel):
    status: Literal["ok"]


@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Indica que la API responde; no comprueba corpus, base de datos ni IA."""
    return HealthResponse(status="ok")

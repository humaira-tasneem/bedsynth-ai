"""BedSynth AI FastAPI entry point."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app.database import engine, initialize_database
from app import models  # noqa: F401 - registers tables with Base.metadata
from app.routes import router as hospital_studio_router


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create tables and add only the columns needed by the first Hospital Studio schema.
    initialize_database()
    yield


app = FastAPI(
    title="BedSynth AI API",
    description="Workspace-scoped hospital, department, and bed configuration API.",
    version="0.1.0",
    lifespan=lifespan,
)

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(hospital_studio_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """Report API availability and whether the configured database can be queried."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return HealthResponse(status="ok", service="bedsynth-api", database="ok")

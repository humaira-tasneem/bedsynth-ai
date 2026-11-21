"""BedSynth AI FastAPI entry point."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.environment import load_backend_environment

load_backend_environment()

from app.database import engine, initialize_database
from app import models  # noqa: F401 - registers tables with Base.metadata
from app.routes import router as hospital_studio_router
from app.analytics_routes import router as analytics_router
from app.datasets_routes import router as datasets_router
from app.assistant_routes import router as assistant_router
from app.auth_routes import router as auth_router, admin_router
from app.dashboard_routes import router as dashboard_router, admin_router as admin_dashboard_router
from app.auth import FRONTEND_ORIGINS


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
    description="Workspace-scoped Hospital Studio and deterministic synthetic operations generation API.",
    version="0.1.0",
    lifespan=lifespan,
)

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(FRONTEND_ORIGINS or (frontend_origin,)),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
@app.middleware("http")
async def validate_browser_origin(request, call_next):
    """Reject cross-origin unsafe browser requests, including credentialed requests."""
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/v1/"):
        origin = request.headers.get("origin")
        cookie_present = "bedsynth_session=" in request.headers.get("cookie", "")
        if origin and origin.rstrip("/") not in FRONTEND_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed."})
        if cookie_present and not origin:
            return JSONResponse(status_code=403, content={"detail": "An allowed request origin is required."})
    return await call_next(request)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(admin_dashboard_router)
app.include_router(hospital_studio_router)
app.include_router(analytics_router)
app.include_router(datasets_router)
app.include_router(assistant_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """Report API availability and whether the configured database can be queried."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return HealthResponse(status="ok", service="bedsynth-api", database="ok")

"""Temporary, capability-based guest access to shared-hospital generation."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.auth import utc_now
from app.database import get_db
from app.models import Bed, Department, GenerationRun, GuestSession, Hospital, Workspace
from app.schemas import GenerationConfig, GenerationCreate, GenerationPreviewRead, GenerationRunRead, HospitalRead, WorkspaceRead, ValidationReportRead
from app.security import InMemoryWindowLimiter
from app.services.data_validation import persist_validation
from app.services.datasets import dataset_manifest, get_dataset_detail, preview_dataset_entity, stream_bed_inventory_csv, stream_entity_csv
from app.services.synthetic_generation import generate_dataset, preview_generation

router = APIRouter(prefix="/api/v1/guest", tags=["guest-access"])
GUEST_COOKIE = "bedsynth_guest_session"
GUEST_SESSION_HOURS = 24
GUEST_MAX_ADMISSIONS = 500
GUEST_MAX_RANGE_DAYS = 30  # Difference between inclusive endpoints: at most 31 calendar dates.
guest_session_limiter = InMemoryWindowLimiter()
guest_preview_limiter = InMemoryWindowLimiter()
guest_generation_limiter = InMemoryWindowLimiter()


class GuestSessionRead(BaseModel):
    active: bool = True
    expires_at: datetime


def _cookie_options() -> dict:
    same_site = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    secure_default = same_site == "none" or os.getenv("APP_ENV", "development").lower() == "production"
    secure = secure_default or os.getenv("SESSION_COOKIE_SECURE", "true" if secure_default else "false").lower() in {"1", "true", "yes"}
    return {"httponly": True, "secure": secure, "samesite": same_site, "path": "/", "max_age": GUEST_SESSION_HOURS * 3600}


def cleanup_expired_guest_sessions(db: Session) -> int:
    """Delete expired capabilities; SQLite FK cascades remove only their guest runs/data."""
    result = db.execute(delete(GuestSession).where(GuestSession.expires_at <= utc_now()))
    db.commit()
    return int(result.rowcount or 0)


def _session_or_401(request: Request, db: Session) -> GuestSession:
    token = request.cookies.get(GUEST_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Guest session is unavailable or expired.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.scalar(select(GuestSession).where(GuestSession.token_hash == token_hash))
    if session is None or session.expires_at.replace(tzinfo=timezone.utc) <= utc_now():
        raise HTTPException(status_code=401, detail="Guest session is unavailable or expired.")
    return session


def _guest_session(request: Request, db: Session = Depends(get_db)) -> GuestSession:
    return _session_or_401(request, db)


def _shared_hospital_or_404(db: Session, hospital_id: int) -> Hospital:
    hospital = db.scalar(select(Hospital).join(Workspace).where(
        Hospital.id == hospital_id,
        Hospital.is_archived.is_(False),
        Workspace.is_shared.is_(True),
    ))
    if hospital is None:
        raise HTTPException(status_code=404, detail="Shared hospital not found.")
    return hospital


def _check_guest_limits(config: GenerationConfig) -> None:
    if config.target_admissions > GUEST_MAX_ADMISSIONS:
        raise HTTPException(status_code=422, detail=f"Guest generation is limited to {GUEST_MAX_ADMISSIONS} admissions per dataset.")
    if (config.end_date - config.start_date).days > GUEST_MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail="Guest generation is limited to 31 calendar days per dataset.")


def _owned_run_or_404(db: Session, session: GuestSession, run_id: str) -> GenerationRun:
    run = db.scalar(select(GenerationRun).where(
        GenerationRun.run_id == run_id,
        GenerationRun.guest_session_id == session.id,
        GenerationRun.owner_user_id.is_(None),
        GenerationRun.deleted_at.is_(None),
    ))
    if run is None:
        raise HTTPException(status_code=404, detail="Guest dataset not found.")
    return run


@router.post("/sessions", response_model=GuestSessionRead, status_code=201)
def create_guest_session(request: Request, response: Response, db: Session = Depends(get_db)) -> GuestSession:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = guest_session_limiter.retry_after(client_ip, limit=5, window_seconds=3600)
    if retry_after is not None:
        raise HTTPException(status_code=429, detail="Guest access is temporarily rate-limited. Try again later.", headers={"Retry-After": str(retry_after)})
    guest_session_limiter.record(client_ip)
    cleanup_expired_guest_sessions(db)
    token = secrets.token_urlsafe(32)
    session = GuestSession(token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(), expires_at=utc_now() + timedelta(hours=GUEST_SESSION_HOURS))
    db.add(session)
    db.commit()
    db.refresh(session)
    response.set_cookie(GUEST_COOKIE, token, **_cookie_options())
    return session


@router.get("/session", response_model=GuestSessionRead)
def guest_session_status(session: GuestSession = Depends(_guest_session)) -> GuestSession:
    return session


@router.delete("/session", status_code=204)
def end_guest_session(response: Response, session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)) -> Response:
    db.delete(session)
    db.commit()
    options = _cookie_options()
    response.delete_cookie(GUEST_COOKIE, path="/", httponly=True, secure=options["secure"], samesite=options["samesite"])
    response.status_code = 204
    return response


@router.get("/workspaces", response_model=list[WorkspaceRead])
def list_shared_workspaces(_session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)) -> list[Workspace]:
    return list(db.scalars(select(Workspace).where(Workspace.is_shared.is_(True)).order_by(Workspace.name, Workspace.id)).all())


@router.get("/workspaces/{workspace_id}/hospitals", response_model=list[HospitalRead])
def list_shared_hospitals(workspace_id: int, _session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)) -> list[Hospital]:
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id, Workspace.is_shared.is_(True)))
    if workspace is None:
        raise HTTPException(status_code=404, detail="Shared workspace not found.")
    options = selectinload(Hospital.departments.and_(Department.is_archived.is_(False))).selectinload(Department.beds.and_(Bed.status != "retired"))
    query = select(Hospital).where(Hospital.workspace_id == workspace_id, Hospital.is_archived.is_(False)).options(options).order_by(Hospital.name)
    return list(db.scalars(query).all())


@router.post("/hospitals/{hospital_id}/generation-runs/preview", response_model=GenerationPreviewRead)
def guest_generation_preview(hospital_id: int, payload: GenerationConfig, request: Request,
                             session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)) -> GenerationPreviewRead:
    _shared_hospital_or_404(db, hospital_id)
    _check_guest_limits(payload)
    key = f"{session.id}:{request.client.host if request.client else 'unknown'}"
    retry_after = guest_preview_limiter.retry_after(key, limit=20, window_seconds=3600)
    if retry_after is not None:
        raise HTTPException(status_code=429, detail="Guest preview limit reached. Try again later.", headers={"Retry-After": str(retry_after)})
    guest_preview_limiter.record(key)
    preview = preview_generation(db, hospital_id, payload)
    if preview.projected_admissions > GUEST_MAX_ADMISSIONS:
        raise HTTPException(status_code=422, detail=f"This scenario would project more than {GUEST_MAX_ADMISSIONS} admissions. Reduce the target admission count.")
    return preview


@router.post("/hospitals/{hospital_id}/generation-runs", response_model=GenerationRunRead)
def guest_create_generation(hospital_id: int, payload: GenerationCreate, request: Request,
                            session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)) -> GenerationRun:
    _shared_hospital_or_404(db, hospital_id)
    _check_guest_limits(payload)
    key = f"{session.id}:{request.client.host if request.client else 'unknown'}"
    retry_after = guest_generation_limiter.retry_after(key, limit=5, window_seconds=86400)
    if retry_after is not None:
        raise HTTPException(status_code=429, detail="Guest generation limit reached. Try again tomorrow.", headers={"Retry-After": str(retry_after)})
    guest_generation_limiter.record(key)
    preview = preview_generation(db, hospital_id, payload)
    if preview.projected_admissions > GUEST_MAX_ADMISSIONS:
        raise HTTPException(status_code=422, detail=f"This scenario would project more than {GUEST_MAX_ADMISSIONS} admissions. Reduce the target admission count.")
    return generate_dataset(db, hospital_id, payload, guest_session_id=session.id)


@router.get("/generation-runs/{run_id}/dataset")
def guest_dataset_detail(run_id: str, session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)):
    _owned_run_or_404(db, session, run_id)
    return get_dataset_detail(db, run_id)


@router.get("/generation-runs/{run_id}/dataset/preview/{entity}")
def guest_dataset_preview(run_id: str, entity: str, page: int = 1, page_size: int = 25, q: str | None = None,
                          session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)):
    _owned_run_or_404(db, session, run_id)
    return preview_dataset_entity(db, run_id, entity, page=page, page_size=page_size, q=q)


@router.get("/generation-runs/{run_id}/dataset/export/{entity}")
def guest_dataset_export(run_id: str, entity: str, session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)):
    _owned_run_or_404(db, session, run_id)
    rows = stream_bed_inventory_csv(db, run_id) if entity == "bed_inventory" else stream_entity_csv(db, run_id, entity)
    return StreamingResponse(rows, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{entity}.csv"', "Cache-Control": "no-store",
    })


@router.get("/generation-runs/{run_id}/dataset/manifest")
def guest_dataset_manifest(run_id: str, session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)):
    _owned_run_or_404(db, session, run_id)
    return JSONResponse(content=jsonable_encoder(dataset_manifest(db, run_id)), headers={
        "Content-Disposition": f'attachment; filename="{run_id}-manifest.json"', "Cache-Control": "no-store",
    })


@router.post("/generation-runs/{run_id}/validations", response_model=ValidationReportRead, status_code=201)
def guest_validate_dataset(run_id: str, session: GuestSession = Depends(_guest_session), db: Session = Depends(get_db)):
    _owned_run_or_404(db, session, run_id)
    return persist_validation(db, run_id)

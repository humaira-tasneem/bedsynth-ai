"""Cookie-session authentication and role/resource authorization helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import GenerationRun, Hospital, User, UserSession, ValidationReport, Workspace

SESSION_COOKIE = "bedsynth_session"
SESSION_DAYS = 14


def configured_frontend_origins(app_env: str, frontend_origins: str | None, frontend_origin: str | None) -> tuple[str, ...]:
    """Resolve browser origins and fail closed for unsafe production CORS settings."""
    raw_origins = frontend_origins or frontend_origin
    is_production = app_env.strip().lower() == "production"
    if is_production and not raw_origins:
        raise RuntimeError("FRONTEND_ORIGINS must explicitly allow the deployed frontend in production.")

    origins = tuple(origin.strip().rstrip("/") for origin in (raw_origins or "http://localhost:3000").split(",") if origin.strip())
    if is_production:
        for origin in origins:
            parsed = urlsplit(origin)
            try:
                _ = parsed.port
            except ValueError:
                invalid_port = True
            else:
                invalid_port = False
            if (origin == "*" or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or invalid_port or parsed.path or parsed.query or parsed.fragment):
                raise RuntimeError("Production frontend origins must be exact HTTPS origins without paths or wildcards.")
    return origins


FRONTEND_ORIGINS = configured_frontend_origins(
    os.getenv("APP_ENV", "development"),
    os.getenv("FRONTEND_ORIGINS"),
    os.getenv("FRONTEND_ORIGIN"),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=64)
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=utc_now() + timedelta(days=SESSION_DAYS),
    ))
    db.commit()
    return token


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if session:
        db.delete(session)
        db.commit()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    now = utc_now()
    if session is None or session.expires_at.replace(tzinfo=timezone.utc) <= now or not session.user.is_active:
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=401, detail="Authentication required.")
    request.state.user = session.user
    return session.user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


def enforce_role_by_method(request: Request, user: User = Depends(current_user)) -> None:
    """Keep hospital configuration and administration endpoints admin-only."""
    if user.role == "admin" or request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    path = request.url.path
    allowed = (
        path.endswith("/generation-runs/preview")
        or ("/generation-runs" in path and request.method == "POST" and not path.endswith("/validations"))
        or path.endswith("/analytics/runs/compare")
        or (path.endswith("/validations") and request.method == "POST")
        or (path.startswith("/api/v1/generation-runs/") and path.endswith("/dataset") and request.method == "DELETE")
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Administrator access required for this action.")


def resource_access(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    """Restrict hospital reads to published inventory and all runs to their owner."""
    params = request.path_params
    workspace_id = params.get("workspace_id")
    if workspace_id is not None:
        workspace_exists = db.scalar(select(Workspace.id).where(Workspace.id == int(workspace_id)))
        if workspace_exists is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        public_catalog_route = request.url.path.endswith("/hospitals") or request.url.path.endswith("/networks")
        if user.role != "admin" and public_catalog_route:
            published_hospital_id = db.scalar(select(Hospital.id).where(
                Hospital.workspace_id == int(workspace_id),
                Hospital.available_to_users.is_(True),
                Hospital.is_archived.is_(False),
            ).limit(1))
            if published_hospital_id is None:
                raise HTTPException(status_code=404, detail="Workspace not found.")
    hospital_id = params.get("hospital_id")
    if hospital_id is not None and user.role != "admin":
        hospital = db.get(Hospital, int(hospital_id))
        if hospital is None or hospital.is_archived or not hospital.available_to_users:
            raise HTTPException(status_code=404, detail="Hospital not found.")
    run_id = params.get("run_id")
    if run_id is not None:
        run = db.get(GenerationRun, str(run_id))
        if run is None or run.guest_session_id is not None or run.deleted_at is not None or run.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="Dataset not found.")
    validation_id = params.get("validation_id")
    if validation_id is not None:
        report = db.get(ValidationReport, str(validation_id))
        run = db.get(GenerationRun, report.run_id) if report else None
        if run is None or run.guest_session_id is not None or run.deleted_at is not None or run.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="Validation report not found.")

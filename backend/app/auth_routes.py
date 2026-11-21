"""Authentication and administrative account/workspace endpoints."""

import hashlib
import os
import re
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE, SESSION_DAYS, admin_user, create_session,
    current_user, hash_password, normalize_email, revoke_session, verify_password,
)
from app.database import get_db
from app.models import GenerationRun, User, UserSession, Workspace
from app.schemas import (AdminUserItem, AdminUserPage, AdminUserStats, LoginRequest, RegisterRequest,
                         RegistrationActivity, UserRead, UserUpdate, WorkspaceRead, WorkspaceSharingUpdate)
from app.security import login_limiter, registration_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["administration"], dependencies=[Depends(admin_user)])
_DUMMY_PASSWORD_HASH = hash_password("bedsynth-invalid-login-dummy")


def _cookie_options() -> dict:
    same_site = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    secure_default = same_site == "none" or os.getenv("APP_ENV", "development").lower() == "production"
    configured_secure = os.getenv("SESSION_COOKIE_SECURE", "true" if secure_default else "false").lower() in {"1", "true", "yes"}
    secure = secure_default or configured_secure
    return {"httponly": True, "secure": secure, "samesite": same_site, "path": "/", "max_age": SESSION_DAYS * 86400}


@router.post("/register", response_model=UserRead, status_code=201)
def register(payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    client_ip = request.client.host if request.client else "unknown"
    retry = registration_limiter.retry_after(client_ip, limit=30, window_seconds=3600)
    if retry is not None:
        raise HTTPException(status_code=429, detail="Account creation is temporarily rate-limited. Try again later.", headers={"Retry-After": str(retry)})
    registration_limiter.record(client_ip)
    email = normalize_email(payload.email)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(payload.password), role="user", is_active=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    db.refresh(user)
    token = create_session(db, user)
    response.set_cookie(SESSION_COOKIE, token, **_cookie_options())
    return user


@router.post("/login", response_model=UserRead)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    email = normalize_email(payload.email)
    client_ip = request.client.host if request.client else "unknown"
    account_key = hashlib.sha256(f"{client_ip}\x00{email}".encode("utf-8")).hexdigest()
    for key, limit in ((account_key, 8), (f"ip:{client_ip}", 100)):
        retry = login_limiter.retry_after(key, limit=limit, window_seconds=900)
        if retry is not None:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.", headers={"Retry-After": str(retry)})
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    password_valid = verify_password(payload.password, user.password_hash) if user is not None and user.is_active else False
    if user is None or not user.is_active:
        # Keep the common unknown/inactive-account path close to the password-hash path.
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
    if not password_valid:
        login_limiter.record(account_key)
        login_limiter.record(f"ip:{client_ip}")
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    login_limiter.clear(account_key)
    login_limiter.clear(f"ip:{client_ip}")
    token = create_session(db, user)
    response.set_cookie(SESSION_COOKIE, token, **_cookie_options())
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_cookie_options()["secure"], samesite=_cookie_options()["samesite"])
    response.status_code = 204
    return response


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(current_user)) -> User:
    return user


@admin_router.get("/users/stats", response_model=AdminUserStats)
def user_stats(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    values = db.execute(select(
        func.count(User.id),
        func.coalesce(func.sum(case((User.is_active.is_(True), 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.role == "admin", 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.role == "user", 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.created_at >= now - timedelta(days=7), 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.created_at >= now - timedelta(days=30), 1), else_=0)), 0),
    )).one()
    total, active, admins, users, new7, new30 = (int(value or 0) for value in values)
    return {"total_accounts": total, "active_accounts": active, "deactivated_accounts": total - active,
            "administrators": admins, "standard_users": users, "registrations_7d": new7, "registrations_30d": new30}


@admin_router.get("/users/activity", response_model=RegistrationActivity)
def user_registration_activity(days: int = Query(default=30, ge=7, le=30), db: Session = Depends(get_db)) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    start_at = datetime.combine(start, datetime.min.time(), timezone.utc)
    end_at = datetime.combine(today + timedelta(days=1), datetime.min.time(), timezone.utc)
    rows = db.execute(select(func.date(User.created_at), func.count(User.id))
                      .where(User.created_at >= start_at, User.created_at < end_at)
                      .group_by(func.date(User.created_at))).all()
    counts = {str(day): int(total) for day, total in rows}
    return {"days": days, "items": [{"date": (start + timedelta(days=i)).isoformat(),
                                      "registrations": counts.get((start + timedelta(days=i)).isoformat(), 0)}
                                     for i in range(days)]}


def _admin_user_items(db: Session, users: list[User]) -> list[dict]:
    if not users:
        return []
    dataset_counts = dict(db.execute(select(GenerationRun.owner_user_id, func.count(GenerationRun.run_id))
        .where(GenerationRun.owner_user_id.in_([user.id for user in users]), GenerationRun.guest_session_id.is_(None),
               GenerationRun.deleted_at.is_(None), GenerationRun.status == "completed")
        .group_by(GenerationRun.owner_user_id)).all())
    return [{"id": user.id, "email": user.email, "role": user.role, "is_active": user.is_active,
             "created_at": user.created_at, "dataset_count": int(dataset_counts.get(user.id, 0))} for user in users]


@admin_router.get("/users", response_model=AdminUserPage)
def list_users(
    q: str | None = Query(default=None, max_length=254),
    role: str | None = Query(default=None, pattern="^(admin|user)$"),
    status: str | None = Query(default=None, pattern="^(active|deactivated)$"),
    sort: str = Query(default="newest", pattern="^(newest|oldest)$"),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    query = select(User)
    if q and q.strip():
        query = query.where(User.email.ilike(f"%{q.strip()}%"))
    if role:
        query = query.where(User.role == role)
    if status:
        query = query.where(User.is_active.is_(status == "active"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordering = (User.created_at.desc(), User.id.desc()) if sort == "newest" else (User.created_at.asc(), User.id.asc())
    users = list(db.scalars(query.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)).all())
    return {"items": _admin_user_items(db, users), "total": int(total), "page": page,
            "page_size": page_size, "pages": math.ceil(total / page_size) if total else 0}


@admin_router.get("/users/{user_id}", response_model=AdminUserItem)
def get_admin_user(user_id: int, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _admin_user_items(db, [user])[0]


@admin_router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, actor: User = Depends(admin_user), db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    changes = payload.model_dump(exclude_unset=True)
    if user.id == actor.id and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own administrator account.")
    if user.role == "admin" and user.is_active and (changes.get("role") == "user" or changes.get("is_active") is False):
        active_admins = db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="The last active administrator cannot be removed or deactivated.")
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("is_active") is False:
        db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    db.refresh(user)
    return user


@admin_router.get("/workspaces", response_model=list[WorkspaceRead])
def list_admin_workspaces(db: Session = Depends(get_db)) -> list[Workspace]:
    return list(db.scalars(select(Workspace).order_by(Workspace.id)).all())


@admin_router.patch("/workspaces/{workspace_id}/sharing", response_model=WorkspaceRead)
def set_workspace_sharing(workspace_id: int, payload: WorkspaceSharingUpdate, db: Session = Depends(get_db)) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    workspace.is_shared = payload.is_shared
    db.commit()
    db.refresh(workspace)
    return workspace

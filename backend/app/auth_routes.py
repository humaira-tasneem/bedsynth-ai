"""Authentication and administrative account/workspace endpoints."""

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE, SESSION_DAYS, admin_user, create_session,
    current_user, hash_password, normalize_email, revoke_session, verify_password,
)
from app.database import get_db
from app.models import User, UserSession, Workspace
from app.schemas import LoginRequest, RegisterRequest, UserRead, UserUpdate, WorkspaceRead, WorkspaceSharingUpdate

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["administration"], dependencies=[Depends(admin_user)])


def _cookie_options() -> dict:
    same_site = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    secure_default = same_site == "none" or os.getenv("APP_ENV", "development").lower() == "production"
    configured_secure = os.getenv("SESSION_COOKIE_SECURE", "true" if secure_default else "false").lower() in {"1", "true", "yes"}
    secure = secure_default or configured_secure
    return {"httponly": True, "secure": secure, "samesite": same_site, "path": "/", "max_age": SESSION_DAYS * 86400}


@router.post("/register", response_model=UserRead, status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> User:
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
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    email = normalize_email(payload.email)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
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


@admin_router.get("/users", response_model=list[UserRead])
def list_users(q: str | None = Query(default=None, max_length=254), db: Session = Depends(get_db)) -> list[User]:
    query = select(User)
    if q:
        query = query.where(User.email.ilike(f"%{q.strip()}%"))
    return list(db.scalars(query.order_by(User.email).limit(200)).all())


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

"""Authentication and administrative account/workspace endpoints."""

import hashlib
import os
import re
import math
from datetime import datetime, timedelta, timezone
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.auth import (
    SESSION_COOKIE, SESSION_DAYS, admin_user, create_session,
    current_user, hash_password, normalize_email, revoke_session, verify_password,
)
from app.database import get_db
from app.models import AccountActivityEvent, Department, GenerationRun, Hospital, User, UserSession, Workspace
from app.services.account_activity import record_account_activity
from app.schemas import (AdminUserItem, AdminUserPage, AdminUserStats, LoginRequest, RegisterRequest,
                         RegistrationActivity, RegistrationPeriodStats, RegistrationSeries, AccountSettingsRead,
                         PasswordChangeRequest, AccountActivityPage, UserRead, UserUpdate, WorkspaceRead, WorkspaceSharingUpdate)
from app.schemas import AdminUserOverviewDetail, AdminUserOverviewPage
from app.security import login_limiter, registration_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["administration"], dependencies=[Depends(admin_user)])
_DUMMY_PASSWORD_HASH = hash_password("bedsynth-invalid-login-dummy")
_ACTIVITY_TYPES = ("account_registered", "login_succeeded", "logout", "password_changed", "role_changed",
                   "account_activated", "account_deactivated", "dataset_generated", "dataset_soft_deleted")


def _date_bounds(from_date: date_type | None, to_date: date_type | None) -> tuple[datetime | None, datetime]:
    today = datetime.now(timezone.utc).date()
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="Start date must be on or before end date.")
    if to_date and to_date > today:
        raise HTTPException(status_code=422, detail="End date cannot be in the future.")
    if from_date and from_date > today:
        raise HTTPException(status_code=422, detail="Start date cannot be in the future.")
    start = datetime.combine(from_date, datetime.min.time(), timezone.utc) if from_date else None
    end_day = (to_date or today) + timedelta(days=1)
    return start, datetime.combine(end_day, datetime.min.time(), timezone.utc)


def _event_payload(event: AccountActivityEvent, actor_email: str | None, target_email: str | None) -> dict:
    return {"id": event.id, "actor_user_id": event.actor_user_id, "actor_email": actor_email,
            "target_user_id": event.target_user_id, "target_email": target_email, "run_id": event.run_id,
            "event_type": event.event_type, "occurred_at": event.occurred_at,
            "metadata": event.metadata_json or {}}


def _activity_page(db: Session, *, page: int, page_size: int, from_date: date_type | None,
                   to_date: date_type | None, event_type: str | None, actor_id: int | None,
                   target_id: int | None, q: str | None) -> dict:
    actor = aliased(User)
    target = aliased(User)
    query = select(AccountActivityEvent, actor.email, target.email).outerjoin(
        actor, actor.id == AccountActivityEvent.actor_user_id
    ).outerjoin(target, target.id == AccountActivityEvent.target_user_id)
    start, end = _date_bounds(from_date, to_date)
    if start:
        query = query.where(AccountActivityEvent.occurred_at >= start)
    query = query.where(AccountActivityEvent.occurred_at < end)
    if event_type:
        query = query.where(AccountActivityEvent.event_type == event_type)
    if actor_id:
        query = query.where(AccountActivityEvent.actor_user_id == actor_id)
    if target_id:
        query = query.where(AccountActivityEvent.target_user_id == target_id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(actor.email.ilike(needle), target.email.ilike(needle)))
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.execute(query.order_by(AccountActivityEvent.occurred_at.desc(), AccountActivityEvent.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_event_payload(event, actor_email, target_email) for event, actor_email, target_email in rows],
            "total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 0}


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
    record_account_activity(db, "account_registered", actor_user_id=user.id, target_user_id=user.id)
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
    user.last_login_at = datetime.now(timezone.utc)
    token = create_session(db, user)
    record_account_activity(db, "login_succeeded", actor_user_id=user.id, target_user_id=user.id)
    response.set_cookie(SESSION_COOKIE, token, **_cookie_options())
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    session = None
    if token:
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        session = db.scalar(select(UserSession).where(UserSession.token_hash == session_hash))
    user_id = session.user_id if session else None
    revoke_session(db, token)
    if user_id is not None:
        record_account_activity(db, "logout", actor_user_id=user_id, target_user_id=user_id)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_cookie_options()["secure"], samesite=_cookie_options()["samesite"])
    response.status_code = 204
    return response


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/settings", response_model=AccountSettingsRead)
def account_settings(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    session_hash = hashlib.sha256(token.encode()).hexdigest()
    session = db.scalar(select(UserSession).where(UserSession.token_hash == session_hash, UserSession.user_id == user.id))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return {"account": user, "session_expires_at": session.expires_at}


@router.post("/change-password", status_code=204)
def change_password(payload: PasswordChangeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=422, detail="Choose a new password different from the current password.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    record_account_activity(db, "password_changed", actor_user_id=user.id, target_user_id=user.id)
    return Response(status_code=204)


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


def _overview_user(user: User, dataset_count: int, latest_generation_at: datetime | None) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role,
            "registered_at": user.created_at, "completed_dataset_count": dataset_count,
            "latest_generation_at": latest_generation_at}


@admin_router.get("/overview/users", response_model=AdminUserOverviewPage)
def list_user_overview(page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
                       db: Session = Depends(get_db)) -> dict:
    total = int(db.scalar(select(func.count(User.id))) or 0)
    users = list(db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())
                            .offset((page - 1) * page_size).limit(page_size)).all())
    user_ids = [user.id for user in users]
    aggregates: dict[int, tuple[int, datetime | None]] = {}
    if user_ids:
        rows = db.execute(select(
            GenerationRun.owner_user_id,
            func.sum(case((GenerationRun.status == "completed", 1), else_=0)),
            func.max(func.coalesce(GenerationRun.completed_at, GenerationRun.started_at)),
        ).where(
            GenerationRun.owner_user_id.in_(user_ids), GenerationRun.guest_session_id.is_(None),
            GenerationRun.deleted_at.is_(None),
        ).group_by(GenerationRun.owner_user_id)).all()
        aggregates = {int(owner_id): (int(count or 0), latest) for owner_id, count, latest in rows}
    items = [_overview_user(user, *aggregates.get(user.id, (0, None))) for user in users]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 0}


@admin_router.get("/overview/users/{user_id}", response_model=AdminUserOverviewDetail)
def get_user_overview(user_id: int, page: int = Query(default=1, ge=1),
                      page_size: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    run_filter = (GenerationRun.owner_user_id == user.id, GenerationRun.guest_session_id.is_(None),
                  GenerationRun.deleted_at.is_(None))
    total_runs = int(db.scalar(select(func.count(GenerationRun.run_id)).where(*run_filter)) or 0)
    pairs = db.execute(select(GenerationRun, Hospital.name).join(
        Hospital, (Hospital.id == GenerationRun.hospital_id) & (Hospital.workspace_id == GenerationRun.workspace_id)
    ).where(*run_filter).order_by(GenerationRun.started_at.desc(), GenerationRun.run_id.desc())
                       .offset((page - 1) * page_size).limit(page_size)).all()
    runs = [run for run, _ in pairs]
    from app.services.datasets import _record_counts
    from app.services.analytics import scenario_name_for_run
    from datetime import date

    record_counts = _record_counts(db, runs)
    department_ids = {int(dept_id) for run in runs for dept_id in ((run.config or {}).get("resolved_department_ids") or [])
                      if isinstance(dept_id, int)}
    department_names: dict[tuple[int, int], str] = {}
    if department_ids:
        department_names = {(row.id, row.hospital_id): row.name for row in db.scalars(select(Department).where(
            Department.id.in_(department_ids), Department.hospital_id.in_({run.hospital_id for run in runs})
        )).all()}

    def parsed_date(value):
        try:
            return date.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return None

    def safe_integer(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def safe_percentage(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value)
        return None

    run_items = []
    for run, hospital_name in pairs:
        config = run.config or {}
        request_config = config.get("request") if isinstance(config.get("request"), dict) else {}
        counts = record_counts[run.run_id].model_dump()
        scenario_name = scenario_name_for_run(run)
        run_items.append({
            "run_id": run.run_id, "hospital_name": hospital_name, "status": run.status,
            "started_at": run.started_at, "completed_at": run.completed_at,
            "scenario_name": scenario_name if isinstance(scenario_name, str) else None,
            "configured_start_date": parsed_date(request_config.get("start_date")),
            "configured_end_date": parsed_date(request_config.get("end_date")),
            "target_admissions": safe_integer(request_config.get("target_admissions", request_config.get("admissions_count"))),
            "target_occupancy_pct": safe_percentage(request_config.get("target_occupancy_pct")), "seed": run.seed,
            "departments": [department_names[(dept_id, run.hospital_id)]
                            for dept_id in (config.get("resolved_department_ids") or [])
                            if (dept_id, run.hospital_id) in department_names],
            "record_counts": counts,
        })
    # Aggregate displayed dataset count uses the same completed, visible run definition as My Datasets.
    dataset_count, latest = db.execute(select(
        func.sum(case((GenerationRun.status == "completed", 1), else_=0)),
        func.max(func.coalesce(GenerationRun.completed_at, GenerationRun.started_at)),
    ).where(*run_filter)).one()
    return {**_overview_user(user, int(dataset_count or 0), latest), "runs": run_items,
            "total_runs": total_runs, "page": page, "page_size": page_size}


@admin_router.get("/users/activity", response_model=RegistrationActivity)
def user_registration_activity(days: int = Query(default=30, ge=7, le=30), db: Session = Depends(get_db)) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    start_at, end_at = _date_bounds(start, today)
    rows = db.execute(select(func.date(User.created_at), func.count(User.id))
                      .where(User.created_at >= start_at, User.created_at < end_at)
                      .group_by(func.date(User.created_at))).all()
    counts = {str(day): int(total) for day, total in rows}
    return {"days": days, "items": [{"date": (start + timedelta(days=i)).isoformat(),
                                      "registrations": counts.get((start + timedelta(days=i)).isoformat(), 0)}
                                     for i in range(days)]}


@admin_router.get("/users/registration-stats", response_model=RegistrationPeriodStats)
def registration_period_stats(from_date: date_type | None = None, to_date: date_type | None = None,
                             db: Session = Depends(get_db)) -> dict:
    start, end = _date_bounds(from_date, to_date)
    filters = [User.created_at < end]
    if start:
        filters.append(User.created_at >= start)
    values = db.execute(select(
        func.count(User.id),
        func.coalesce(func.sum(case((User.is_active.is_(True), 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.is_active.is_(False), 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.role == "admin", 1), else_=0)), 0),
        func.coalesce(func.sum(case((User.role == "user", 1), else_=0)), 0),
    ).where(*filters)).one()
    return {"from_date": from_date, "to_date": to_date, "registered_accounts": int(values[0] or 0),
            "active_registered_accounts": int(values[1] or 0), "deactivated_registered_accounts": int(values[2] or 0),
            "new_administrators": int(values[3] or 0), "new_standard_users": int(values[4] or 0)}


@admin_router.get("/users/registration-activity", response_model=RegistrationSeries)
def registration_series(from_date: date_type | None = None, to_date: date_type | None = None,
                        granularity: str = Query(default="auto", pattern="^(auto|day|week|month)$"),
                        db: Session = Depends(get_db)) -> dict:
    start, end = _date_bounds(from_date, to_date)
    if granularity == "auto":
        span = (to_date - from_date).days + 1 if from_date and to_date else 731
        group = "day" if span <= 90 else "week" if span <= 730 else "month"
    else:
        group = granularity
    bucket = func.date(User.created_at) if group == "day" else func.strftime("%Y-%W", User.created_at) if group == "week" else func.strftime("%Y-%m", User.created_at)
    query = select(bucket, func.count(User.id)).where(User.created_at < end)
    if start:
        query = query.where(User.created_at >= start)
    rows = db.execute(query.group_by(bucket).order_by(bucket)).all()
    counts = {str(period): int(count) for period, count in rows}
    if from_date and to_date:
        periods: list[str] = []
        if group == "day":
            cursor = from_date
            while cursor <= to_date:
                periods.append(cursor.isoformat())
                cursor += timedelta(days=1)
        elif group == "week":
            cursor = from_date - timedelta(days=from_date.weekday())
            while cursor <= to_date:
                periods.append(cursor.strftime("%Y-%W"))
                cursor += timedelta(days=7)
        else:
            year, month = from_date.year, from_date.month
            while (year, month) <= (to_date.year, to_date.month):
                periods.append(f"{year:04d}-{month:02d}")
                month += 1
                if month > 12:
                    year, month = year + 1, 1
        items = [{"period": period, "registrations": counts.get(period, 0)} for period in periods]
    else:
        items = [{"period": period, "registrations": count} for period, count in counts.items()]
    return {"from_date": from_date, "to_date": to_date, "granularity": group, "items": items}


@admin_router.get("/account-activity", response_model=AccountActivityPage)
def global_account_activity(
    from_date: date_type | None = None, to_date: date_type | None = None,
    event_type: str | None = Query(default=None, pattern="^(account_registered|login_succeeded|logout|password_changed|role_changed|account_activated|account_deactivated|dataset_generated|dataset_soft_deleted)$"),
    actor_id: int | None = Query(default=None, ge=1), target_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=254), page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db),
) -> dict:
    return _activity_page(db, page=page, page_size=page_size, from_date=from_date, to_date=to_date,
                          event_type=event_type, actor_id=actor_id, target_id=target_id, q=q)


@admin_router.get("/users/{user_id}/activity", response_model=AccountActivityPage)
def user_account_activity(
    user_id: int, from_date: date_type | None = None, to_date: date_type | None = None,
    event_type: str | None = Query(default=None, pattern="^(account_registered|login_succeeded|logout|password_changed|role_changed|account_activated|account_deactivated|dataset_generated|dataset_soft_deleted)$"),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _activity_page(db, page=page, page_size=page_size, from_date=from_date, to_date=to_date,
                          event_type=event_type, actor_id=None, target_id=user_id, q=None)


def _admin_user_items(db: Session, users: list[User]) -> list[dict]:
    if not users:
        return []
    dataset_counts = dict(db.execute(select(GenerationRun.owner_user_id, func.count(GenerationRun.run_id))
        .where(GenerationRun.owner_user_id.in_([user.id for user in users]), GenerationRun.guest_session_id.is_(None),
               GenerationRun.deleted_at.is_(None), GenerationRun.status == "completed")
        .group_by(GenerationRun.owner_user_id)).all())
    return [{"id": user.id, "email": user.email, "role": user.role, "is_active": user.is_active,
             "created_at": user.created_at, "last_login_at": user.last_login_at,
             "dataset_count": int(dataset_counts.get(user.id, 0))} for user in users]


@admin_router.get("/users", response_model=AdminUserPage)
def list_users(
    q: str | None = Query(default=None, max_length=254),
    role: str | None = Query(default=None, pattern="^(admin|user)$"),
    status: str | None = Query(default=None, pattern="^(active|deactivated)$"),
    sort: str = Query(default="newest", pattern="^(newest|oldest)$"),
    from_date: date_type | None = None, to_date: date_type | None = None,
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
    date_start, date_end = _date_bounds(from_date, to_date)
    if date_start:
        query = query.where(User.created_at >= date_start)
    if from_date or to_date:
        query = query.where(User.created_at < date_end)
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
    old_role, old_active = user.role, user.is_active
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("is_active") is False:
        db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    db.refresh(user)
    if user.role != old_role:
        record_account_activity(db, "role_changed", actor_user_id=actor.id, target_user_id=user.id,
                                metadata={"from_role": old_role, "to_role": user.role})
    if user.is_active != old_active:
        event_type = "account_activated" if user.is_active else "account_deactivated"
        record_account_activity(db, event_type, actor_user_id=actor.id, target_user_id=user.id,
                                metadata={"from_active": old_active, "to_active": user.is_active})
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

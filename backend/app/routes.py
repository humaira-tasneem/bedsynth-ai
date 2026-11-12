"""REST endpoints for workspace-scoped Hospital Studio configuration."""

from collections.abc import Generator
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.models import Bed, Department, Hospital, HospitalNetwork, Workspace
from app.schemas import (
    BedGenerationDepartmentResult,
    BedGenerationPreviewDepartment,
    BedGenerationPreviewRead,
    BedGenerationPreviewRequest,
    BedGenerationRead,
    BedGenerationRequest,
    BedCreate,
    BedRead,
    BedUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    HospitalCreate,
    HospitalRead,
    HospitalUpdate,
    NetworkCreate,
    NetworkRead,
    WorkspaceCreate,
    WorkspaceRead,
)

router = APIRouter(prefix="/api/v1", tags=["hospital-studio"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _commit(db: Session, conflict: str = "This record conflicts with an existing identifier.") -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict) from exc


def _hospital_or_404(db: Session, hospital_id: int) -> Hospital:
    hospital = db.scalar(select(Hospital).where(Hospital.id == hospital_id))
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    return hospital


def _workspace_hospital_or_404(db: Session, workspace_id: int, hospital_id: int) -> Hospital:
    hospital = db.scalar(
        select(Hospital)
        .where(Hospital.id == hospital_id, Hospital.workspace_id == workspace_id)
        .options(selectinload(Hospital.departments).selectinload(Department.beds))
    )
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found in this workspace.")
    return hospital


def _require_active_hospital(hospital: Hospital) -> None:
    if hospital.is_archived:
        raise HTTPException(status_code=409, detail="This hospital is archived. Restore it before editing its configuration.")


def _department_or_404(db: Session, hospital_id: int, department_id: int) -> Department:
    department = db.scalar(
        select(Department)
        .where(Department.id == department_id, Department.hospital_id == hospital_id)
        .options(selectinload(Department.beds))
    )
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found in this hospital.")
    return department


def _check_network(db: Session, workspace_id: int, network_id: int | None) -> None:
    if network_id is None:
        return
    network = db.scalar(
        select(HospitalNetwork).where(
            HospitalNetwork.id == network_id,
            HospitalNetwork.workspace_id == workspace_id,
            HospitalNetwork.is_archived.is_(False),
        )
    )
    if network is None:
        raise HTTPException(status_code=422, detail="Choose an active network in this workspace, or leave the hospital independent.")


def _active_bed_count(db: Session, department_id: int) -> int:
    return db.scalar(
        select(func.count(Bed.id)).where(Bed.department_id == department_id, Bed.status != "retired")
    ) or 0


def _check_department_capacity(db: Session, department: Department, *, adding: int = 1, excluding_bed_id: int | None = None) -> None:
    if department.bed_capacity is None:
        raise HTTPException(status_code=409, detail="Set a bed capacity for this department before adding beds.")
    occupied_slots = _active_bed_count(db, department.id)
    if excluding_bed_id is not None:
        existing = db.get(Bed, excluding_bed_id)
        if existing is not None and existing.department_id == department.id and existing.status != "retired":
            occupied_slots -= 1
    if occupied_slots + adding > department.bed_capacity:
        raise HTTPException(
            status_code=409,
            detail=f"This change exceeds the department's configured capacity of {department.bed_capacity} beds.",
        )


def _bed_generation_plan(db: Session, hospital_id: int, department_ids: list[int] | None) -> tuple[list[dict], str]:
    query = select(Department).where(Department.hospital_id == hospital_id)
    if department_ids is None:
        query = query.where(Department.is_archived.is_(False)).order_by(Department.name, Department.id)
    else:
        if len(set(department_ids)) != len(department_ids):
            raise HTTPException(status_code=422, detail="Department IDs must be unique.")
        query = query.where(Department.id.in_(department_ids)).order_by(Department.name, Department.id)
    departments = list(db.scalars(query).all())
    if department_ids is not None and len(departments) != len(department_ids):
        raise HTTPException(status_code=404, detail="One or more departments were not found in this hospital.")
    if any(department.is_archived for department in departments):
        raise HTTPException(status_code=409, detail="Archived departments cannot receive generated beds.")

    used_codes = {code.upper() for code in db.scalars(select(Bed.code).where(Bed.hospital_id == hospital_id)).all()}
    plan: list[dict] = []
    for department in departments:
        existing = _active_bed_count(db, department.id)
        if department.bed_capacity is None:
            count = 0
            note = "Set a bed capacity before generating beds."
        else:
            count = max(0, department.bed_capacity - existing)
            note = None if count else "Department already meets its configured capacity."
        prefix = (re.sub(r"[-_]?[0-9]+$", "", department.code).rstrip("-_").upper() or department.code.upper())[:34]
        codes: list[str] = []
        sequence = 1
        while len(codes) < count:
            candidate = f"{prefix}-{sequence:03d}"
            sequence += 1
            if candidate.upper() in used_codes:
                continue
            codes.append(candidate)
            used_codes.add(candidate.upper())
        plan.append({
            "department_id": department.id,
            "department_name": department.name,
            "department_code": department.code,
            "capacity": department.bed_capacity,
            "existing_beds": existing,
            "beds_to_create": count,
            "codes": codes,
            "note": note,
        })
    canonical = {
        "hospital_id": hospital_id,
        "departments": [
            {key: row[key] for key in ("department_id", "capacity", "existing_beds", "codes")}
            for row in plan
        ],
    }
    token = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return plan, token


def _generation_preview(hospital_id: int, plan: list[dict], token: str) -> BedGenerationPreviewRead:
    return BedGenerationPreviewRead(
        hospital_id=hospital_id,
        departments=[BedGenerationPreviewDepartment(
            department_id=row["department_id"],
            department_name=row["department_name"],
            department_code=row["department_code"],
            capacity=row["capacity"],
            existing_beds=row["existing_beds"],
            beds_to_create=row["beds_to_create"],
            first_bed_code=row["codes"][0] if row["codes"] else None,
            last_bed_code=row["codes"][-1] if row["codes"] else None,
            note=row["note"],
        ) for row in plan],
        total_to_create=sum(row["beds_to_create"] for row in plan),
        preview_token=token,
    )


@router.get("/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(db: Session = Depends(get_db)) -> list[Workspace]:
    return list(db.scalars(select(Workspace).order_by(Workspace.id)).all())


@router.post("/workspaces", response_model=WorkspaceRead, status_code=201)
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)) -> Workspace:
    workspace = Workspace(name=payload.name)
    db.add(workspace)
    _commit(db, "A workspace with this identifier already exists.")
    db.refresh(workspace)
    return workspace


@router.get("/workspaces/{workspace_id}/networks", response_model=list[NetworkRead])
def list_networks(workspace_id: int, include_archived: bool = False, db: Session = Depends(get_db)) -> list[HospitalNetwork]:
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    query = select(HospitalNetwork).where(HospitalNetwork.workspace_id == workspace_id)
    if not include_archived:
        query = query.where(HospitalNetwork.is_archived.is_(False))
    return list(db.scalars(query.order_by(HospitalNetwork.name)).all())


@router.post("/workspaces/{workspace_id}/networks", response_model=NetworkRead, status_code=201)
def create_network(workspace_id: int, payload: NetworkCreate, db: Session = Depends(get_db)) -> HospitalNetwork:
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    network = HospitalNetwork(workspace_id=workspace_id, name=payload.name)
    db.add(network)
    _commit(db, "A network with this name already exists in this workspace.")
    db.refresh(network)
    return network


@router.get("/workspaces/{workspace_id}/hospitals", response_model=list[HospitalRead])
def list_hospitals(
    workspace_id: int,
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[Hospital]:
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    query = select(Hospital).where(Hospital.workspace_id == workspace_id).options(
        selectinload(Hospital.departments).selectinload(Department.beds)
    )
    if not include_archived:
        query = query.where(Hospital.is_archived.is_(False))
    return list(db.scalars(query.order_by(Hospital.name)).all())


@router.post("/workspaces/{workspace_id}/hospitals", response_model=HospitalRead, status_code=201)
def create_hospital(workspace_id: int, payload: HospitalCreate, db: Session = Depends(get_db)) -> Hospital:
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    _check_network(db, workspace_id, payload.network_id)
    hospital = Hospital(workspace_id=workspace_id, **payload.model_dump())
    db.add(hospital)
    _commit(db, "A hospital with this code already exists in this workspace.")
    return _workspace_hospital_or_404(db, workspace_id, hospital.id)


@router.get("/workspaces/{workspace_id}/hospitals/{hospital_id}", response_model=HospitalRead)
def get_hospital(workspace_id: int, hospital_id: int, db: Session = Depends(get_db)) -> Hospital:
    return _workspace_hospital_or_404(db, workspace_id, hospital_id)


@router.patch("/workspaces/{workspace_id}/hospitals/{hospital_id}", response_model=HospitalRead)
def update_hospital(
    workspace_id: int,
    hospital_id: int,
    payload: HospitalUpdate,
    db: Session = Depends(get_db),
) -> Hospital:
    hospital = _workspace_hospital_or_404(db, workspace_id, hospital_id)
    changes = payload.model_dump(exclude_unset=True)
    if hospital.is_archived and changes.get("is_archived") is not False:
        raise HTTPException(status_code=409, detail="This hospital is archived. Restore it before changing its details.")
    if "network_id" in changes:
        _check_network(db, workspace_id, changes["network_id"])
    for field, value in changes.items():
        setattr(hospital, field, value)
    _commit(db, "A hospital with this code already exists in this workspace.")
    return _workspace_hospital_or_404(db, workspace_id, hospital_id)


@router.get("/hospitals/{hospital_id}/departments", response_model=list[DepartmentRead])
def list_departments(hospital_id: int, include_archived: bool = False, db: Session = Depends(get_db)) -> list[Department]:
    _hospital_or_404(db, hospital_id)
    query = select(Department).where(Department.hospital_id == hospital_id).options(selectinload(Department.beds))
    if not include_archived:
        query = query.where(Department.is_archived.is_(False))
    return list(db.scalars(query.order_by(Department.name)).all())


@router.post("/hospitals/{hospital_id}/departments", response_model=DepartmentRead, status_code=201)
def create_department(hospital_id: int, payload: DepartmentCreate, db: Session = Depends(get_db)) -> Department:
    hospital = _hospital_or_404(db, hospital_id)
    _require_active_hospital(hospital)
    department = Department(hospital_id=hospital_id, **payload.model_dump())
    db.add(department)
    _commit(db, "A department with this code already exists in this hospital.")
    return _department_or_404(db, hospital_id, department.id)


@router.patch("/hospitals/{hospital_id}/departments/{department_id}", response_model=DepartmentRead)
def update_department(
    hospital_id: int,
    department_id: int,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
) -> Department:
    hospital = _hospital_or_404(db, hospital_id)
    _require_active_hospital(hospital)
    department = _department_or_404(db, hospital_id, department_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("bed_capacity") is not None:
        current_count = _active_bed_count(db, department_id)
        if changes["bed_capacity"] < current_count:
            raise HTTPException(status_code=409, detail=f"Capacity cannot be lower than the {current_count} non-retired beds already assigned.")
    for field, value in changes.items():
        setattr(department, field, value)
    _commit(db, "A department with this code already exists in this hospital.")
    return _department_or_404(db, hospital_id, department_id)


@router.get("/hospitals/{hospital_id}/beds", response_model=list[BedRead])
def list_beds(
    hospital_id: int,
    department_id: int | None = None,
    include_retired: bool = False,
    db: Session = Depends(get_db),
) -> list[Bed]:
    _hospital_or_404(db, hospital_id)
    query = select(Bed).where(Bed.hospital_id == hospital_id)
    if department_id is not None:
        _department_or_404(db, hospital_id, department_id)
        query = query.where(Bed.department_id == department_id)
    if not include_retired:
        query = query.where(Bed.status != "retired")
    return list(db.scalars(query.order_by(Bed.code)).all())


@router.post("/hospitals/{hospital_id}/beds/generation-preview", response_model=BedGenerationPreviewRead)
def preview_bed_generation(
    hospital_id: int,
    payload: BedGenerationPreviewRequest,
    db: Session = Depends(get_db),
) -> BedGenerationPreviewRead:
    hospital = _hospital_or_404(db, hospital_id)
    _require_active_hospital(hospital)
    plan, token = _bed_generation_plan(db, hospital_id, payload.department_ids)
    return _generation_preview(hospital_id, plan, token)


@router.post("/hospitals/{hospital_id}/beds/generate", response_model=BedGenerationRead)
def generate_beds(
    hospital_id: int,
    payload: BedGenerationRequest,
    db: Session = Depends(get_db),
) -> BedGenerationRead:
    if not payload.confirmed:
        raise HTTPException(status_code=422, detail="Confirm the bed generation preview before creating beds.")
    try:
        # Serialize SQLite writers before recounting inventory so concurrent requests
        # cannot both consume the same remaining capacity.
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        hospital = _hospital_or_404(db, hospital_id)
        _require_active_hospital(hospital)
        plan, current_token = _bed_generation_plan(db, hospital_id, payload.department_ids)
        if current_token != payload.preview_token:
            db.rollback()
            raise HTTPException(status_code=409, detail="Bed inventory changed after preview. Review a fresh preview before confirming.")

        created = 0
        for row in plan:
            for code in row["codes"]:
                db.add(Bed(
                    hospital_id=hospital_id,
                    department_id=row["department_id"],
                    code=code,
                    category="general",
                    status="operational",
                ))
                created += 1
        db.commit()
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A bed identifier conflicted with existing inventory. Review a fresh preview.") from exc
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bed inventory is being updated. Review a fresh preview and try again.") from exc
    except Exception:
        db.rollback()
        raise

    return BedGenerationRead(
        hospital_id=hospital_id,
        beds_created=created,
        departments=[BedGenerationDepartmentResult(
            department_id=row["department_id"],
            department_name=row["department_name"],
            beds_created=row["beds_to_create"],
        ) for row in plan],
    )


@router.post("/hospitals/{hospital_id}/departments/{department_id}/beds", response_model=BedRead, status_code=201)
def create_bed(hospital_id: int, department_id: int, payload: BedCreate, db: Session = Depends(get_db)) -> Bed:
    hospital = _hospital_or_404(db, hospital_id)
    _require_active_hospital(hospital)
    department = _department_or_404(db, hospital_id, department_id)
    if department.is_archived:
        raise HTTPException(status_code=409, detail="This department is archived and cannot accept new beds.")
    _check_department_capacity(db, department)
    bed = Bed(hospital_id=hospital_id, department_id=department_id, **payload.model_dump())
    db.add(bed)
    _commit(db, "A bed with this code already exists in this hospital.")
    db.refresh(bed)
    return bed


@router.patch("/hospitals/{hospital_id}/beds/{bed_id}", response_model=BedRead)
def update_bed(hospital_id: int, bed_id: int, payload: BedUpdate, db: Session = Depends(get_db)) -> Bed:
    hospital = _hospital_or_404(db, hospital_id)
    _require_active_hospital(hospital)
    bed = db.scalar(select(Bed).where(Bed.id == bed_id, Bed.hospital_id == hospital_id))
    if bed is None:
        raise HTTPException(status_code=404, detail="Bed not found in this hospital.")
    changes = payload.model_dump(exclude_unset=True)
    target_department_id = changes.pop("department_id", bed.department_id)
    target_department = _department_or_404(db, hospital_id, target_department_id)
    if target_department.is_archived and target_department_id != bed.department_id:
        raise HTTPException(status_code=409, detail="Beds cannot be moved into an archived department.")
    new_status = changes.get("status", bed.status)
    if new_status != "retired" and (target_department_id != bed.department_id or bed.status == "retired"):
        _check_department_capacity(db, target_department, excluding_bed_id=bed_id if target_department_id == bed.department_id else None)
    for field, value in changes.items():
        setattr(bed, field, value)
    bed.department_id = target_department_id
    _commit(db, "A bed with this code already exists in this hospital.")
    db.refresh(bed)
    return bed

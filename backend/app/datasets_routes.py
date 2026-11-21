"""Workspace-scoped dataset library and read-only run exports."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.routes import get_db
from app.auth import current_user, enforce_role_by_method, resource_access
from app.schemas import DatasetLibraryRead, DatasetPreviewRead, DatasetRunDetailRead
from app.services.datasets import dataset_manifest, get_dataset_detail, list_datasets, preview_dataset_entity, stream_bed_inventory_csv, stream_entity_csv

router = APIRouter(prefix="/api/v1", tags=["datasets"], dependencies=[Depends(current_user), Depends(enforce_role_by_method), Depends(resource_access)])


@router.get("/workspaces/{workspace_id}/datasets", response_model=DatasetLibraryRead)
def workspace_datasets(
    workspace_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    hospital_id: int | None = Query(default=None, ge=1),
    status: Literal["generating", "completed", "failed"] | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    db: Session = Depends(get_db),
    user=Depends(current_user),
) -> dict:
    return list_datasets(db, workspace_id, page=page, page_size=page_size, q=q,
                         hospital_id=hospital_id, status=status, sort=sort,
                         owner_user_id=None if user.role == "admin" else user.id,
                         include_deleted=user.role == "admin")


@router.get("/generation-runs/{run_id}/dataset", response_model=DatasetRunDetailRead)
def dataset_detail(run_id: str, db: Session = Depends(get_db)) -> DatasetRunDetailRead:
    return get_dataset_detail(db, run_id)


@router.get("/generation-runs/{run_id}/dataset/preview/{entity}", response_model=DatasetPreviewRead)
def dataset_preview(
    run_id: str,
    entity: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
) -> dict:
    return preview_dataset_entity(db, run_id, entity, page=page, page_size=page_size, q=q)


@router.get("/generation-runs/{run_id}/dataset/export/{entity}")
def export_dataset_entity(run_id: str, entity: str, db: Session = Depends(get_db)) -> StreamingResponse:
    rows = stream_bed_inventory_csv(db, run_id) if entity == "bed_inventory" else stream_entity_csv(db, run_id, entity)
    return StreamingResponse(
        rows,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{entity}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/generation-runs/{run_id}/dataset/manifest")
def export_dataset_manifest(run_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    manifest = dataset_manifest(db, run_id)
    return JSONResponse(
        content=jsonable_encoder(manifest),
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}-manifest.json"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/generation-runs/{run_id}/dataset", status_code=204)
def soft_delete_dataset(run_id: str, db: Session = Depends(get_db)) -> Response:
    from datetime import datetime, timezone
    from app.models import GenerationRun

    run = db.get(GenerationRun, run_id)
    if run is None or run.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    run.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=204)

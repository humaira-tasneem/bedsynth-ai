"""Workspace-scoped, non-generative assistant configuration endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.routes import get_db
from app.auth import current_user, enforce_role_by_method
from app.models import Hospital, User, Workspace
from app.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantConfigValidationRequest,
    AssistantConfigValidationResponse,
    AssistantServiceStatusRead,
)
from app.services.assistant import (
    chat_with_assistant,
    gemini_key_is_configured,
    groq_key_is_configured,
    validate_assistant_config,
)

router = APIRouter(prefix="/api/v1/assistant", tags=["generation-assistant"], dependencies=[Depends(current_user), Depends(enforce_role_by_method)])


@router.get("/status", response_model=AssistantServiceStatusRead)
def assistant_status() -> AssistantServiceStatusRead:
    """Report backend key presence only; provider availability is learned from requests."""
    return AssistantServiceStatusRead(
        gemini_key_configured=gemini_key_is_configured(),
        groq_key_configured=groq_key_is_configured(),
    )


@router.post("/chat", response_model=AssistantChatResponse)
def assistant_chat(payload: AssistantChatRequest, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Interpret bounded conversation text; never writes or generates records."""
    workspace = db.get(Workspace, payload.workspace_id)
    if workspace is None or (user.role != "admin" and not workspace.is_shared):
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return chat_with_assistant(db, payload)


@router.post("/validate-config", response_model=AssistantConfigValidationResponse)
def validate_config(
    payload: AssistantConfigValidationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Validate edited assistant configuration independently of Gemini."""
    workspace = db.get(Workspace, payload.workspace_id)
    if workspace is None or (user.role != "admin" and not workspace.is_shared):
        raise HTTPException(status_code=404, detail="Hospital not found in this workspace.")
    hospital = db.get(Hospital, payload.hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found in this workspace.")
    if hospital.workspace_id != workspace.id:
        if user.role != "admin":
            raise HTTPException(status_code=404, detail="Hospital not found in this workspace.")
    if user.role != "admin" and hospital.is_archived:
        raise HTTPException(status_code=404, detail="Hospital not found in this workspace.")
    configuration = validate_assistant_config(db, payload)
    return {"valid": True, "configuration": configuration}

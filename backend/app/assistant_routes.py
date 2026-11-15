"""Workspace-scoped, non-generative assistant configuration endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.routes import get_db
from app.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantConfigValidationRequest,
    AssistantConfigValidationResponse,
)
from app.services.assistant import chat_with_assistant, validate_assistant_config

router = APIRouter(prefix="/api/v1/assistant", tags=["generation-assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
def assistant_chat(payload: AssistantChatRequest, db: Session = Depends(get_db)) -> dict:
    """Interpret bounded conversation text; never writes or generates records."""
    return chat_with_assistant(db, payload)


@router.post("/validate-config", response_model=AssistantConfigValidationResponse)
def validate_config(
    payload: AssistantConfigValidationRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Validate edited assistant configuration independently of Gemini."""
    configuration = validate_assistant_config(db, payload)
    return {"valid": True, "configuration": configuration}

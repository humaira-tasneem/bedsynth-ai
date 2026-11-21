"""Best-effort writes for the append-only account activity log."""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AccountActivityEvent

logger = logging.getLogger(__name__)
_SAFE_METADATA_KEYS = {"from_role", "to_role", "from_active", "to_active"}


def record_account_activity(
    db: Session,
    event_type: str,
    *,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    run_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Persist an event after the primary action has committed.

    Audit persistence is non-critical: failure rolls back only this follow-up write
    and never rolls back the already committed account or dataset operation.
    """
    safe_metadata = {key: value for key, value in (metadata or {}).items() if key in _SAFE_METADATA_KEYS}
    try:
        db.add(AccountActivityEvent(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            run_id=run_id,
            event_type=event_type,
            metadata_json=safe_metadata,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()  # A repeated idempotent generation event is already recorded.
    except Exception:
        db.rollback()
        logger.warning("Account activity event persistence failed (type=%s).", event_type)

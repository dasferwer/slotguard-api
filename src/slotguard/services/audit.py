from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from slotguard.models import AuditLog


def add_audit_log(
    db: Session,
    *,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )

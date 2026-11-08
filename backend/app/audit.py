from sqlalchemy.orm import Session

from app.clock import now
from app.models import AuditLog


def log(db: Session, actor: str, action: str, entity: str, entity_id=None, detail: dict | None = None) -> None:
    db.add(AuditLog(ts=now().replace(tzinfo=None), actor=actor, action=action, entity=entity,
                    entity_id=None if entity_id is None else str(entity_id), detail=detail))

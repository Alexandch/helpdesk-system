from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.db.session import get_db
from app.models.system import AuditLog
from app.models.user import User
from app.schemas.system import AuditLogRead


router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    return list(db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)))

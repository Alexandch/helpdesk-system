from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.system import Notification
from app.models.user import User
from app.schemas.system import NotificationCount, NotificationRead
from app.services.event_fallback import send_email_notification


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread_only: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100)))


@router.get("/unread-count", response_model=NotificationCount)
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationCount:
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )
    return NotificationCount(unread=count or 0)


@router.post("/test-email")
def send_test_email(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    title = "Тестовое уведомление HelpDesk"
    body = "Если вы получили это письмо, SMTP-уведомления HelpDesk настроены корректно."
    notification = Notification(
        user_id=current_user.id,
        event_type="email.test",
        title=title,
        body=body,
        entity_id=None,
        is_read=False,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    try:
        email_status = send_email_notification(current_user, title, body)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Email delivery failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
    return {"notification_id": notification.id, "email_status": email_status}


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_as_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/read-all")
def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"updated": result.rowcount}

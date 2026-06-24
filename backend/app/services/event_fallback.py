import logging
import smtplib
from email.message import EmailMessage
from uuid import uuid4

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.system import AuditLog, Notification
from app.models.user import User


logger = logging.getLogger(__name__)


def notification_text(event_type: str, payload: dict) -> tuple[str, str]:
    ticket_title = payload.get("title", "Обращение")
    status_labels = {
        "OPEN": "Открыто",
        "IN_PROGRESS": "В работе",
        "RESOLVED": "Решено",
        "CLOSED": "Закрыто",
    }
    if event_type == "ticket.created":
        return "Обращение создано", f"Обращение «{ticket_title}» успешно зарегистрировано."
    if event_type == "ticket.assigned":
        return "Назначен исполнитель", f"Для обращения «{ticket_title}» назначен исполнитель."
    if event_type == "message.created":
        preview = payload.get("message_preview", "")
        return "Новое сообщение", f"В обращении «{ticket_title}» появилось сообщение: {preview}"

    changes = payload.get("changes", {})
    if "status" in changes:
        status = status_labels.get(changes["status"], changes["status"])
        return "Статус изменён", f"Статус обращения «{ticket_title}» изменён на «{status}»."
    if "assignee_id" in changes:
        return "Исполнитель изменён", f"В обращении «{ticket_title}» изменён исполнитель."
    return "Обращение обновлено", f"Обращение «{ticket_title}» было обновлено."


def infer_entity(payload: dict) -> tuple[str, str | None]:
    if "ticket_id" in payload:
        return "ticket", payload["ticket_id"]
    if "message_id" in payload:
        return "message", payload["message_id"]
    return "system", None


def send_email_notification(user: User, title: str, body: str) -> None:
    if not settings.email_delivery_enabled:
        logger.info("Email notification skipped by settings: user=%s title=%s", user.email, title)
        return
    if not user.email_notifications_enabled:
        logger.info("Email notification skipped by user preference: user=%s", user.email)
        return
    if not settings.smtp_host:
        logger.warning("Email delivery is enabled, but SMTP_HOST is not configured")
        return

    message = EmailMessage()
    message["Subject"] = title
    message["From"] = settings.smtp_from
    message["To"] = user.email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    logger.info("Email notification sent: user=%s title=%s", user.email, title)


def save_notification_event(event_type: str, payload: dict) -> None:
    recipient_ids = list(dict.fromkeys(payload.get("recipient_ids", [])))
    if not recipient_ids:
        logger.info("Fallback notification skipped: no recipients for event=%s", event_type)
        return

    title, body = notification_text(event_type, payload)
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.id.in_(recipient_ids), User.is_active.is_(True)).all()
        user_by_id = {user.id: user for user in users}
        for user_id in recipient_ids:
            if user_id not in user_by_id:
                continue
            db.add(
                Notification(
                    user_id=user_id,
                    event_type=event_type,
                    title=title,
                    body=body,
                    entity_id=payload.get("ticket_id"),
                    is_read=False,
                )
            )
        db.commit()
        for user in users:
            try:
                send_email_notification(user, title, body)
            except Exception:
                logger.exception("Email notification failed: user=%s", user.email)
        logger.info("Fallback notifications saved: type=%s recipients=%s", event_type, recipient_ids)
    finally:
        db.close()


def save_audit_event(event_type: str, payload: dict) -> None:
    entity_type, entity_id = infer_entity(payload)
    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                id=str(uuid4()),
                actor_id=payload.get("actor_id"),
                action=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )
        )
        db.commit()
        logger.info("Fallback audit saved: type=%s entity=%s:%s", event_type, entity_type, entity_id)
    finally:
        db.close()


def handle_event_without_broker(topic: str, event_type: str, payload: dict) -> None:
    if topic == "ticket-events":
        save_notification_event(event_type, payload)
    elif topic == "audit-events":
        save_audit_event(event_type, payload)

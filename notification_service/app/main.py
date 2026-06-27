import asyncio
import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from uuid import uuid4

from aiokafka import AIOKafkaConsumer
from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, Text, create_engine, func, insert, select


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("notification-service")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
NOTIFICATION_TOPIC = os.getenv("NOTIFICATION_TOPIC", "ticket-events")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./notifications.db")
EMAIL_DELIVERY_ENABLED = os.getenv("EMAIL_DELIVERY_ENABLED", "false").lower() == "true"
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").lower()
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@example.com")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
MAILTRAP_API_TOKEN = os.getenv("MAILTRAP_API_TOKEN")
MAILTRAP_INBOX_ID = os.getenv("MAILTRAP_INBOX_ID")
MAILTRAP_FROM = os.getenv("MAILTRAP_FROM", "HelpDesk <mailtrap@example.com>")
MAILTRAP_API_BASE_URL = os.getenv("MAILTRAP_API_BASE_URL", "https://sandbox.api.mailtrap.io/api/send")
TELEGRAM_NOTIFICATIONS_ENABLED = os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()
users_metadata = MetaData()
notifications = Table(
    "notifications",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("event_type", String(120), nullable=False),
    Column("title", String(255), nullable=False),
    Column("body", Text, nullable=False),
    Column("entity_id", String(36), nullable=True, index=True),
    Column("is_read", Boolean, nullable=False, default=False, index=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)
users = Table(
    "users",
    users_metadata,
    Column("id", String(36), primary_key=True),
    Column("email", String(255), nullable=False),
    Column("full_name", String(255), nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("email_notifications_enabled", Boolean, nullable=False),
    Column("telegram_notifications_enabled", Boolean, nullable=False),
    Column("telegram_chat_id", String(64), nullable=True),
)


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


def mailtrap_address(value: str) -> dict[str, str]:
    if "<" in value and ">" in value:
        name = value.split("<", 1)[0].strip().strip('"')
        email = value.split("<", 1)[1].split(">", 1)[0].strip()
        result = {"email": email}
        if name:
            result["name"] = name
        return result
    return {"email": value.strip()}


def send_email_via_mailtrap(user: dict, title: str, body: str) -> str:
    if not MAILTRAP_API_TOKEN or not MAILTRAP_INBOX_ID:
        return "mailtrap_not_configured"
    payload = json.dumps(
        {
            "from": mailtrap_address(MAILTRAP_FROM),
            "to": [{"email": user["email"], "name": user["full_name"]}],
            "subject": title,
            "text": body,
            "category": "HelpDesk notifications",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{MAILTRAP_API_BASE_URL.rstrip('/')}/{MAILTRAP_INBOX_ID}",
        data=payload,
        headers={
            "Api-Token": MAILTRAP_API_TOKEN,
            "Authorization": f"Bearer {MAILTRAP_API_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "HelpDesk-System/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if 200 <= response.status < 300:
                return "sent"
            return f"mailtrap_http_{response.status}"
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Mailtrap API error {exc.code}: {details}") from exc


def send_email_via_smtp(user: dict, title: str, body: str) -> str:
    if not SMTP_HOST:
        return "smtp_not_configured"

    message = EmailMessage()
    message["Subject"] = title
    message["From"] = SMTP_FROM
    message["To"] = user["email"]
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME and SMTP_PASSWORD:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)
    return "sent"


def send_email_notification(user: dict, title: str, body: str) -> str:
    if not EMAIL_DELIVERY_ENABLED:
        return "disabled_by_settings"
    if not user["email_notifications_enabled"]:
        return "disabled_by_user"
    if EMAIL_PROVIDER == "smtp":
        return send_email_via_smtp(user, title, body)
    if EMAIL_PROVIDER == "mailtrap":
        return send_email_via_mailtrap(user, title, body)
    return "unsupported_email_provider"


def send_telegram_notification(user: dict, title: str, body: str) -> str:
    if not TELEGRAM_NOTIFICATIONS_ENABLED:
        return "disabled_by_settings"
    if not TELEGRAM_BOT_TOKEN:
        return "telegram_not_configured"
    if not user["telegram_notifications_enabled"]:
        return "disabled_by_user"
    if not user["telegram_chat_id"]:
        return "telegram_chat_not_configured"

    payload = json.dumps({"chat_id": user["telegram_chat_id"], "text": f"{title}\n\n{body}"[:4096]}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if 200 <= response.status < 300:
                return "sent"
            return f"telegram_http_{response.status}"
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Telegram API error {exc.code}: {details}") from exc


async def handle_event(event: dict) -> None:
    event_type = event.get("type", "unknown")
    payload = event.get("payload", {})
    recipient_ids = list(dict.fromkeys(payload.get("recipient_ids", [])))
    title, body = notification_text(event_type, payload)

    if recipient_ids:
        with engine.begin() as connection:
            connection.execute(
                insert(notifications),
                [
                    {
                        "id": str(uuid4()),
                        "user_id": user_id,
                        "event_type": event_type,
                        "title": title,
                        "body": body,
                        "entity_id": payload.get("ticket_id"),
                        "is_read": False,
                    }
                    for user_id in recipient_ids
                ],
            )
            recipients = list(
                connection.execute(
                    select(users).where(users.c.id.in_(recipient_ids), users.c.is_active.is_(True))
                ).mappings()
            )
        for user in recipients:
            try:
                status = send_email_notification(user, title, body)
                logger.info("Email notification status: user=%s status=%s", user["email"], status)
            except Exception:
                logger.exception("Email notification failed: user=%s", user["email"])
            try:
                status = send_telegram_notification(user, title, body)
                logger.info("Telegram notification status: user=%s status=%s", user["email"], status)
            except Exception:
                logger.exception("Telegram notification failed: user=%s", user["email"])
    logger.info("Notifications saved: type=%s recipients=%s", event_type, recipient_ids)


async def main() -> None:
    metadata.create_all(engine)
    consumer = AIOKafkaConsumer(
        NOTIFICATION_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="notification-service",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info("Notification service listens topic %s", NOTIFICATION_TOPIC)
    try:
        async for message in consumer:
            await handle_event(json.loads(message.value.decode("utf-8")))
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())

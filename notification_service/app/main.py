import asyncio
import json
import logging
import os
from uuid import uuid4

from aiokafka import AIOKafkaConsumer
from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, Text, create_engine, func, insert


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("notification-service")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
NOTIFICATION_TOPIC = os.getenv("NOTIFICATION_TOPIC", "ticket-events")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./notifications.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()
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

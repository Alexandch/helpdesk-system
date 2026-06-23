import asyncio
import json
import logging
import os

from aiokafka import AIOKafkaConsumer
from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, Uuid, create_engine, func, insert


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit-service")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./audit.db")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
AUDIT_TOPIC = os.getenv("AUDIT_TOPIC", "audit-events")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("actor_id", Uuid(as_uuid=False), nullable=True),
    Column("action", String(120), nullable=False),
    Column("entity_type", String(80), nullable=False),
    Column("entity_id", Uuid(as_uuid=False), nullable=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


def infer_entity(event: dict) -> tuple[str, str | None]:
    payload = event.get("payload", {})
    if "ticket_id" in payload:
        return "ticket", payload["ticket_id"]
    if "message_id" in payload:
        return "message", payload["message_id"]
    return "system", None


def save_audit_event(event: dict) -> None:
    from uuid import uuid4

    payload = event.get("payload", {})
    entity_type, entity_id = infer_entity(event)
    with engine.begin() as connection:
        connection.execute(
            insert(audit_logs).values(
                id=str(uuid4()),
                actor_id=payload.get("actor_id"),
                action=event.get("type", "unknown"),
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )
        )


async def main() -> None:
    metadata.create_all(engine)
    consumer = AIOKafkaConsumer(
        AUDIT_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="audit-service",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info("Audit service listens topic %s", AUDIT_TOPIC)
    try:
        async for message in consumer:
            event = json.loads(message.value.decode("utf-8"))
            save_audit_event(event)
            logger.info("Audit event saved: %s", event.get("type"))
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())

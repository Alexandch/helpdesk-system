import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import settings


logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if not settings.kafka_enabled:
            logger.info("Kafka producer is disabled by settings")
            return
        try:
            self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
            await asyncio.wait_for(self._producer.start(), timeout=3)
            logger.info("Kafka producer started")
        except Exception as exc:
            self._producer = None
            logger.warning("Kafka producer is disabled: %s", exc)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish(self, topic: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "payload": payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not self._producer:
            logger.info("Kafka event skipped: %s", event)
            return
        await self._producer.send_and_wait(topic, json.dumps(event, ensure_ascii=False).encode("utf-8"))

    @property
    def is_connected(self) -> bool:
        return self._producer is not None


publisher = EventPublisher()


async def publish_ticket_event(event_type: str, payload: dict[str, Any]) -> None:
    await publisher.publish("ticket-events", event_type, payload)
    await publisher.publish("audit-events", event_type, payload)

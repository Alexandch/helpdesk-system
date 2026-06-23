import json
import logging
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


logger = logging.getLogger(__name__)
_client: Redis | None = None


def get_redis() -> Redis | None:
    global _client
    if not settings.redis_enabled:
        return None
    if _client is None:
        try:
            _client = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            _client.ping()
        except RedisError as exc:
            logger.warning("Redis is disabled: %s", exc)
            _client = None
    return _client


def cache_get_json(key: str) -> dict[str, Any] | None:
    client = get_redis()
    if not client:
        return None
    value = client.get(key)
    return json.loads(value) if value else None


def cache_set_json(key: str, value: dict[str, Any], ttl_seconds: int = 60) -> None:
    client = get_redis()
    if not client:
        return
    client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))


def cache_delete(key: str) -> None:
    client = get_redis()
    if client:
        client.delete(key)

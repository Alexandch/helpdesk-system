from time import perf_counter

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.system_health import DependencyHealth, SystemHealth
from app.services.cache import get_redis
from app.services.events import publisher


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=SystemHealth)
def system_health(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> SystemHealth:
    db_started = perf_counter()
    try:
        db.execute(text("SELECT 1"))
        database = DependencyHealth(status="operational", latency_ms=round((perf_counter() - db_started) * 1000, 2))
    except Exception:
        database = DependencyHealth(status="unavailable")

    redis_started = perf_counter()
    try:
        redis = get_redis()
        if redis:
            redis.ping()
            redis_health = DependencyHealth(status="operational", latency_ms=round((perf_counter() - redis_started) * 1000, 2))
        else:
            redis_health = DependencyHealth(status="unavailable")
    except Exception:
        redis_health = DependencyHealth(status="unavailable")

    return SystemHealth(
        api=DependencyHealth(status="operational"),
        database=database,
        redis=redis_health,
        kafka=DependencyHealth(status="operational" if publisher.is_connected else "unavailable"),
    )

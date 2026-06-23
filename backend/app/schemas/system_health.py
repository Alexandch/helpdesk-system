from pydantic import BaseModel


class DependencyHealth(BaseModel):
    status: str
    latency_ms: float | None = None


class SystemHealth(BaseModel):
    api: DependencyHealth
    database: DependencyHealth
    redis: DependencyHealth
    kafka: DependencyHealth

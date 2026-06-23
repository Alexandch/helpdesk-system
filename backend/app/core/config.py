from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "HelpDesk System"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./helpdesk.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_enabled: bool = True

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120

    admin_email: str = "admin@example.com"
    admin_password: str = "admin12345"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

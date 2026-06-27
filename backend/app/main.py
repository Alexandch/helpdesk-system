from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from sqlalchemy import inspect, text

from app.db.session import Base, SessionLocal, engine
from app.models.enums import UserRole
from app.models.user import User
from app.services.events import publisher
from app.services.users import create_user, get_user_by_email


def bootstrap_database() -> None:
    Base.metadata.create_all(bind=engine)
    existing_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    boolean_defaults = {
        "email_notifications_enabled": True,
        "telegram_notifications_enabled": False,
    }
    for column_name, default_enabled in boolean_defaults.items():
        if column_name not in existing_columns:
            if engine.dialect.name == "postgresql":
                default_value = "TRUE" if default_enabled else "FALSE"
            else:
                default_value = "1" if default_enabled else "0"
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE users "
                        f"ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT {default_value}"
                    )
                )
    if "telegram_chat_id" not in existing_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN telegram_chat_id VARCHAR(64)"
                )
            )
    if engine.dialect.name == "postgresql":
        for value in ("SUPER_ADMIN", "AGENT"):
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{value}'"))
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET role = 'SUPER_ADMIN' WHERE role::text = 'ADMIN'"))

    db = SessionLocal()
    try:
        if not get_user_by_email(db, settings.admin_email):
            create_user(
                db,
                email=settings.admin_email,
                full_name="Системный администратор",
                password=settings.admin_password,
                role=UserRole.SUPER_ADMIN,
            )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap_database()
    await publisher.start()
    yield
    await publisher.stop()


app = FastAPI(title=settings.project_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}

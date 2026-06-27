from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import UserRole


class UserRead(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    email_notifications_enabled: bool = True
    telegram_notifications_enabled: bool = False
    telegram_chat_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserPreferencesUpdate(BaseModel):
    email_notifications_enabled: bool | None = None
    telegram_notifications_enabled: bool | None = None
    telegram_chat_id: str | None = None

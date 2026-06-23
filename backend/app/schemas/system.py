from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    id: str
    user_id: str
    event_type: str
    title: str
    body: str
    entity_id: str | None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationCount(BaseModel):
    unread: int


class AuditLogRead(BaseModel):
    id: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    payload: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationRead(BaseModel):
    ticket_id: str
    ticket_title: str
    ticket_status: str
    last_message: str | None
    last_message_at: datetime | None
    last_author_name: str | None
    unread_count: int


class ConversationUnreadCount(BaseModel):
    unread: int

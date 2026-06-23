from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TicketPriority, TicketStatus
from app.schemas.user import UserRead


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=5)
    priority: TicketPriority = TicketPriority.MEDIUM


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=5)
    priority: TicketPriority | None = None
    status: TicketStatus | None = None
    assignee_id: str | None = None


class TicketRead(BaseModel):
    id: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    creator_id: str
    assignee_id: str | None
    created_at: datetime
    updated_at: datetime
    creator: UserRead | None = None
    assignee: UserRead | None = None

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class MessageRead(BaseModel):
    id: str
    ticket_id: str
    author_id: str
    body: str
    created_at: datetime
    author: UserRead | None = None

    model_config = ConfigDict(from_attributes=True)


class TicketStats(BaseModel):
    total: int
    open: int
    in_progress: int
    resolved: int
    closed: int


class DailyTicketCount(BaseModel):
    date: str
    count: int


class TicketAnalytics(BaseModel):
    by_status: dict[str, int]
    by_priority: dict[str, int]
    created_last_7_days: list[DailyTicketCount]

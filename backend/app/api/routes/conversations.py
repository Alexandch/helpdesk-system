from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.system import ConversationRead
from app.models.ticket import Message, Ticket
from app.models.user import User
from app.schemas.system import ConversationRead as ConversationReadSchema
from app.schemas.system import ConversationUnreadCount
from app.services.tickets import get_ticket_for_user


router = APIRouter(prefix="/conversations", tags=["conversations"])


def accessible_tickets(db: Session, user: User) -> list[Ticket]:
    if user.role == UserRole.SUPER_ADMIN:
        return []
    stmt = select(Ticket).order_by(Ticket.updated_at.desc())
    if user.role == UserRole.AGENT:
        stmt = stmt.where(Ticket.assignee_id == user.id)
    else:
        stmt = stmt.where(Ticket.creator_id == user.id)
    return list(db.scalars(stmt))


def unread_for_ticket(db: Session, user: User, ticket: Ticket, marker: ConversationRead | None) -> int:
    stmt = select(func.count(Message.id)).where(
        Message.ticket_id == ticket.id,
        Message.author_id != user.id,
    )
    if marker:
        stmt = stmt.where(Message.created_at > marker.last_read_at)
    return db.scalar(stmt) or 0


@router.get("", response_model=list[ConversationReadSchema])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationReadSchema]:
    result: list[ConversationReadSchema] = []
    for ticket in accessible_tickets(db, current_user):
        last_message = db.scalar(
            select(Message)
            .options(joinedload(Message.author))
            .where(Message.ticket_id == ticket.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        marker = db.scalar(
            select(ConversationRead).where(
                ConversationRead.user_id == current_user.id,
                ConversationRead.ticket_id == ticket.id,
            )
        )
        result.append(
            ConversationReadSchema(
                ticket_id=ticket.id,
                ticket_title=ticket.title,
                ticket_status=ticket.status.value,
                last_message=last_message.body if last_message else None,
                last_message_at=last_message.created_at if last_message else None,
                last_author_name=last_message.author.full_name if last_message else None,
                unread_count=unread_for_ticket(db, current_user, ticket, marker),
            )
        )
    return sorted(
        result,
        key=lambda item: item.last_message_at.timestamp() if item.last_message_at else 0,
        reverse=True,
    )


@router.get("/unread-count", response_model=ConversationUnreadCount)
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationUnreadCount:
    total = 0
    for ticket in accessible_tickets(db, current_user):
        marker = db.scalar(
            select(ConversationRead).where(
                ConversationRead.user_id == current_user.id,
                ConversationRead.ticket_id == ticket.id,
            )
        )
        total += unread_for_ticket(db, current_user, ticket, marker)
    return ConversationUnreadCount(unread=total)


@router.post("/{ticket_id}/read")
def mark_conversation_read(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    marker = db.scalar(
        select(ConversationRead).where(
            ConversationRead.user_id == current_user.id,
            ConversationRead.ticket_id == ticket_id,
        )
    )
    now = datetime.now(timezone.utc)
    if marker:
        marker.last_read_at = now
    else:
        marker = ConversationRead(user_id=current_user.id, ticket_id=ticket_id, last_read_at=now)
        db.add(marker)
    db.commit()
    return {"read": True}

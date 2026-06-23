from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.enums import TicketStatus, UserRole
from app.models.ticket import Message, Ticket
from app.models.user import User
from app.schemas.ticket import (
    MessageCreate,
    MessageRead,
    TicketAnalytics,
    TicketCreate,
    TicketRead,
    TicketStats,
    TicketUpdate,
)
from app.services.cache import cache_delete, cache_get_json, cache_set_json
from app.services.events import publish_ticket_event
from app.services.tickets import (
    add_message,
    create_ticket,
    get_ticket_for_user,
    is_valid_status_transition,
    list_tickets,
    ticket_analytics,
    ticket_stats,
    update_ticket,
)


router = APIRouter(prefix="/tickets", tags=["tickets"])


def stats_cache_key(user: User) -> str:
    return f"ticket-stats:{user.role}:{user.id}"


def user_ids_by_role(db: Session, role: UserRole) -> list[str]:
    return list(db.scalars(select(User.id).where(User.role == role, User.is_active.is_(True))))


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket_endpoint(
    payload: TicketCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Ticket:
    if current_user.role != UserRole.USER:
        raise HTTPException(status_code=403, detail="Only users can create tickets")
    ticket = create_ticket(db, payload, current_user)
    cache_delete(stats_cache_key(current_user))
    background_tasks.add_task(
        publish_ticket_event,
        "ticket.created",
        {
            "ticket_id": ticket.id,
            "actor_id": current_user.id,
            "recipient_ids": list({current_user.id, *user_ids_by_role(db, UserRole.SUPER_ADMIN)}),
            "title": ticket.title,
        },
    )
    return ticket


@router.get("", response_model=list[TicketRead])
def list_ticket_endpoint(
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    assignee_id: str | None = None,
    q: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Ticket]:
    return list_tickets(db, current_user, status_filter, assignee_id, q)


@router.get("/stats", response_model=TicketStats)
def get_ticket_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    key = stats_cache_key(current_user)
    cached = cache_get_json(key)
    if cached:
        return cached
    stats = ticket_stats(db, current_user)
    cache_set_json(key, stats, ttl_seconds=30)
    return stats


@router.get("/analytics", response_model=TicketAnalytics)
def get_ticket_analytics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return ticket_analytics(db, current_user)


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Ticket:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.patch("/{ticket_id}", response_model=TicketRead)
def patch_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Ticket:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    values = payload.model_dump(exclude_unset=True)
    content_fields = {"title", "description", "priority"}

    if current_user.role == UserRole.USER and set(values) - content_fields:
        raise HTTPException(status_code=403, detail="Users can only edit ticket content")
    if current_user.role == UserRole.AGENT and set(values) - {"status"}:
        raise HTTPException(status_code=403, detail="Agents can only change ticket status")
    if current_user.role == UserRole.SUPER_ADMIN and set(values) - {"assignee_id"}:
        raise HTTPException(status_code=403, detail="Super admins can only assign agents")

    if "assignee_id" in values and values["assignee_id"] is not None:
        assignee = db.get(User, values["assignee_id"])
        if not assignee:
            raise HTTPException(status_code=404, detail="Assignee not found")
        if assignee.role != UserRole.AGENT or not assignee.is_active:
            raise HTTPException(status_code=422, detail="Assignee must be an active agent")
        if ticket.status == TicketStatus.OPEN:
            values["status"] = TicketStatus.IN_PROGRESS
    if "status" in values and values["status"] is not None:
        target_status = values["status"]
        if not is_valid_status_transition(ticket.status, target_status):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status transition: {ticket.status.value} -> {target_status.value}",
            )
        future_assignee_id = values.get("assignee_id", ticket.assignee_id)
        if target_status == TicketStatus.IN_PROGRESS and not future_assignee_id:
            raise HTTPException(status_code=422, detail="Ticket must have assignee before moving to IN_PROGRESS")
    update_payload = TicketUpdate(**values)
    updated = update_ticket(db, ticket, update_payload)
    cache_delete(stats_cache_key(current_user))
    recipients = {ticket.creator_id}
    if ticket.assignee_id:
        recipients.add(ticket.assignee_id)
    if "status" in values or "assignee_id" in values:
        recipients.update(user_ids_by_role(db, UserRole.SUPER_ADMIN))
    recipients.discard(current_user.id)
    background_tasks.add_task(
        publish_ticket_event,
        "ticket.assigned" if "assignee_id" in values else "ticket.updated",
        {
            "ticket_id": ticket.id,
            "actor_id": current_user.id,
            "recipient_ids": list(recipients),
            "title": ticket.title,
            "changes": values,
        },
    )
    return updated


@router.post("/{ticket_id}/assign/{assignee_id}", response_model=TicketRead)
def assign_ticket(
    ticket_id: str,
    assignee_id: str,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    assignee = db.get(User, assignee_id)
    if not ticket or not assignee:
        raise HTTPException(status_code=404, detail="Ticket or assignee not found")
    if assignee.role != UserRole.AGENT or not assignee.is_active:
        raise HTTPException(status_code=422, detail="Assignee must be an active agent")
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=422, detail="Closed ticket cannot be reassigned")
    ticket.assignee_id = assignee_id
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    background_tasks.add_task(
        publish_ticket_event,
        "ticket.assigned",
        {
            "ticket_id": ticket.id,
            "actor_id": _.id,
            "assignee_id": assignee_id,
            "recipient_ids": list(({ticket.creator_id, assignee_id, *user_ids_by_role(db, UserRole.SUPER_ADMIN)}) - {_.id}),
            "title": ticket.title,
        },
    )
    return ticket


@router.post("/{ticket_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def create_message(
    ticket_id: str,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admins do not participate in customer conversations")
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=422, detail="Closed ticket does not accept new messages")
    message = add_message(db, ticket, current_user, payload.body)
    recipient_ids = []
    if current_user.role == UserRole.USER and ticket.assignee_id:
        recipient_ids = [ticket.assignee_id]
    elif current_user.role == UserRole.AGENT:
        recipient_ids = [ticket.creator_id]
    background_tasks.add_task(
        publish_ticket_event,
        "message.created",
        {
            "ticket_id": ticket.id,
            "message_id": message.id,
            "actor_id": current_user.id,
            "recipient_ids": recipient_ids,
            "title": ticket.title,
            "message_preview": payload.body[:120],
        },
    )
    return message


@router.get("/{ticket_id}/messages", response_model=list[MessageRead])
def list_messages(ticket_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Message]:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admins do not participate in customer conversations")
    return ticket.messages

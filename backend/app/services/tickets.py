from datetime import date, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.enums import TicketStatus, UserRole
from app.models.ticket import Message, Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate


ALLOWED_STATUS_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS},
    TicketStatus.IN_PROGRESS: {TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}


def is_valid_status_transition(current: TicketStatus, target: TicketStatus) -> bool:
    return current == target or target in ALLOWED_STATUS_TRANSITIONS[current]


def user_can_access_ticket(user: User, ticket: Ticket) -> bool:
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if user.role == UserRole.AGENT:
        return ticket.assignee_id == user.id
    return ticket.creator_id == user.id


def base_ticket_query() -> Select[tuple[Ticket]]:
    return select(Ticket).options(joinedload(Ticket.creator), joinedload(Ticket.assignee))


def get_ticket_for_user(db: Session, ticket_id: str, user: User) -> Ticket | None:
    ticket = db.scalar(base_ticket_query().where(Ticket.id == ticket_id))
    if not ticket or not user_can_access_ticket(user, ticket):
        return None
    return ticket


def create_ticket(db: Session, data: TicketCreate, creator: User) -> Ticket:
    ticket = Ticket(**data.model_dump(), creator_id=creator.id)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def list_tickets(
    db: Session,
    user: User,
    status: TicketStatus | None = None,
    assignee_id: str | None = None,
    q: str | None = None,
) -> list[Ticket]:
    stmt = base_ticket_query().order_by(Ticket.created_at.desc())

    if user.role == UserRole.AGENT:
        stmt = stmt.where(Ticket.assignee_id == user.id)
    elif user.role == UserRole.USER:
        stmt = stmt.where(Ticket.creator_id == user.id)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if assignee_id:
        stmt = stmt.where(Ticket.assignee_id == assignee_id)
    if q:
        stmt = stmt.where(Ticket.title.ilike(f"%{q}%"))
    return list(db.scalars(stmt).unique())


def update_ticket(db: Session, ticket: Ticket, data: TicketUpdate) -> Ticket:
    values = data.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(ticket, key, value)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def add_message(db: Session, ticket: Ticket, author: User, body: str) -> Message:
    message = Message(ticket_id=ticket.id, author_id=author.id, body=body)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def ticket_stats(db: Session, user: User) -> dict[str, int]:
    stmt = select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
    if user.role == UserRole.AGENT:
        stmt = stmt.where(Ticket.assignee_id == user.id)
    elif user.role == UserRole.USER:
        stmt = stmt.where(Ticket.creator_id == user.id)
    rows = db.execute(stmt).all()
    counters = {status.value: count for status, count in rows}
    return {
        "total": sum(counters.values()),
        "open": counters.get("OPEN", 0),
        "in_progress": counters.get("IN_PROGRESS", 0),
        "resolved": counters.get("RESOLVED", 0),
        "closed": counters.get("CLOSED", 0),
    }


def ticket_analytics(db: Session, user: User) -> dict:
    tickets = list_tickets(db, user)
    by_status = {status.value: 0 for status in TicketStatus}
    by_priority = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    today = date.today()
    days = {today - timedelta(days=offset): 0 for offset in range(6, -1, -1)}

    for ticket in tickets:
        by_status[ticket.status.value] += 1
        by_priority[ticket.priority.value] += 1
        created_date = ticket.created_at.date()
        if created_date in days:
            days[created_date] += 1

    return {
        "by_status": by_status,
        "by_priority": by_priority,
        "created_last_7_days": [
            {"date": day.isoformat(), "count": count}
            for day, count in days.items()
        ],
    }

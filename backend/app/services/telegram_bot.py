from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.enums import TicketPriority, TicketStatus, UserRole
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services.cache import cache_delete
from app.services.events import publish_ticket_event
from app.services.telegram import telegram_api_request
from app.services.tickets import (
    add_message,
    create_ticket,
    get_ticket_for_user,
    is_valid_status_transition,
    list_tickets,
    update_ticket,
)


STATUS_LABELS = {
    TicketStatus.OPEN: "Открыто",
    TicketStatus.IN_PROGRESS: "В работе",
    TicketStatus.RESOLVED: "Решено",
    TicketStatus.CLOSED: "Закрыто",
}

PRIORITY_LABELS = {
    TicketPriority.LOW: "Низкий",
    TicketPriority.MEDIUM: "Средний",
    TicketPriority.HIGH: "Высокий",
    TicketPriority.CRITICAL: "Критический",
}


def stats_cache_key(user: User) -> str:
    return f"ticket-stats:{user.role}:{user.id}"


def user_ids_by_role(db: Session, role: UserRole) -> list[str]:
    return list(db.scalars(select(User.id).where(User.role == role, User.is_active.is_(True))))


def send_bot_message(chat_id: str, text: str) -> None:
    telegram_api_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        },
    )


def extract_message(update: dict) -> dict | None:
    return update.get("message") or update.get("edited_message")


def extract_command(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return command, args


def find_user_by_chat_id(db: Session, chat_id: str) -> User | None:
    return db.scalar(
        select(User).where(
            User.telegram_chat_id == chat_id,
            User.is_active.is_(True),
        )
    )


def bind_user_by_token(db: Session, token: str, chat_id: str) -> User | None:
    user = db.scalar(select(User).where(User.telegram_link_token == token, User.is_active.is_(True)))
    if not user:
        return None
    user.telegram_chat_id = chat_id
    user.telegram_notifications_enabled = True
    user.telegram_link_token = None
    user.telegram_link_expires_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def short_id(ticket_id: str) -> str:
    return ticket_id[:8]


def find_ticket_by_short_id(db: Session, value: str, user: User) -> Ticket | None:
    value = value.strip()
    if not value:
        return None

    ticket = get_ticket_for_user(db, value, user)
    if ticket:
        return ticket

    stmt = (
        select(Ticket)
        .options(joinedload(Ticket.creator), joinedload(Ticket.assignee))
        .where(Ticket.id.ilike(f"{value}%"))
        .limit(5)
    )
    tickets = [item for item in db.scalars(stmt).unique() if item and item.id.startswith(value)]
    accessible = [item for item in tickets if get_ticket_for_user(db, item.id, user)]
    return accessible[0] if len(accessible) == 1 else None


def format_ticket_line(ticket: Ticket) -> str:
    return (
        f"#{short_id(ticket.id)} — {ticket.title}\n"
        f"Статус: {STATUS_LABELS[ticket.status]}, приоритет: {PRIORITY_LABELS[ticket.priority]}"
    )


def format_ticket_details(ticket: Ticket) -> str:
    assignee = ticket.assignee.full_name if ticket.assignee else "не назначен"
    return (
        f"Обращение #{short_id(ticket.id)}\n"
        f"Тема: {ticket.title}\n"
        f"Статус: {STATUS_LABELS[ticket.status]}\n"
        f"Приоритет: {PRIORITY_LABELS[ticket.priority]}\n"
        f"Исполнитель: {assignee}\n\n"
        f"{ticket.description}\n\n"
        f"Ответить: /reply {short_id(ticket.id)} текст сообщения"
    )


def help_text(user: User | None) -> str:
    common = [
        "Команды HelpDesk:",
        "/help — справка",
        "/tickets — список обращений",
        "/ticket ID — детали обращения",
        "/reply ID текст — отправить сообщение в переписку",
    ]
    if user and user.role == UserRole.USER:
        common.append("/new тема | описание | приоритет — создать обращение")
    if user and user.role == UserRole.AGENT:
        common.append("/status ID RESOLVED — изменить статус обращения")
    common.append("\nID можно брать из команды /tickets, например #a1b2c3d4.")
    return "\n".join(common)


async def handle_start(db: Session, chat_id: str, args: str) -> str:
    if args:
        user = bind_user_by_token(db, args, chat_id)
        if user:
            return (
                f"Telegram подключён к аккаунту {user.email}.\n\n"
                "Теперь можно получать уведомления и работать с обращениями через бота.\n"
                "Напишите /help, чтобы посмотреть команды."
            )
        return "Не удалось привязать Telegram: ссылка устарела или токен не найден. Создайте новую ссылку на сайте."

    user = find_user_by_chat_id(db, chat_id)
    if user:
        return f"Вы уже подключены как {user.full_name}. Напишите /help для списка команд."
    return "Здравствуйте! Чтобы подключить бота, откройте сайт HelpDesk и нажмите «Подключить Telegram»."


def require_linked_user(db: Session, chat_id: str) -> User | None:
    return find_user_by_chat_id(db, chat_id)


async def handle_tickets(db: Session, user: User) -> str:
    tickets = list_tickets(db, user)[:10]
    if not tickets:
        return "Обращений пока нет."

    lines = ["Ваши обращения:"]
    for ticket in tickets:
        lines.append("")
        lines.append(format_ticket_line(ticket))
    lines.append("\nОткрыть детали: /ticket ID")
    return "\n".join(lines)


async def handle_ticket_details(db: Session, user: User, args: str) -> str:
    ticket = find_ticket_by_short_id(db, args, user)
    if not ticket:
        return "Обращение не найдено или нет доступа. Проверьте ID из команды /tickets."
    return format_ticket_details(ticket)


async def handle_new_ticket(db: Session, user: User, args: str) -> str:
    if user.role != UserRole.USER:
        return "Создавать обращения через бота могут только пользователи."

    parts = [part.strip() for part in args.split("|")]
    if len(parts) < 2 or len(parts[0]) < 3 or len(parts[1]) < 5:
        return "Формат: /new тема | описание | приоритет\nПример: /new Не работает вход | После ввода пароля появляется ошибка | HIGH"

    priority = TicketPriority.MEDIUM
    if len(parts) >= 3 and parts[2]:
        try:
            priority = TicketPriority(parts[2].strip().upper())
        except ValueError:
            return "Приоритет должен быть LOW, MEDIUM, HIGH или CRITICAL."

    ticket = create_ticket(db, TicketCreate(title=parts[0], description=parts[1], priority=priority), user)
    cache_delete(stats_cache_key(user))
    await publish_ticket_event(
        "ticket.created",
        {
            "ticket_id": ticket.id,
            "actor_id": user.id,
            "recipient_ids": list({user.id, *user_ids_by_role(db, UserRole.SUPER_ADMIN)}),
            "title": ticket.title,
        },
    )
    return f"Обращение создано: #{short_id(ticket.id)}\n{format_ticket_line(ticket)}"


async def handle_reply(db: Session, user: User, args: str) -> str:
    if user.role == UserRole.SUPER_ADMIN:
        return "Суперадминистратор не участвует в переписке с клиентом."

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return "Формат: /reply ID текст сообщения"

    ticket = find_ticket_by_short_id(db, parts[0], user)
    if not ticket:
        return "Обращение не найдено или нет доступа."
    if ticket.status == TicketStatus.CLOSED:
        return "Закрытое обращение не принимает новые сообщения."

    message = add_message(db, ticket, user, parts[1])
    recipient_ids: list[str] = []
    if user.role == UserRole.USER and ticket.assignee_id:
        recipient_ids = [ticket.assignee_id]
    elif user.role == UserRole.AGENT:
        recipient_ids = [ticket.creator_id]

    await publish_ticket_event(
        "message.created",
        {
            "ticket_id": ticket.id,
            "message_id": message.id,
            "actor_id": user.id,
            "recipient_ids": recipient_ids,
            "title": ticket.title,
            "message_preview": parts[1][:120],
        },
    )
    return f"Сообщение добавлено в обращение #{short_id(ticket.id)}."


async def handle_status(db: Session, user: User, args: str) -> str:
    if user.role != UserRole.AGENT:
        return "Менять статус через бота может только исполнитель."

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return "Формат: /status ID RESOLVED\nДоступные статусы: IN_PROGRESS, RESOLVED, CLOSED."

    ticket = find_ticket_by_short_id(db, parts[0], user)
    if not ticket:
        return "Обращение не найдено или не назначено вам."

    try:
        target_status = TicketStatus(parts[1].strip().upper())
    except ValueError:
        return "Неизвестный статус. Используйте IN_PROGRESS, RESOLVED или CLOSED."

    if not is_valid_status_transition(ticket.status, target_status):
        return f"Недопустимый переход статуса: {ticket.status.value} → {target_status.value}."

    updated = update_ticket(db, ticket, TicketUpdate(status=target_status))
    cache_delete(stats_cache_key(user))
    await publish_ticket_event(
        "ticket.updated",
        {
            "ticket_id": updated.id,
            "actor_id": user.id,
            "recipient_ids": list({updated.creator_id, *user_ids_by_role(db, UserRole.SUPER_ADMIN)} - {user.id}),
            "title": updated.title,
            "changes": {"status": target_status.value},
        },
    )
    return f"Статус обращения #{short_id(updated.id)} изменён на «{STATUS_LABELS[updated.status]}»."


async def handle_telegram_update(db: Session, update: dict) -> None:
    message = extract_message(update)
    if not message:
        return

    chat_id = str((message.get("chat") or {}).get("id") or "")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return

    command, args = extract_command(text)
    if command == "/start":
        response = await handle_start(db, chat_id, args)
        send_bot_message(chat_id, response)
        return

    user = require_linked_user(db, chat_id)
    if not user:
        send_bot_message(chat_id, "Сначала подключите Telegram на сайте HelpDesk через раздел «Уведомления».")
        return

    handlers = {
        "/help": lambda: help_text(user),
        "/tickets": lambda: handle_tickets(db, user),
        "/ticket": lambda: handle_ticket_details(db, user, args),
        "/new": lambda: handle_new_ticket(db, user, args),
        "/reply": lambda: handle_reply(db, user, args),
        "/status": lambda: handle_status(db, user, args),
    }

    handler = handlers.get(command)
    if not handler:
        send_bot_message(chat_id, "Неизвестная команда. Напишите /help.")
        return

    result = handler()
    if hasattr(result, "__await__"):
        result = await result
    send_bot_message(chat_id, result)

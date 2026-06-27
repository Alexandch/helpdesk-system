from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.enums import TicketPriority, TicketStatus, UserRole
from app.models.system import TelegramBotSession
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services.cache import cache_delete
from app.services.events import publish_ticket_event
from app.services.telegram import clear_telegram_chat_from_other_users, telegram_api_request
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


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": text, "callback_data": data} for text, data in row] for row in rows]}


def main_menu_keyboard(user: User) -> dict:
    rows = [[("📋 Мои обращения", "menu:tickets")]]
    if user.role == UserRole.USER:
        rows.append([("➕ Создать обращение", "menu:new")])
    rows.append([("ℹ️ Справка", "menu:help")])
    return keyboard(rows)


def ticket_list_keyboard(tickets: list[Ticket], user: User) -> dict:
    rows = [[(f"#{short_id(ticket.id)} • {ticket.title[:32]}", f"ticket:{ticket.id}")] for ticket in tickets[:10]]
    if user.role == UserRole.USER:
        rows.append([("➕ Создать обращение", "menu:new")])
    rows.append([("🏠 Меню", "menu:home")])
    return keyboard(rows)


def ticket_actions_keyboard(ticket: Ticket, user: User) -> dict:
    rows: list[list[tuple[str, str]]] = []
    if user.role != UserRole.SUPER_ADMIN and ticket.status != TicketStatus.CLOSED:
        rows.append([("💬 Ответить", f"reply:{ticket.id}")])
    if user.role == UserRole.AGENT:
        status_buttons = [
            (f"✅ {STATUS_LABELS[status]}", f"status:{ticket.id}:{status.value}")
            for status in allowed_next_statuses(ticket.status)
        ]
        rows.extend([status_buttons[index : index + 2] for index in range(0, len(status_buttons), 2)])
    rows.append([("⬅️ К списку", "menu:tickets"), ("🏠 Меню", "menu:home")])
    return keyboard(rows)


def priority_keyboard() -> dict:
    return keyboard(
        [
            [("Низкий", "new_priority:LOW"), ("Средний", "new_priority:MEDIUM")],
            [("Высокий", "new_priority:HIGH"), ("Критический", "new_priority:CRITICAL")],
            [("Отмена", "cancel")],
        ]
    )


def cancel_keyboard() -> dict:
    return keyboard([[("Отмена", "cancel")]])


def send_bot_message(chat_id: str, text: str, reply_markup: dict | None = None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    telegram_api_request("sendMessage", payload)


def edit_bot_message(chat_id: str, message_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        telegram_api_request("editMessageText", payload)
    except RuntimeError as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def delete_bot_message(chat_id: str, message_id: int | None) -> None:
    if message_id is None:
        return
    try:
        telegram_api_request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    except RuntimeError:
        pass


def answer_callback(callback_id: str, text: str | None = None) -> None:
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text[:200]
    telegram_api_request("answerCallbackQuery", payload)


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
    clear_telegram_chat_from_other_users(db, chat_id, user)
    user.telegram_chat_id = chat_id
    user.telegram_notifications_enabled = True
    user.telegram_link_token = None
    user.telegram_link_expires_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_session(db: Session, chat_id: str) -> TelegramBotSession | None:
    return db.get(TelegramBotSession, chat_id)


def set_session(db: Session, chat_id: str, user: User, state: str, payload: dict | None = None) -> None:
    session = get_session(db, chat_id) or TelegramBotSession(chat_id=chat_id, user_id=user.id, state=state, payload={})
    session.user_id = user.id
    session.state = state
    session.payload = payload or {}
    db.add(session)
    db.commit()


def clear_session(db: Session, chat_id: str) -> None:
    session = get_session(db, chat_id)
    if session:
        db.delete(session)
        db.commit()


def short_id(ticket_id: str) -> str:
    return ticket_id[:8]


def allowed_next_statuses(status: TicketStatus) -> list[TicketStatus]:
    return {
        TicketStatus.OPEN: [TicketStatus.IN_PROGRESS],
        TicketStatus.IN_PROGRESS: [TicketStatus.RESOLVED],
        TicketStatus.RESOLVED: [TicketStatus.IN_PROGRESS, TicketStatus.CLOSED],
        TicketStatus.CLOSED: [],
    }[status]


def find_ticket_by_short_id(db: Session, value: str, user: User) -> Ticket | None:
    value = value.strip().lstrip("#")
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


def ticket_title_from_description(description: str) -> str:
    first_line = description.strip().splitlines()[0].strip()
    return first_line[:80] if len(first_line) > 3 else "Обращение из Telegram"


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
        f"{ticket.description}"
    )


def help_text(user: User | None) -> str:
    if not user:
        return "Подключите Telegram на сайте HelpDesk, затем используйте кнопки меню."
    return (
        "HelpDesk-бот\n\n"
        "Можно работать кнопками ниже или командами:\n"
        "/tickets — список обращений\n"
        "/ticket ID — детали обращения\n"
        "/reply ID текст — ответить в обращение\n"
        + ("/new — создать обращение\n" if user.role == UserRole.USER else "")
        + ("/status ID RESOLVED — изменить статус\n" if user.role == UserRole.AGENT else "")
    )


def capabilities_text(user: User) -> str:
    lines = [
        "HelpDesk-бот помогает работать с обращениями прямо в Telegram.",
        "",
        "Что можно делать:",
        "• смотреть список обращений;",
        "• открывать детали обращения;",
        "• отвечать в переписку;",
    ]
    if user.role == UserRole.USER:
        lines.append("• создавать новое обращение в пару шагов;")
    if user.role == UserRole.AGENT:
        lines.append("• менять статус назначенных обращений кнопками;")
    lines.extend(["", "Выберите действие в меню ниже."])
    return "\n".join(lines)


def setup_bot_commands() -> dict:
    return telegram_api_request(
        "setMyCommands",
        {
            "commands": [
                {"command": "menu", "description": "Открыть главное меню"},
                {"command": "tickets", "description": "Показать обращения"},
                {"command": "new", "description": "Создать обращение"},
                {"command": "help", "description": "Что умеет бот"},
            ]
        },
    )


async def publish_ticket_created(db: Session, user: User, ticket: Ticket) -> None:
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


async def publish_message_created(user: User, ticket: Ticket, message_id: str, body: str) -> None:
    recipient_ids: list[str] = []
    if user.role == UserRole.USER and ticket.assignee_id:
        recipient_ids = [ticket.assignee_id]
    elif user.role == UserRole.AGENT:
        recipient_ids = [ticket.creator_id]
    await publish_ticket_event(
        "message.created",
        {
            "ticket_id": ticket.id,
            "message_id": message_id,
            "actor_id": user.id,
            "recipient_ids": recipient_ids,
            "title": ticket.title,
            "message_preview": body[:120],
        },
    )


async def handle_start(db: Session, chat_id: str, args: str) -> tuple[str, dict | None]:
    if args:
        user = bind_user_by_token(db, args, chat_id)
        if user:
            clear_session(db, chat_id)
            return (
                f"Telegram подключён к аккаунту {user.email}.\n\n{capabilities_text(user)}",
                main_menu_keyboard(user),
            )
        return "Не удалось привязать Telegram: ссылка устарела или токен не найден.", None

    user = find_user_by_chat_id(db, chat_id)
    if user:
        return f"Вы подключены как {user.full_name}.\n\n{capabilities_text(user)}", main_menu_keyboard(user)
    return "Здравствуйте! Чтобы подключить бота, откройте сайт HelpDesk и нажмите «Подключить Telegram».", None


def require_linked_user(db: Session, chat_id: str) -> User | None:
    return find_user_by_chat_id(db, chat_id)


def tickets_response(db: Session, user: User) -> tuple[str, dict | None]:
    tickets = list_tickets(db, user)[:10]
    if not tickets:
        return "Обращений пока нет.", main_menu_keyboard(user)
    return "Выберите обращение:", ticket_list_keyboard(tickets, user)


def ticket_details_response(db: Session, user: User, args: str) -> tuple[str, dict | None]:
    ticket = find_ticket_by_short_id(db, args, user)
    if not ticket:
        return "Обращение не найдено или нет доступа. Проверьте ID из списка.", main_menu_keyboard(user)
    return format_ticket_details(ticket), ticket_actions_keyboard(ticket, user)


def begin_new_ticket(db: Session, chat_id: str, user: User, message_id: int | None = None) -> tuple[str, dict | None]:
    if user.role != UserRole.USER:
        return "Создавать обращения через бота могут только пользователи.", main_menu_keyboard(user)
    set_session(db, chat_id, user, "awaiting_ticket_text", {"message_id": message_id})
    return "Опишите проблему одним сообщением. Тему отдельно вводить не нужно — я сформирую её из текста.", cancel_keyboard()


async def create_ticket_from_session(db: Session, chat_id: str, user: User, priority: TicketPriority) -> tuple[str, dict | None]:
    session = get_session(db, chat_id)
    description = (session.payload or {}).get("description") if session else None
    if not description:
        clear_session(db, chat_id)
        return "Не нашёл текст обращения. Начните заново.", main_menu_keyboard(user)

    ticket = create_ticket(
        db,
        TicketCreate(title=ticket_title_from_description(description), description=description, priority=priority),
        user,
    )
    clear_session(db, chat_id)
    await publish_ticket_created(db, user, ticket)
    return f"Обращение создано.\n\n{format_ticket_line(ticket)}", ticket_actions_keyboard(ticket, user)


async def reply_from_session(db: Session, chat_id: str, user: User, body: str) -> tuple[str, dict | None]:
    session = get_session(db, chat_id)
    ticket_id = (session.payload or {}).get("ticket_id") if session else None
    ticket = get_ticket_for_user(db, ticket_id, user) if ticket_id else None
    if not ticket:
        clear_session(db, chat_id)
        return "Обращение не найдено или нет доступа.", main_menu_keyboard(user)
    if ticket.status == TicketStatus.CLOSED:
        clear_session(db, chat_id)
        return "Закрытое обращение не принимает новые сообщения.", ticket_actions_keyboard(ticket, user)

    message = add_message(db, ticket, user, body)
    clear_session(db, chat_id)
    await publish_message_created(user, ticket, message.id, body)
    return f"Сообщение добавлено в обращение #{short_id(ticket.id)}.", ticket_actions_keyboard(ticket, user)


async def handle_session_message(db: Session, chat_id: str, user: User, text: str) -> tuple[str, dict | None] | None:
    session = get_session(db, chat_id)
    if not session:
        return None
    if text.startswith("/"):
        clear_session(db, chat_id)
        return "Действие отменено. Выберите пункт меню.", main_menu_keyboard(user)
    if session.state == "awaiting_ticket_text":
        message_id = (session.payload or {}).get("message_id")
        set_session(db, chat_id, user, "awaiting_ticket_priority", {"description": text.strip(), "message_id": message_id})
        return "Выберите приоритет обращения:", priority_keyboard()
    if session.state == "awaiting_reply":
        return await reply_from_session(db, chat_id, user, text.strip())
    clear_session(db, chat_id)
    return "Неизвестное состояние диалога. Начните заново.", main_menu_keyboard(user)


async def handle_new_ticket_command(db: Session, user: User, args: str) -> tuple[str, dict | None]:
    if not args:
        return "Нажмите кнопку «Создать обращение», чтобы пройти создание пошагово.", main_menu_keyboard(user)
    if user.role != UserRole.USER:
        return "Создавать обращения через бота могут только пользователи.", main_menu_keyboard(user)
    priority = TicketPriority.MEDIUM
    if "|" in args:
        parts = [part.strip() for part in args.split("|")]
        title = parts[0] or ticket_title_from_description(args)
        description = parts[1] if len(parts) > 1 and parts[1] else args
        if len(parts) > 2 and parts[2]:
            try:
                priority = TicketPriority(parts[2].upper())
            except ValueError:
                return "Приоритет должен быть LOW, MEDIUM, HIGH или CRITICAL.", main_menu_keyboard(user)
    else:
        title = ticket_title_from_description(args)
        description = args
    ticket = create_ticket(db, TicketCreate(title=title, description=description, priority=priority), user)
    await publish_ticket_created(db, user, ticket)
    return f"Обращение создано.\n\n{format_ticket_line(ticket)}", ticket_actions_keyboard(ticket, user)


async def handle_reply_command(db: Session, user: User, args: str) -> tuple[str, dict | None]:
    if user.role == UserRole.SUPER_ADMIN:
        return "Суперадминистратор не участвует в переписке с клиентом.", main_menu_keyboard(user)
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return "Формат: /reply ID текст сообщения", main_menu_keyboard(user)
    ticket = find_ticket_by_short_id(db, parts[0], user)
    if not ticket:
        return "Обращение не найдено или нет доступа.", main_menu_keyboard(user)
    message = add_message(db, ticket, user, parts[1])
    await publish_message_created(user, ticket, message.id, parts[1])
    return f"Сообщение добавлено в обращение #{short_id(ticket.id)}.", ticket_actions_keyboard(ticket, user)


async def change_status(db: Session, user: User, ticket: Ticket, target_status: TicketStatus) -> tuple[str, dict | None]:
    if user.role != UserRole.AGENT:
        return "Менять статус через бота может только исполнитель.", ticket_actions_keyboard(ticket, user)
    if not is_valid_status_transition(ticket.status, target_status):
        return f"Недопустимый переход статуса: {ticket.status.value} → {target_status.value}.", ticket_actions_keyboard(ticket, user)
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
    return f"Статус изменён на «{STATUS_LABELS[updated.status]}».", ticket_actions_keyboard(updated, user)


async def handle_status_command(db: Session, user: User, args: str) -> tuple[str, dict | None]:
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return "Откройте обращение из списка и выберите новый статус кнопкой.", main_menu_keyboard(user)
    ticket = find_ticket_by_short_id(db, parts[0], user)
    if not ticket:
        return "Обращение не найдено или не назначено вам.", main_menu_keyboard(user)
    try:
        target_status = TicketStatus(parts[1].strip().upper())
    except ValueError:
        return "Неизвестный статус. Используйте кнопки в карточке обращения.", ticket_actions_keyboard(ticket, user)
    return await change_status(db, user, ticket, target_status)


async def handle_callback(db: Session, callback: dict) -> None:
    callback_id = callback.get("id")
    data = callback.get("data") or ""
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    message_id = message.get("message_id")

    def respond(text: str, reply_markup: dict | None = None) -> None:
        if message_id:
            edit_bot_message(chat_id, message_id, text, reply_markup)
        else:
            send_bot_message(chat_id, text, reply_markup)

    if callback_id:
        answer_callback(callback_id)
    if not chat_id:
        return

    user = require_linked_user(db, chat_id)
    if not user:
        respond("Сначала подключите Telegram на сайте HelpDesk.")
        return

    if data == "cancel":
        clear_session(db, chat_id)
        respond("Действие отменено.", main_menu_keyboard(user))
        return
    if data == "menu:home":
        clear_session(db, chat_id)
        respond("Главное меню:", main_menu_keyboard(user))
        return
    if data == "menu:help":
        respond(help_text(user), main_menu_keyboard(user))
        return
    if data == "menu:tickets":
        text, markup = tickets_response(db, user)
        respond(text, markup)
        return
    if data == "menu:new":
        text, markup = begin_new_ticket(db, chat_id, user, message_id)
        respond(text, markup)
        return
    if data.startswith("ticket:"):
        text, markup = ticket_details_response(db, user, data.split(":", 1)[1])
        respond(text, markup)
        return
    if data.startswith("reply:"):
        ticket = find_ticket_by_short_id(db, data.split(":", 1)[1], user)
        if not ticket:
            respond("Обращение не найдено или нет доступа.", main_menu_keyboard(user))
            return
        set_session(db, chat_id, user, "awaiting_reply", {"ticket_id": ticket.id, "message_id": message_id})
        respond(f"Введите сообщение для обращения #{short_id(ticket.id)}:", cancel_keyboard())
        return
    if data.startswith("new_priority:"):
        try:
            priority = TicketPriority(data.split(":", 1)[1])
        except ValueError:
            respond("Неизвестный приоритет.", priority_keyboard())
            return
        text, markup = await create_ticket_from_session(db, chat_id, user, priority)
        respond(text, markup)
        return
    if data.startswith("status:"):
        _, ticket_id, status_value = data.split(":", 2)
        ticket = get_ticket_for_user(db, ticket_id, user)
        if not ticket:
            respond("Обращение не найдено или нет доступа.", main_menu_keyboard(user))
            return
        text, markup = await change_status(db, user, ticket, TicketStatus(status_value))
        respond(text, markup)
        return

    respond("Неизвестное действие.", main_menu_keyboard(user))


async def handle_text_message(db: Session, chat_id: str, text: str, message_id: int | None = None) -> None:
    command, args = extract_command(text)
    if command == "/start":
        response, markup = await handle_start(db, chat_id, args)
        send_bot_message(chat_id, response, markup)
        return

    user = require_linked_user(db, chat_id)
    if not user:
        send_bot_message(chat_id, "Сначала подключите Telegram на сайте HelpDesk через раздел «Уведомления».")
        return

    active_session = get_session(db, chat_id)
    screen_message_id = (active_session.payload or {}).get("message_id") if active_session else None
    session_response = await handle_session_message(db, chat_id, user, text)
    if session_response:
        response, markup = session_response
        if screen_message_id:
            edit_bot_message(chat_id, int(screen_message_id), response, markup)
            delete_bot_message(chat_id, message_id)
        else:
            send_bot_message(chat_id, response, markup)
        return

    handlers = {
        "/help": lambda: (help_text(user), main_menu_keyboard(user)),
        "/menu": lambda: ("Главное меню:", main_menu_keyboard(user)),
        "/tickets": lambda: tickets_response(db, user),
        "/ticket": lambda: ticket_details_response(db, user, args),
        "/new": lambda: handle_new_ticket_command(db, user, args),
        "/reply": lambda: handle_reply_command(db, user, args),
        "/status": lambda: handle_status_command(db, user, args),
    }
    handler = handlers.get(command)
    if not handler:
        send_bot_message(chat_id, "Неизвестная команда. Используйте меню ниже.", main_menu_keyboard(user))
        return

    result = handler()
    if hasattr(result, "__await__"):
        result = await result
    response, markup = result
    send_bot_message(chat_id, response, markup)


async def handle_telegram_update(db: Session, update: dict) -> None:
    callback = update.get("callback_query")
    if callback:
        await handle_callback(db, callback)
        return

    message = extract_message(update)
    if not message:
        return

    chat_id = str((message.get("chat") or {}).get("id") or "")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return
    await handle_text_message(db, chat_id, text, message.get("message_id"))

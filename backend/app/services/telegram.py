import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User


TELEGRAM_LINK_TTL_MINUTES = 15


def telegram_api_request(method: str, payload: dict | None = None) -> dict:
    if not settings.telegram_bot_token:
        raise RuntimeError("Telegram bot token is not configured")

    data = None
    headers = {"User-Agent": "HelpDesk-System/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}",
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Telegram API error {exc.code}: {details}") from exc

    if not body.get("ok"):
        raise RuntimeError(f"Telegram API returned error: {body}")
    return body


def get_bot_username() -> str:
    body = telegram_api_request("getMe")
    username = body.get("result", {}).get("username")
    if not username:
        raise RuntimeError("Telegram bot username was not returned by getMe")
    return username


def ensure_telegram_link(db: Session, user: User) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = user.telegram_link_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if not user.telegram_link_token or not expires_at or expires_at <= now:
        user.telegram_link_token = secrets.token_urlsafe(18)
        user.telegram_link_expires_at = now + timedelta(minutes=TELEGRAM_LINK_TTL_MINUTES)
        db.add(user)
        db.commit()
        db.refresh(user)

    return user.telegram_link_token, user.telegram_link_expires_at


def build_telegram_link(token: str) -> str:
    username = get_bot_username()
    return f"https://t.me/{username}?start={urllib.parse.quote(token)}"


def extract_start_token(update: dict) -> tuple[str | None, str | None]:
    message = update.get("message") or update.get("edited_message") or {}
    text = message.get("text") or ""
    if not text.startswith("/start"):
        return None, None

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None, None

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None, None
    return parts[1].strip(), str(chat_id)


def find_chat_id_by_token(token: str) -> str | None:
    body = telegram_api_request("getUpdates")
    for update in body.get("result", []):
        start_token, chat_id = extract_start_token(update)
        if start_token == token:
            return chat_id
    return None


def bind_telegram_if_started(db: Session, user: User) -> bool:
    if not user.telegram_link_token:
        return False

    expires_at = user.telegram_link_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at <= datetime.now(timezone.utc):
        return False

    chat_id = find_chat_id_by_token(user.telegram_link_token)
    if not chat_id:
        return False

    user.telegram_chat_id = chat_id
    user.telegram_notifications_enabled = True
    user.telegram_link_token = None
    user.telegram_link_expires_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    return True

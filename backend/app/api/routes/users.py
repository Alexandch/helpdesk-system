from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import TelegramLinkRead, TelegramLinkStatus, UserPreferencesUpdate, UserRead, UserUpdate
from app.services.telegram import bind_telegram_if_started, build_telegram_link, ensure_telegram_link


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(_: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())))


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: str, payload: UserUpdate, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    values = payload.model_dump(exclude_unset=True)
    removes_super_admin = user.role == UserRole.SUPER_ADMIN and (
        values.get("role", UserRole.SUPER_ADMIN) != UserRole.SUPER_ADMIN
        or values.get("is_active") is False
    )
    if removes_super_admin:
        active_super_admins = db.scalar(
            select(func.count(User.id)).where(
                User.role == UserRole.SUPER_ADMIN,
                User.is_active.is_(True),
            )
        )
        if active_super_admins <= 1:
            raise HTTPException(status_code=422, detail="At least one active super admin is required")
    if user.id == current_user.id and values.get("is_active") is False:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    for key, value in values.items():
        setattr(user, key, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/me/preferences", response_model=UserRead)
def update_preferences(
    payload: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    values = payload.model_dump(exclude_unset=True)
    if "email_notifications_enabled" in values:
        current_user.email_notifications_enabled = values["email_notifications_enabled"]
    if "telegram_notifications_enabled" in values:
        current_user.telegram_notifications_enabled = values["telegram_notifications_enabled"]
    if "telegram_chat_id" in values:
        chat_id = values["telegram_chat_id"]
        current_user.telegram_chat_id = chat_id.strip() if chat_id and chat_id.strip() else None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/telegram-link", response_model=TelegramLinkRead)
def create_telegram_link(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TelegramLinkRead:
    try:
        token, expires_at = ensure_telegram_link(db, current_user)
        link = build_telegram_link(token)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Telegram link creation failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
    return TelegramLinkRead(
        link=link,
        token=token,
        expires_at=expires_at,
            connected=bool(current_user.telegram_chat_id),
    )


@router.post("/me/telegram-link/check", response_model=TelegramLinkStatus)
def check_telegram_link(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TelegramLinkStatus:
    if current_user.telegram_chat_id:
        return TelegramLinkStatus(
            connected=True,
            telegram_notifications_enabled=current_user.telegram_notifications_enabled,
            telegram_chat_id=current_user.telegram_chat_id,
            status="already_connected",
        )
    try:
        connected = bind_telegram_if_started(db, current_user)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Telegram link check failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
    return TelegramLinkStatus(
        connected=connected,
        telegram_notifications_enabled=current_user.telegram_notifications_enabled,
        telegram_chat_id=current_user.telegram_chat_id,
        status="connected" if connected else "waiting_for_start",
    )

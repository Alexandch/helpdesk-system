from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.telegram_bot import handle_telegram_update, setup_bot_commands


router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    update = await request.json()
    await handle_telegram_update(db, update)
    return {"ok": True}


@router.post("/commands")
def configure_telegram_commands(_: User = Depends(require_super_admin)) -> dict:
    try:
        setup_bot_commands()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Telegram command setup failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
    return {"ok": True}

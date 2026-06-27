from fastapi import APIRouter

from app.api.routes import audit, auth, conversations, notifications, system, telegram, tickets, users


api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(tickets.router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)
api_router.include_router(conversations.router)
api_router.include_router(system.router)
api_router.include_router(telegram.router)

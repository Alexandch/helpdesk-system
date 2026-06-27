import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "admin12345"
os.environ["KAFKA_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"

import httpx
import pytest

from app.core.config import settings
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.enums import UserRole
from app.models.system import AuditLog, Notification
from app.models.user import User
from app.services.users import create_user


@pytest.fixture
def anyio_backend():
    return "asyncio"


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        create_user(
            db,
            email=settings.admin_email,
            full_name="Admin",
            password=settings.admin_password,
            role=UserRole.SUPER_ADMIN,
        )
    finally:
        db.close()


@pytest.fixture
async def client():
    reset_database()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


async def auth_headers(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_test_agent(email: str = "agent@example.com", password: str = "agent12345") -> User:
    db = SessionLocal()
    try:
        return create_user(
            db,
            email=email,
            full_name="Support Agent",
            password=password,
            role=UserRole.AGENT,
        )
    finally:
        db.close()


@pytest.mark.anyio
async def test_user_can_register_login_and_create_ticket(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "full_name": "Test User", "password": "password123"},
    )
    assert response.status_code == 201

    headers = await auth_headers(client, "user@example.com", "password123")
    response = await client.post(
        "/api/v1/tickets",
        headers=headers,
        json={"title": "Broken portal", "description": "Portal returns HTTP 500", "priority": "HIGH"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["priority"] == "HIGH"


@pytest.mark.anyio
async def test_swagger_oauth_form_login_is_supported(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": "admin12345"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


@pytest.mark.anyio
async def test_regular_user_cannot_change_status(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "full_name": "Test User", "password": "password123"},
    )
    headers = await auth_headers(client, "user@example.com", "password123")
    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=headers,
            json={"title": "Printer issue", "description": "Printer does not print", "priority": "MEDIUM"},
        )
    ).json()

    response = await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=headers,
        json={"status": "RESOLVED"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_can_update_ticket_status_and_list_users(client: httpx.AsyncClient) -> None:
    agent = create_test_agent()
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "full_name": "Test User", "password": "password123"},
    )
    user_headers = await auth_headers(client, "user@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    agent_headers = await auth_headers(client, "agent@example.com", "agent12345")

    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=user_headers,
            json={"title": "Network outage", "description": "No internet connection", "priority": "CRITICAL"},
        )
    ).json()

    response = await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assignee_id": agent.id},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"

    response = await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=agent_headers,
        json={"status": "RESOLVED"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"

    users = await client.get("/api/v1/users", headers=admin_headers)
    assert users.status_code == 200
    assert len(users.json()) >= 2


@pytest.mark.anyio
async def test_invalid_status_transition_is_rejected(client: httpx.AsyncClient) -> None:
    agent = create_test_agent()
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "full_name": "Test User", "password": "password123"},
    )
    user_headers = await auth_headers(client, "user@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    agent_headers = await auth_headers(client, "agent@example.com", "agent12345")
    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=user_headers,
            json={"title": "Billing issue", "description": "Invoice has wrong amount", "priority": "MEDIUM"},
        )
    ).json()
    await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assignee_id": agent.id},
    )

    response = await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=agent_headers,
        json={"status": "CLOSED"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_user_cannot_access_foreign_ticket(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "full_name": "Owner", "password": "password123"},
    )
    await client.post(
        "/api/v1/auth/register",
        json={"email": "stranger@example.com", "full_name": "Stranger", "password": "password123"},
    )
    owner_headers = await auth_headers(client, "owner@example.com", "password123")
    stranger_headers = await auth_headers(client, "stranger@example.com", "password123")
    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=owner_headers,
            json={"title": "Private issue", "description": "Only owner should see this ticket", "priority": "LOW"},
        )
    ).json()

    response = await client.get(f"/api/v1/tickets/{ticket['id']}", headers=stranger_headers)
    assert response.status_code == 404


@pytest.mark.anyio
async def test_regular_user_cannot_be_assigned_as_executor(client: httpx.AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    client_id = register.json()["id"]
    user_headers = await auth_headers(client, "client@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=user_headers,
            json={"title": "Access problem", "description": "Cannot open personal account", "priority": "HIGH"},
        )
    ).json()

    response = await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assignee_id": client_id},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_user_can_read_notifications_and_admin_can_read_audit(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "full_name": "Test User", "password": "password123"},
    )
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "user@example.com").one()
        db.add(
            Notification(
                user_id=user.id,
                event_type="ticket.updated",
                title="Статус изменён",
                body="Тестовое уведомление",
                entity_id=None,
            )
        )
        db.add(
            AuditLog(
                id="db8ea541-2aa1-4118-9925-b72b852dc747",
                actor_id=user.id,
                action="ticket.updated",
                entity_type="ticket",
                entity_id=None,
                payload={"status": "RESOLVED"},
            )
        )
        db.commit()
    finally:
        db.close()

    user_headers = await auth_headers(client, "user@example.com", "password123")
    notifications = await client.get("/api/v1/notifications", headers=user_headers)
    assert notifications.status_code == 200
    assert notifications.json()[0]["is_read"] is False

    count = await client.get("/api/v1/notifications/unread-count", headers=user_headers)
    assert count.json()["unread"] == 1

    forbidden_audit = await client.get("/api/v1/audit-logs", headers=user_headers)
    assert forbidden_audit.status_code == 403

    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    audit = await client.get("/api/v1/audit-logs", headers=admin_headers)
    assert audit.status_code == 200
    assert audit.json()[0]["action"] == "ticket.updated"


@pytest.mark.anyio
async def test_kafka_disabled_fallback_creates_notifications_and_audit(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    client_headers = await auth_headers(client, "client@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")

    response = await client.post(
        "/api/v1/tickets",
        headers=client_headers,
        json={"title": "Production notification", "description": "Fallback notification check", "priority": "MEDIUM"},
    )
    assert response.status_code == 201

    notifications = await client.get("/api/v1/notifications", headers=client_headers)
    assert notifications.status_code == 200
    assert any(item["event_type"] == "ticket.created" for item in notifications.json())

    audit = await client.get("/api/v1/audit-logs", headers=admin_headers)
    assert audit.status_code == 200
    assert any(item["action"] == "ticket.created" for item in audit.json())


@pytest.mark.anyio
async def test_user_can_update_email_notification_preference(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    headers = await auth_headers(client, "client@example.com", "password123")

    response = await client.patch(
        "/api/v1/users/me/preferences",
        headers=headers,
        json={"email_notifications_enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["email_notifications_enabled"] is False

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["email_notifications_enabled"] is False


@pytest.mark.anyio
async def test_user_can_update_telegram_notification_preferences(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    headers = await auth_headers(client, "client@example.com", "password123")

    response = await client.patch(
        "/api/v1/users/me/preferences",
        headers=headers,
        json={"telegram_notifications_enabled": True, "telegram_chat_id": "123456789"},
    )
    assert response.status_code == 200
    assert response.json()["telegram_notifications_enabled"] is True
    assert response.json()["telegram_chat_id"] == "123456789"

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["telegram_notifications_enabled"] is True
    assert me.json()["telegram_chat_id"] == "123456789"


@pytest.mark.anyio
async def test_user_can_request_test_email_status(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    headers = await auth_headers(client, "client@example.com", "password123")

    response = await client.post("/api/v1/notifications/test-email", headers=headers)
    assert response.status_code == 200
    assert response.json()["email_status"] == "disabled_by_settings"


@pytest.mark.anyio
async def test_user_can_request_test_telegram_status(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    headers = await auth_headers(client, "client@example.com", "password123")

    response = await client.post("/api/v1/notifications/test-telegram", headers=headers)
    assert response.status_code == 200
    assert response.json()["telegram_status"] == "disabled_by_settings"


@pytest.mark.anyio
async def test_conversation_unread_counter_is_cleared_after_read(client: httpx.AsyncClient) -> None:
    agent = create_test_agent()
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    client_headers = await auth_headers(client, "client@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    agent_headers = await auth_headers(client, "agent@example.com", "agent12345")

    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=client_headers,
            json={"title": "Email problem", "description": "Recovery email is missing", "priority": "MEDIUM"},
        )
    ).json()
    await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assignee_id": agent.id},
    )
    await client.post(
        f"/api/v1/tickets/{ticket['id']}/messages",
        headers=agent_headers,
        json={"body": "Проверьте папку Спам и подтвердите адрес электронной почты."},
    )

    before = await client.get("/api/v1/conversations/unread-count", headers=client_headers)
    assert before.json()["unread"] == 1

    mark_read = await client.post(f"/api/v1/conversations/{ticket['id']}/read", headers=client_headers)
    assert mark_read.status_code == 200

    after = await client.get("/api/v1/conversations/unread-count", headers=client_headers)
    assert after.json()["unread"] == 0


@pytest.mark.anyio
async def test_closed_ticket_does_not_accept_messages(client: httpx.AsyncClient) -> None:
    agent = create_test_agent()
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    client_headers = await auth_headers(client, "client@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    agent_headers = await auth_headers(client, "agent@example.com", "agent12345")

    ticket = (
        await client.post(
            "/api/v1/tickets",
            headers=client_headers,
            json={"title": "Closed case", "description": "Ticket will be closed", "priority": "LOW"},
        )
    ).json()
    await client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assignee_id": agent.id},
    )
    await client.patch(f"/api/v1/tickets/{ticket['id']}", headers=agent_headers, json={"status": "RESOLVED"})
    await client.patch(f"/api/v1/tickets/{ticket['id']}", headers=agent_headers, json={"status": "CLOSED"})

    response = await client.post(
        f"/api/v1/tickets/{ticket['id']}/messages",
        headers=client_headers,
        json={"body": "I still want to add a message."},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_admin_can_read_analytics_and_system_health(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "client@example.com", "full_name": "Client", "password": "password123"},
    )
    client_headers = await auth_headers(client, "client@example.com", "password123")
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    await client.post(
        "/api/v1/tickets",
        headers=client_headers,
        json={"title": "Analytics ticket", "description": "Ticket for dashboard analytics", "priority": "HIGH"},
    )

    analytics = await client.get("/api/v1/tickets/analytics", headers=admin_headers)
    assert analytics.status_code == 200
    assert analytics.json()["by_status"]["OPEN"] == 1
    assert analytics.json()["by_priority"]["HIGH"] == 1
    assert len(analytics.json()["created_last_7_days"]) == 7

    health = await client.get("/api/v1/system/health", headers=admin_headers)
    assert health.status_code == 200
    assert health.json()["api"]["status"] == "operational"
    assert health.json()["database"]["status"] == "operational"

    forbidden = await client.get("/api/v1/system/health", headers=client_headers)
    assert forbidden.status_code == 403


@pytest.mark.anyio
async def test_admin_cannot_create_ticket(client: httpx.AsyncClient) -> None:
    admin_headers = await auth_headers(client, "admin@example.com", "admin12345")
    response = await client.post(
        "/api/v1/tickets",
        headers=admin_headers,
        json={"title": "Admin ticket", "description": "Admin must not create tickets", "priority": "LOW"},
    )
    assert response.status_code == 403

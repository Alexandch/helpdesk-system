# Примеры API-запросов

## Вход

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "admin@example.com",
  "password": "admin12345"
}
```

## Создание обращения

```http
POST /api/v1/tickets
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "Не работает личный кабинет",
  "description": "После входа появляется ошибка 500",
  "priority": "HIGH"
}
```

## Фильтрация обращений

```http
GET /api/v1/tickets?status=OPEN&q=кабинет
Authorization: Bearer <token>
```

## Назначение исполнителя

```http
POST /api/v1/tickets/{ticket_id}/assign/{assignee_id}
Authorization: Bearer <admin-token>
```

## Изменение статуса

```http
PATCH /api/v1/tickets/{ticket_id}
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "status": "RESOLVED"
}
```


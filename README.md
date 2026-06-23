# HelpDesk System

Учебно-практическая система обработки обращений клиентов на FastAPI, React, PostgreSQL, Redis и Apache Kafka.

## Состав проекта

- `backend/` — основной REST API;
- `notification_service/` — обработка Kafka-событий и создание уведомлений;
- `audit_service/` — централизованное журналирование действий;
- `frontend/` — пользовательский интерфейс React;
- `docs/` — техническое задание, архитектура, ER-модель и отчёт;
- `k8s/` — примеры Kubernetes-манифестов.

## Запуск

```bash
docker compose up -d --build
```

Адреса сервисов:

- Frontend: http://localhost:3000
- Swagger API: http://localhost:8000/docs
- Kafka UI: http://localhost:8080
- RedisInsight: http://localhost:5540
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Kafka: `localhost:9092`

Тестовый администратор:

- email: `admin@example.com`
- password: `admin12345`

## Основные возможности

- регистрация, вход и JWT-аутентификация;
- роли `SUPER_ADMIN`, `AGENT` и `USER`;
- создание, назначение, фильтрация и изменение статусов обращений;
- строгий жизненный цикл `OPEN → IN_PROGRESS → RESOLVED → CLOSED`;
- карточка обращения и переписка;
- персональные уведомления с отметкой прочтения;
- административный журнал аудита;
- интерфейс на русском и английском языках с сохранением выбора;
- адаптивная навигация, состояния загрузки и анимации переходов;
- административный обзор с графиками, последней активностью и состоянием инфраструктуры;
- публикация и обработка событий через Kafka;
- Redis-кэширование статистики;
- Docker Compose и пример Kubernetes-конфигурации.

## Проверка уведомлений и аудита

1. Откройте обращение кликом по карточке и отправьте сообщение.
2. Измените статус или назначьте исполнителя.
3. Notification Service обработает событие через Kafka.
4. В разделе «Уведомления» появится новая запись и счётчик.
5. Под администратором откройте «Журнал аудита».

Интерфейс автоматически обновляет данные каждые 15 секунд.

## Kafka и Redis

Kafka UI показывает топики `ticket-events`, `audit-events`, сообщения и consumer groups.

При первом подключении RedisInsight используйте:

- host: `redis`;
- port: `6379`;
- username/password: не заполнять.

Команды для терминала:

```bash
docker compose logs -f notification-service audit-service
docker compose exec kafka kafka-topics --bootstrap-server kafka:29092 --list
docker compose exec redis redis-cli --scan
docker compose exec redis redis-cli MONITOR
```

## Тесты

```bash
cd backend
pytest
```

Сценарий демонстрации описан в `docs/demo_scenario.md`.

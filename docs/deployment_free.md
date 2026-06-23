# Бесплатная публикация проекта

Документ описывает практичный вариант публикации HelpDesk System для демонстрации.

Полная инфраструктура проекта включает PostgreSQL, Redis, Apache Kafka, отдельные сервисы уведомлений и аудита. Для бесплатного публичного стенда Kafka обычно является самым сложным компонентом, поэтому рекомендуется разделить окружения:

- локально и в Kubernetes — полный вариант с Kafka, Kafka UI, RedisInsight и worker-сервисами;
- публичный demo-стенд — frontend + FastAPI + PostgreSQL + Redis, а Kafka отключается переменной `KAFKA_ENABLED=false`.

Такой подход сохраняет архитектуру проекта и при этом позволяет бесплатно показать работающий веб-интерфейс.

## 1. Подготовка репозитория

```bash
git init
git add .
git commit -m "Initial HelpDesk System release"
git branch -M main
```

После создания пустых репозиториев на GitHub и GitLab:

```bash
git remote add origin https://github.com/<username>/<repo>.git
git remote add gitlab https://gitlab.com/<username>/<repo>.git

git push -u origin main
git push -u gitlab main
```

## 2. Backend

Backend можно опубликовать как Docker Web Service.

Настройки сервиса:

- root/context directory: `backend`;
- Dockerfile: `backend/Dockerfile`;
- port: `8000`;
- health check path: `/health`.

Переменные окружения:

```env
DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/<database>
REDIS_URL=redis://<user>:<password>@<host>:6379/0
REDIS_ENABLED=true
KAFKA_ENABLED=false
JWT_SECRET_KEY=<long-random-secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<strong-password>
```

Если Redis на выбранном хостинге не используется, можно указать:

```env
REDIS_ENABLED=false
```

## 3. PostgreSQL

Для бесплатной демонстрации удобно использовать внешний PostgreSQL-сервис.

Важно: если провайдер выдаёт строку вида:

```text
postgresql://user:password@host:5432/database
```

для приложения её нужно записать так:

```text
postgresql+psycopg2://user:password@host:5432/database
```

Таблицы создаются автоматически при запуске backend-приложения.

## 4. Redis

Redis в публичном demo-стенде используется для кэширования статистики. Если бесплатный Redis недоступен, проект продолжит работать без него при `REDIS_ENABLED=false`.

## 5. Frontend

Frontend можно опубликовать как статический сайт.

Настройки:

- root directory: `frontend`;
- build command: `npm install && npm run build`;
- output directory: `dist`.

Переменная окружения:

```env
VITE_API_URL=https://<backend-domain>/api/v1
```

После изменения `VITE_API_URL` frontend нужно пересобрать.

## 6. Что показать на защите

Для демонстрации стоит показать два режима:

1. Локальный/Kubernetes-режим:
   - PostgreSQL;
   - Redis;
   - Apache Kafka;
   - Notification Service;
   - Audit Service;
   - Kafka UI;
   - RedisInsight.

2. Публичный demo-режим:
   - авторизация;
   - роли `SUPER_ADMIN`, `AGENT`, `USER`;
   - создание обращений пользователями;
   - назначение исполнителей супер-админом;
   - переписка пользователя и исполнителя;
   - статистика;
   - адаптивный React-интерфейс.

## 7. Важное замечание по безопасности

Файлы `.env` и реальные production-секреты нельзя хранить в Git. В репозиторий добавлен только `.env.example` с учебными значениями.

Для публичного стенда обязательно заменить:

- `JWT_SECRET_KEY`;
- `ADMIN_PASSWORD`;
- пароль PostgreSQL;
- пароль Redis.

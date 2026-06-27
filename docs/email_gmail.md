# Email-уведомления через Gmail без собственного домена

Этот вариант нужен для публичного стенда, когда письма должны реально приходить пользователям на Gmail/другую почту, но собственного домена нет.

В проект добавлен провайдер:

```env
EMAIL_DELIVERY_ENABLED=true
EMAIL_PROVIDER=gmail_api
GMAIL_CLIENT_ID=<google-oauth-client-id>
GMAIL_CLIENT_SECRET=<google-oauth-client-secret>
GMAIL_REFRESH_TOKEN=<google-oauth-refresh-token>
GMAIL_FROM=HelpDesk <your-gmail@gmail.com>
```

Почему именно `gmail_api`, а не SMTP:

- Gmail API работает по HTTPS и лучше подходит для Render/других бесплатных хостингов.
- SMTP-порты на хостингах могут быть заблокированы, из-за чего появляются ошибки вида `Network is unreachable`.
- Собственный домен не нужен: отправителем будет ваш Gmail-аккаунт, например `HelpDesk <your-gmail@gmail.com>`.

## Как получить данные Google

1. Откройте Google Cloud Console.
2. Создайте проект или выберите существующий.
3. Включите Gmail API.
4. Настройте OAuth consent screen.
   - Для учебного проекта можно оставить приложение в режиме Testing.
   - Добавьте свой Gmail в Test users.
5. Создайте OAuth Client ID.
   - Удобнее выбрать тип `Desktop app` или `Web application`.
6. Получите refresh token со scope:

```text
https://www.googleapis.com/auth/gmail.send
```

Самый простой способ для учебной демонстрации — OAuth 2.0 Playground:

1. Откройте OAuth 2.0 Playground.
2. В настройках включите `Use your own OAuth credentials`.
3. Вставьте `GMAIL_CLIENT_ID` и `GMAIL_CLIENT_SECRET`.
4. В поле scopes укажите `https://www.googleapis.com/auth/gmail.send`.
5. Авторизуйтесь под Gmail, с которого должны уходить письма.
6. Нажмите `Exchange authorization code for tokens`.
7. Скопируйте `refresh_token`.

Секреты не добавляйте в Git. Их нужно хранить только в переменных окружения Render/локального `.env`.

## Настройка на Render

В Render → backend service → Environment добавьте:

```env
EMAIL_DELIVERY_ENABLED=true
EMAIL_PROVIDER=gmail_api
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
GMAIL_FROM=HelpDesk <your-gmail@gmail.com>
```

После сохранения переменных перезапустите backend.

Проверка:

1. Откройте Swagger backend.
2. Авторизуйтесь.
3. Вызовите `POST /api/v1/notifications/test-email`.
4. Успешный ответ:

```json
{
  "notification_id": "...",
  "email_status": "sent"
}
```

После этого реальные события HelpDesk тоже будут отправлять письма тем пользователям, у которых включены email-уведомления.

## Альтернатива: Gmail SMTP

Если нужен именно SMTP, можно использовать пароль приложения Google:

```env
EMAIL_DELIVERY_ENABLED=true
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-gmail@gmail.com
SMTP_PASSWORD=<16-character-app-password>
SMTP_FROM=HelpDesk <your-gmail@gmail.com>
SMTP_USE_TLS=true
```

Но для Render этот вариант менее надёжный: даже при правильном пароле SMTP-соединение может не открываться из-за сетевых ограничений.

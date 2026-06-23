# Локальное развёртывание в Kubernetes

Манифесты создают отдельный namespace `helpdesk` и полный учебный стенд:

- React + Nginx;
- FastAPI;
- Notification Service и Audit Service;
- PostgreSQL с постоянным хранилищем;
- Redis с постоянным хранилищем;
- Kafka и ZooKeeper;
- Kafka UI и RedisInsight.

## 1. Подготовка Docker Desktop

В Docker Desktop откройте `Settings → Kubernetes`, включите
`Enable Kubernetes` и дождитесь статуса `Kubernetes is running`.

Проверьте подключение:

```powershell
kubectl config current-context
kubectl get nodes
```

Для Docker Desktop ожидаемый контекст — `docker-desktop`.

## 2. Сборка локальных образов

Выполняйте команды из корня проекта:

```powershell
docker build -t helpdesk-backend:local .\backend
docker build -t helpdesk-notification-service:local .\notification_service
docker build -t helpdesk-audit-service:local .\audit_service
docker build -t helpdesk-frontend:local .\frontend
```

Docker Desktop Kubernetes использует локальные Docker-образы. Публиковать их
в Docker Hub для локальной проверки не требуется.

## 3. Запуск

Чтобы порты Docker Compose не конфликтовали с Kubernetes, сначала остановите
Compose-стенд:

```powershell
docker compose down
kubectl apply -k .\k8s
kubectl get pods -n helpdesk -w
```

Первый запуск Kafka и загрузка образов могут занять несколько минут.
Дождитесь состояния `Running` и готовности `1/1`.

## 4. Доступ к сервисам

На некоторых версиях Docker Desktop NodePort недоступен напрямую из Windows.
Надёжный способ — запустить подготовленный скрипт:

```powershell
powershell -ExecutionPolicy Bypass -File .\k8s\start-port-forwards.ps1
```

Или выполнить `kubectl port-forward` для каждого сервиса в отдельном окне
терминала.

- приложение: http://localhost:30080
- Kafka UI: http://localhost:30081
- RedisInsight: http://localhost:30540

Для RedisInsight используйте:

- host: `redis`
- port: `6379`
- username/password: пустые.

Swagger можно открыть временным пробросом порта:

```powershell
kubectl port-forward -n helpdesk service/helpdesk-api 8000:8000
```

После этого Swagger доступен по адресу http://localhost:8000/docs.

## 5. Проверка и логи

```powershell
kubectl get all -n helpdesk
kubectl get pvc -n helpdesk
kubectl logs -n helpdesk deployment/helpdesk-api -f
kubectl logs -n helpdesk deployment/notification-service -f
kubectl logs -n helpdesk deployment/audit-service -f
kubectl logs -n helpdesk statefulset/kafka -f
kubectl describe pod -n helpdesk <pod-name>
```

Проверка Kafka:

```powershell
kubectl exec -n helpdesk kafka-0 -- kafka-topics --bootstrap-server kafka:9092 --list
```

Проверка Redis:

```powershell
kubectl exec -n helpdesk deployment/redis -- redis-cli ping
kubectl exec -n helpdesk deployment/redis -- redis-cli --scan
```

## 6. Обновление приложения

После изменения исходного кода пересоберите нужный образ и перезапустите
Deployment:

```powershell
docker build -t helpdesk-backend:local .\backend
kubectl rollout restart deployment/helpdesk-api -n helpdesk
kubectl rollout status deployment/helpdesk-api -n helpdesk
```

Аналогично обновляются `helpdesk-frontend`, `notification-service` и
`audit-service`.

## 7. Остановка

Удалить Kubernetes-ресурсы приложения:

```powershell
kubectl delete -k .\k8s
```

PVC удаляются вместе с манифестами, поэтому данные PostgreSQL, Kafka и Redis
при полном удалении стенда будут потеряны.

## Важно

Секреты в `01-configuration.yaml` являются только демонстрационными. Перед
публикацией необходимо заменить пароли и JWT-ключ, а реальные секреты хранить
в менеджере секретов или создавать отдельной командой `kubectl create secret`.

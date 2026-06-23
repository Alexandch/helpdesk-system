$ErrorActionPreference = "Stop"

$forwards = @(
    @{ Name = "HelpDesk"; Arguments = @("port-forward", "-n", "helpdesk", "service/helpdesk-frontend", "30080:80") },
    @{ Name = "Kafka UI"; Arguments = @("port-forward", "-n", "helpdesk", "service/kafka-ui", "30081:8080") },
    @{ Name = "RedisInsight"; Arguments = @("port-forward", "-n", "helpdesk", "service/redis-insight", "30540:5540") }
)

foreach ($forward in $forwards) {
    Start-Process -FilePath "kubectl" -ArgumentList $forward.Arguments -WindowStyle Hidden
    Write-Host "$($forward.Name): port-forward запущен"
}

Write-Host ""
Write-Host "HelpDesk:     http://localhost:30080"
Write-Host "Kafka UI:     http://localhost:30081"
Write-Host "RedisInsight: http://localhost:30540"
Write-Host ""
Write-Host "Чтобы остановить пробросы, завершите процессы kubectl в диспетчере задач."

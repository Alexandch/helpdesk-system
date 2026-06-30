$ErrorActionPreference = "Stop"

$namespace = "helpdesk"

$forwards = @(
    @{ Name = "HelpDesk frontend"; Arguments = @("port-forward", "-n", $namespace, "service/helpdesk-frontend", "30080:80"); Url = "http://localhost:30080" },
    @{ Name = "Backend API"; Arguments = @("port-forward", "-n", $namespace, "service/helpdesk-api", "30082:8000"); Url = "http://localhost:30082/docs" },
    @{ Name = "Kafka UI"; Arguments = @("port-forward", "-n", $namespace, "service/kafka-ui", "30081:8080"); Url = "http://localhost:30081" },
    @{ Name = "RedisInsight"; Arguments = @("port-forward", "-n", $namespace, "service/redis-insight", "30540:5540"); Url = "http://localhost:30540" }
)

foreach ($forward in $forwards) {
    Start-Process -FilePath "kubectl" -ArgumentList $forward.Arguments -WindowStyle Hidden
    Write-Host "$($forward.Name): port-forward started"
}

Write-Host ""
Write-Host "Kubernetes local URLs:"
foreach ($forward in $forwards) {
    Write-Host "$($forward.Name): $($forward.Url)"
}
Write-Host ""
Write-Host "To stop port-forwards, run:"
Write-Host "Get-Process kubectl | Stop-Process"

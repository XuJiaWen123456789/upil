param(
    [string]$ComposeFile = (Join-Path $PSScriptRoot '..\infra\docker-compose.yml')
)

$ErrorActionPreference = 'Stop'
$composeArgs = @('--file', $ComposeFile)

function Assert-Command([string]$Name) {
    # 先确认命令存在，避免后续错误被误判为服务未启动。
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到命令：$Name，请确认 Docker Desktop 和 PATH 已配置。"
    }
}

function Assert-Http([string]$Url, [string]$Label) {
    # HTTP 检查只验证本机服务可达，不读取或输出任何凭据。
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            throw "HTTP 状态码 $($response.StatusCode)"
        }
        Write-Host "[OK] $Label -> $($response.StatusCode)" -ForegroundColor Green
    } catch {
        throw "$Label 不可访问：$Url；$($_.Exception.Message)"
    }
}

Assert-Command 'docker'

# Docker Compose config 会先解析 YAML 和环境变量，避免启动时才发现编排错误。
docker compose @composeArgs config --quiet
Write-Host '[OK] Docker Compose 配置有效' -ForegroundColor Green

$psOutput = docker compose @composeArgs ps --format json | ConvertFrom-Json
if (-not $psOutput) {
    throw '没有发现正在运行的基础设施容器，请先执行 docker compose up -d。'
}

$expected = @('upil-postgres', 'upil-minio')
foreach ($name in $expected) {
    $container = @($psOutput | Where-Object { $_.Name -eq $name }) | Select-Object -First 1
    if (-not $container) {
        throw "容器未运行：$name"
    }
    Write-Host "[OK] 容器 $name -> $($container.State)" -ForegroundColor Green
}

# PostgreSQL 使用 TCP 端口检查，避免把数据库密码写到脚本或终端输出。
$tcp = Test-NetConnection -ComputerName '127.0.0.1' -Port 5432 -WarningAction SilentlyContinue
if (-not $tcp.TcpTestSucceeded) { throw 'PostgreSQL 5432 端口不可访问。' }
Write-Host '[OK] PostgreSQL 5432 端口可访问' -ForegroundColor Green

Assert-Http 'http://127.0.0.1:19000/minio/health/live' 'MinIO API'
Assert-Http 'http://127.0.0.1:19001' 'MinIO Console'
Write-Host '基础设施检查通过。' -ForegroundColor Green

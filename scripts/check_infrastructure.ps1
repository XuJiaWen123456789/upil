param(
    [string]$ComposeFile = (Join-Path $PSScriptRoot '..\infra\docker-compose.yml'),
    [string]$EnvFile = (Join-Path $PSScriptRoot '..\.env')
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "未找到本地环境文件：$EnvFile。请从 .env.example 复制并填写本地配置。"
}
$composeArgs = @('--env-file', $EnvFile, '--file', $ComposeFile)

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

function Assert-OllamaEmbedding {
    # RAGFlow 首页可访问并不代表检索可用：查询阶段还依赖宿主机 Ollama
    # 和 bge-m3。这里只读取模型目录，不执行向量化，也不输出本机模型路径。
    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11528/api/tags' -TimeoutSec 10
    $models = @($tags.models | ForEach-Object { $_.name })
    if ($models -notcontains 'bge-m3:latest') {
        throw 'Ollama 未安装 RAGFlow 所需的 bge-m3:latest 模型。'
    }
    Write-Host '[OK] Ollama Embedding -> bge-m3:latest 已就绪' -ForegroundColor Green

    # RAGFlow 位于容器内，必须从容器网络访问 host.docker.internal；仅验证
    # Windows 本机端口会漏掉防火墙、Docker DNS 或监听地址错误。
    $ragflowContainer = docker ps --filter 'name=upil-ragflow-ragflow-cpu-1' --format '{{.Names}}'
    if (-not $ragflowContainer) {
        throw 'RAGFlow 容器未运行，无法验证到 Ollama 的容器网络链路。'
    }
    docker exec $ragflowContainer python -c "import urllib.request; urllib.request.urlopen('http://host.docker.internal:11528/api/tags', timeout=10)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'RAGFlow 容器无法访问宿主机 Ollama。'
    }
    Write-Host '[OK] RAGFlow 容器可以访问 Ollama' -ForegroundColor Green
}

Assert-Command 'docker'

# Docker Compose config 会先解析 YAML 和环境变量，避免启动时才发现编排错误。
docker compose @composeArgs config --quiet
Write-Host '[OK] Docker Compose 配置有效' -ForegroundColor Green

$psOutput = docker compose @composeArgs ps --format json | ConvertFrom-Json
if (-not $psOutput) {
    throw '没有发现正在运行的基础设施容器，请先执行 docker compose up -d。'
}

$expected = @('upil-postgres', 'upil-minio', 'upil-redis')
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

Assert-Http 'http://127.0.0.1:29000/minio/health/live' 'MinIO API'
Assert-Http 'http://127.0.0.1:29001' 'MinIO Console'
Assert-Http 'http://127.0.0.1:29080' 'RAGFlow Console'
Assert-OllamaEmbedding

# Redis 先检查宿主机端口，再通过容器内 REDISCLI_AUTH 做鉴权 Ping。
# 脚本不读取、不打印密码，也不把密码放进 redis-cli 参数。
$redisTcp = Test-NetConnection -ComputerName '127.0.0.1' -Port 16380 -WarningAction SilentlyContinue
if (-not $redisTcp.TcpTestSucceeded) { throw 'uPil Redis 16380 端口不可访问。' }
Write-Host '[OK] uPil Redis 16380 端口可访问' -ForegroundColor Green

$redisPing = docker compose @composeArgs exec -T upil-redis redis-cli ping
if ($LASTEXITCODE -ne 0 -or ($redisPing -join '').Trim() -ne 'PONG') {
    throw 'uPil Redis 鉴权健康检查失败。'
}
Write-Host '[OK] uPil Redis 鉴权 Ping -> PONG' -ForegroundColor Green

# API 的深探针会真实访问两个 RAGFlow Assistant，覆盖检索索引、Embedding
# 和回答模型。它可能触发冷启动，因此只在 API 已运行时执行一次，不用于
# Docker 高频健康检查；响应只包含状态，不包含知识库正文或任何凭据。
$apiHealthUrl = 'http://127.0.0.1:18000/api/v1/health/dependencies/deep'
try {
    $deepHealth = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 60
    if ($deepHealth.status -ne 'ok') {
        throw 'RAGFlow 深度业务探针未通过。'
    }
    Write-Host '[OK] RAGFlow 双知识域深度业务探针通过' -ForegroundColor Green
} catch {
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
        throw "RAGFlow 深度业务探针失败，HTTP 状态：$($_.Exception.Response.StatusCode.value__)"
    }
    throw "RAGFlow 深度业务探针不可用，请确认 uPil API 已启动；$($_.Exception.Message)"
}
Write-Host '基础设施与业务依赖检查通过。' -ForegroundColor Green

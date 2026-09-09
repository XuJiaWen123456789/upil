# 阶段 13-H：uPil API 与 A2A 学情分析子服务容器化联调

## 1. 阶段目标

本阶段把主 API 和学情分析 A2A 子服务放入独立的本地 staging 编排，验证容器内服务发现、非 root 运行、健康检查、SSE 对话和 A2A 业务调用。该环境用于生产化约束验证，不等于真实教育机构生产上线。

## 2. 部署拓扑

```text
浏览器 / curl
      │ 127.0.0.1:18000
      ▼
upil-api:8000  ───────►  upil-a2a-learning:8101
      │                         │
      ├── PostgreSQL             └── 只处理固定 learning_summary 任务
      └── MinIO

外部 RAGFlow 由独立 Compose 管理，staging 只通过配置接入，不重复声明有状态服务。
```

API 对宿主机只绑定回环地址；A2A 子服务不映射宿主机端口，只加入 `upil_network`，因此不能被局域网直接访问。

## 3. 关键工程约束

- 运行时基线固定为 Python 3.11。
- 镜像使用 `python:3.11-slim`，容器进程使用 uid/gid 10001 的 `upil` 用户。
- Compose 启用 `no-new-privileges` 和 `cap_drop: ALL`。
- A2A 任务使用严格 Pydantic 合同，拒绝未知字段、命令、SQL、URL 和任意代码执行参数。
- 主 API 只把脱敏学情摘要发送给子节点；A2A 失败时回退数据库可信摘要。
- 健康检查只返回状态，不返回密码、令牌、API Key、连接地址或第三方错误正文。
- `.env.staging` 只存在本机并被 `.gitignore` 忽略。

## 4. 启动与验证

```powershell
Set-Location D:/uPil
docker compose --env-file ./infra/staging/.env.staging `
  -f ./infra/staging/docker-compose.staging.yml up -d --build
docker compose --env-file ./infra/staging/.env.staging `
  -f ./infra/staging/docker-compose.staging.yml ps
curl.exe -sS http://127.0.0.1:18000/api/v1/health
curl.exe -sS http://127.0.0.1:18000/api/v1/health/dependencies
```

FAQ SSE：

```powershell
$body = @{ message = "编程课需要家长提前购买电脑吗？"; actor_role = "parent"; actor_user_id = "P1001" } | ConvertTo-Json -Compress
curl.exe -sS -N -X POST http://127.0.0.1:18000/api/v1/chat/stream `
  -H "Content-Type: application/json" --data-raw $body
```

学情 SSE：

```powershell
$body = @{ message = "查询课时和出勤"; learner_id = "L1001"; actor_role = "parent"; actor_user_id = "P1001" } | ConvertTo-Json -Compress
curl.exe -sS -N -X POST http://127.0.0.1:18000/api/v1/chat/stream `
  -H "Content-Type: application/json" --data-raw $body
```

学情请求的完成事件应能看到 `a2a_task` 状态为 `completed`，并且 provider 为 `a2a_http`。FAQ 在 staging 未注入 Chat ID 时可以安全显示离线回退；注入有效 Chat ID 后再验证 RAGFlow 真实链路。

## 5. 本次验证结果

- Compose 配置检查通过。
- API 和 A2A 镜像构建成功，容器均 healthy。
- API 通过 Docker 内部 DNS 访问 `upil-a2a-learning:8101`。
- PostgreSQL、MinIO 和 A2A 探针成功；RAGFlow 未配置 staging Chat ID 时为 `not_configured`。
- FAQ SSE、学情 SSE 和跨容器 A2A 任务调用成功。
- MinIO 初始探针失败定位为 staging 凭据与 MinIO root 凭据不一致，已修复并通过只读探针验证。

## 6. 尚未达到生产的部分

- A2A 子服务仍使用确定性 Mock 分析器，不是官方 A2A SDK，也未接入真实 DeepSeekHarness。
- 任务状态仍是单进程内存存储，多实例生产需要 Redis/PostgreSQL 持久化和原子幂等。
- 尚未接入真实教务、订单、工单和企业认证系统。
- 生产环境还需要 TLS/mTLS、集中式密钥管理、监控告警、限流、备份和数据合规审查。
- 所有业务数据仍为虚构演示数据。

## 7. 阶段结论

阶段 13-H 的基础容器化和跨容器业务联调完成。后续优先进行 RAGFlow Chat ID 注入后的真实 FAQ 链路验证，再评估 Redis 持久化和真实 DSH 执行器；不能把当前结果包装成真实生产上线。

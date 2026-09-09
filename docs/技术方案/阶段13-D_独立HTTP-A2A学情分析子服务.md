# 阶段 13-D：独立 HTTP A2A 学情分析子服务

> 数据声明：本阶段只使用虚构演示数据和确定性 Mock 分析逻辑，不代表已经接入真实教育机构、真实教务系统或 DeepSeekHarness。

## 1. 阶段目标

将阶段 13-C 的同进程 Mock 节点拆成独立本地 FastAPI 服务，使 uPil 主服务通过 HTTP 完成真正的跨进程任务调用，同时保留原有数据库事实链路和故障降级。

## 2. 服务边界

新增子服务入口：

~~~text
GET  /health
POST /internal/a2a/tasks
~~~

子服务只接收 `A2ATaskRequest`，只返回 `A2ATaskResult`。协议模型统一使用 `extra=forbid`，因此 command、SQL、任意 URL 和未知 skill 都不能进入任务处理逻辑。

当前子服务明确禁止：

- 连接数据库、RAGFlow、MinIO 或 Docker Socket；
- 接收用户指定的远程地址；
- 执行 Python、Shell、PowerShell 或 SQL；
- 接收学员姓名、手机号和内部学员编号；
- 在 production 环境开放 Mock 任务接口。

## 3. 跨进程调用链路

~~~text
SSE 请求
  -> LangGraph Supervisor
  -> 身份与数据权限校验
  -> BusinessToolRegistry 查询可信结构化快照
  -> 学员编号 SHA-256 脱敏
  -> HttpA2ALearningClient
  -> 127.0.0.1:8101/internal/a2a/tasks
  -> MockLearningAnalysisAgent
  -> A2ATaskResult / Markdown Artifact
  -> 主系统二次协议与安全校验
  -> SSE a2a_task + 最终回答
~~~

动态课时和出勤事实仍由主系统数据库工具提供。A2A 子节点只分析已经授权和脱敏的快照，不拥有数据源权限。

## 4. 协议和认证

- 请求和响应都携带固定协议版本 `upil-a2a/1.0`；
- HTTP `X-A2A-Service-Token` 用于本地内部服务鉴权；
- 服务令牌只从环境变量读取，未配置或少于 16 个字符时拒绝服务；
- 令牌使用常量时间比较，不写入 SSE、响应正文和项目日志；
- `correlation_id` 继承主请求 `X-Request-ID`；
- 每次分析生成唯一 `task_id`。

阶段 13-D 的 token 只是本地共享密钥占位。生产环境应使用 Secret Manager、TLS/mTLS、密钥轮换和网关级身份认证。

## 5. 地址限制与 SSRF 防护

`local_http` 模式只接受：

~~~text
http://127.0.0.1:<port>
http://localhost:<port>
http://[::1]:<port>
~~~

客户端拒绝 HTTPS 伪配置、局域网/公网主机、URL 用户名密码、查询字符串和片段。任务请求中也不存在 URL 字段，调用者不能将固定客户端转换为任意地址代理。

## 6. 超时、重试和降级

- HTTP 超时：最多重试两次，即总共最多三次请求；
- 401、422、500 等非 2xx：不重试，避免重试风暴；
- 响应 JSON、协议版本、关联 ID 或 Artifact 校验失败：不重试；
- 子服务失败：LangGraph 返回数据库基础摘要，并通过 SSE 标记 `fallback=database`；
- 数据库或权限校验失败：不调用 A2A，也不生成猜测结果。

## 7. 配置

~~~ini
A2A_LEARNING_ENABLED=false
A2A_LEARNING_MODE=mock
A2A_LEARNING_BASE_URL=http://127.0.0.1:8101
A2A_LEARNING_SERVICE_TOKEN=
A2A_LEARNING_TIMEOUT_SECONDS=10
A2A_LEARNING_MAX_RETRIES=2
~~~

默认仍关闭 A2A，并保留 `mock` 模式。只有明确设置 `A2A_LEARNING_ENABLED=true` 和 `A2A_LEARNING_MODE=local_http` 时才进行跨进程调用。

## 8. 本地启动方法

在两个 PowerShell 窗口中设置相同的临时内部 token，且不要将真实值提交到源码：

~~~powershell
# 窗口 1：A2A 子服务
Set-Location D:\uPil
$env:APP_ENV = "development"
$env:A2A_LEARNING_SERVICE_TOKEN = "请替换为至少16位的本地随机值"
.\.venv\Scripts\python.exe -m uvicorn backend.app.a2a.mock_server:app --host 127.0.0.1 --port 8101
~~~

~~~powershell
# 窗口 2：uPil 主服务
Set-Location D:\uPil
$env:A2A_LEARNING_ENABLED = "true"
$env:A2A_LEARNING_MODE = "local_http"
$env:A2A_LEARNING_BASE_URL = "http://127.0.0.1:8101"
$env:A2A_LEARNING_SERVICE_TOKEN = "与窗口1相同的本地随机值"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
~~~

## 9. 验证结果

- 阶段新增 HTTP 测试：14 项；
- 阶段相关定向测试：41 passed；
- 全量回归：119 passed, 1 skipped；
- 双进程真实 HTTP 联调成功；
- 子服务健康检查返回 200；
- 主 API SSE 返回 `a2a_task=completed`、正确 correlation_id 和 `provider=a2a_http`；
- 联调结束后已关闭两个临时服务。

## 10. 当前边界与下一步

当前已经实现真正的本地跨进程 HTTP 调用，但仍不是官方 A2A SDK 的完整实现，也未接入 DeepSeekHarness。下一阶段应先补充任务状态存储、幂等处理、可观测指标和故障演练，再判断是否有必要把确定性 Mock 执行器替换为受控 DSH 节点。

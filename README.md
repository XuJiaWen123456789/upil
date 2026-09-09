# uPil

uPil 是面向素质教育机构的智能客服与课时学情助手。本仓库当前已完成阶段 13-H 的基础容器化联调，包含可运行的后端骨架、LangGraph 路由、结构化学情工具、数据库查询链路、MinIO 媒体接口、RAGFlow 适配器，以及独立本地 HTTP A2A 学情分析子服务。

## 当前阶段

- FastAPI 健康检查接口
- POST + SSE 对话接口
- LangGraph Supervisor 风格的最小意图路由
- FAQ、学情摘要、人工转接三个演示节点
- SQLite/PostgreSQL 可切换的 SQLAlchemy 数据层
- 家长、教师和管理员的基础学员访问控制
- 学情摘要从数据库统计课时、消课和出勤
- 学情分析白名单工具：学员资料、出勤统计、课时账户和阶段进度
- 结构化学情快照接口，可供后续 A2A Task 封装
- FAQ 服务支持 RAGFlow、LangChain 和离线回退三种运行模式
- RAGFlow v0.27.1 本地 Docker 服务已完成健康检查，FAQ 适配器使用推荐 OpenAI 兼容接口并保留来源引用
- FAQ 知识资源支持 Markdown 图片、表格和图片替代文本；图片和文档原文件统一存入 MinIO
- MinIO 图片上传、审核、权限校验和短时预签名 URL 接口
- 通用意图与实体契约、课程名称标准化、课程纠正覆盖和检索查询改写基础模块
- 供应商无关的结构化意图识别适配器，支持 Pydantic 严格校验、课程白名单、
  高风险确定性守卫、模型异常回退和识别来源诊断
- DeepSeek deepseek-chat 真实模型意图评估已完成，固定用例结果为 8/8；
  结构化识别、查询改写和安全路由已接入 LangGraph/SSE 在线链路
- 可选 `conversation_id` 支持最近课程实体、课程纠正和后续指代；开发期
  状态使用带 TTL/容量限制的进程内 Store，生产需替换为 Redis/PostgreSQL
- A2A 学情分析支持默认关闭的 `mock` 与 `local_http` 两种模式；HTTP 模式已完成
  本地跨进程联调、服务令牌校验、协议版本校验、有限超时重试、任务幂等、状态查询、
  脱敏指标和数据库降级
- 客服演示页已由 FastAPI 直接托管，支持 POST + SSE 增量输出、会话切换、快捷问题、
  A2A 任务状态、请求观测指标、真实引用调试展示和 AbortController 请求取消
- DSH 执行器当前仅完成受控门禁和默认关闭适配器；只允许学情分析技能，未接入真实
  DeepSeekHarness，也不执行用户提交的代码

当前开发机已通过本地 `.env` 配置 DeepSeek，仅用于显式真实评估和本地
在线链路；密钥未写入源码或 `.env.example`。RAGFlow Dataset 已完成解析与
元数据验证，FAQ 在线调用取决于有效的 RAGFlow Chat ID。当前客服演示页已经实现，
但仍属于本地 staging 展示层，不能替代正式的认证和运营后台。
PostgreSQL 连接配置已经准备好，本地测试默认使用注入的 SQLite 内存数据库。

## 项目过程文档

- D:/uPil/docs/PROJECT_LOG.md：按阶段记录完成内容、问题、解决方案和验证结果。
- D:/uPil/docs/TECH_DECISIONS.md：记录 MinIO、PostgreSQL、RAGFlow、向量检索和 A2A 的技术决策。
- D:/uPil/docs/DEFENSE_INTERVIEW_QA.md：整理多智能体、A2A、RAGFlow、MinIO、SSE 和数据安全等答辩与面试问答。

阶段 13-H 的 staging 编排文件位于 D:/uPil/infra/staging。它使用 Python 3.11、
非 root 用户和独立 Docker 网络，将 API 与 A2A 子服务放入可复现的本地预发布环境。
启动前请将 .env.staging.example 复制为 .env.staging 并填写本机依赖凭据；
.env.staging 已被 Git 忽略，不能提交真实密钥。

```powershell
Set-Location D:/uPil
docker compose --env-file ./infra/staging/.env.staging `
  -f ./infra/staging/docker-compose.staging.yml up -d --build
docker compose --env-file ./infra/staging/.env.staging `
  -f ./infra/staging/docker-compose.staging.yml ps
curl.exe -sS http://127.0.0.1:18000/api/v1/health
curl.exe -sS http://127.0.0.1:18000/api/v1/health/dependencies
```

健康检查中 ok 表示探针成功，not_configured 表示可选能力尚未注入配置，
degraded 表示至少一个已启用依赖异常。当前 staging 的 A2A 是本地受控 Mock
学情分析子服务，不代表已接入真实 DeepSeekHarness 或真实教育机构生产数据。

第 3 阶段本轮已完成外部能力适配层，但没有伪造在线服务已连接。只有设置完整的
LLM 或 RAGFlow 配置后，FAQ 才会访问对应服务；未配置时会稳定回退到离线回答。

本地持久化联调可使用 SQLite 文件库。初始化后数据库文件位于 D:/uPil/data/upil.db，
可供本地数据工具读取；该文件只包含演示数据，不应作为生产数据库使用。

## FAQ 知识资源与图片

演示知识库位于 D:/uPil/knowledge_base，其中包含校区、课程、收费、请假补课、装备和活动服务等 FAQ 文档。
复杂资料示例位于 D:/uPil/knowledge_base/demo_institution/01_institution/教师与校区环境.md，展示了教师介绍表格、校区环境图和周末课程安排图。
当前图片是虚构 SVG 演示素材，正式环境需要替换为已授权并审核通过的图片。

图片和文档原文件使用 MinIO 对象存储，安装媒体依赖并配置 MinIO 后可使用：

uv pip install -e ".[media]"

$env:MINIO_ENDPOINT = "localhost:19000"
$env:MINIO_ACCESS_KEY = "minioadmin"
$env:MINIO_SECRET_KEY = "minioadmin"
$env:MINIO_BUCKET = "upil-media"
$env:MINIO_SECURE = "false"

RAGFlow 保存文档正文、表格、OCR 文本和图片说明；MinIO 保存图片和文档原文件，PostgreSQL 保存媒体元数据及对象键。uPil 在权限校验通过后生成短时预签名 URL。SSE 只返回 media_asset_id 等脱敏引用，不返回二进制内容。真实环境还必须补充图片下载接口的登录态、可见范围校验和 SVG 消毒。

媒体接口：

- POST /api/v1/media/images：教师或管理员上传图片，素材默认进入 pending 审核状态。
- POST /api/v1/media/{asset_id}/review：管理员将素材标记为 approved 或 rejected。
- GET /api/v1/media/{asset_id}/url：审核通过且当前角色有权限时生成 600 秒预签名 URL。

上传接口会校验文件大小、Content-Type、PNG/JPEG/WebP 文件签名和基础 SVG 安全规则。对象元数据中的中文会进行 UTF-8 百分号编码，业务数据库仍保存完整中文字段。当前开发接口中的 actor_role 和 actor_user_id 仍是模拟身份参数，不能直接用于生产鉴权。

接口中的 actor_role 和 actor_user_id 仅用于开发和测试身份模拟。正式环境必须从登录态、JWT 或网关注入身份，不能信任客户端直接提交的角色和用户编号。

## 本地运行

uv venv --python 3.11 .venv
.\\.venv\\Scripts\\Activate.ps1
uv pip install -e ".[dev]"
uvicorn backend.app.main:app --reload --port 8000

需要使用 LangChain 的 OpenAI 兼容模型时，可额外安装可选依赖：

uv pip install -e ".[llm]"

初始化本地 SQLite 文件库：

python -m scripts.init_db

使用本地 SQLite 文件库启动 API：

$env:DATABASE_URL = "sqlite:///D:/uPil/data/upil.db"
$env:LLM_ENABLED = "false"
# 真实模型接入时再填写以下配置，并且不要把密钥提交到代码仓库：
# $env:LLM_ENABLED = "true"
# $env:LLM_BASE_URL = "https://your-openai-compatible-endpoint/v1"
# $env:LLM_API_KEY = "your-api-key"
# $env:LLM_MODEL = "your-model-name"
# $env:RAGFLOW_BASE_URL = "http://localhost:19380"
# $env:RAGFLOW_API_KEY = "your-ragflow-api-key"
# $env:RAGFLOW_CHAT_ID = "your-chat-id"
uvicorn backend.app.main:app --reload --port 8000

健康检查：http://127.0.0.1:8000/api/v1/health

结构化学情联调接口：

http://127.0.0.1:8000/api/v1/learners/L1001/learning-snapshot

该接口的 actor_role 和 actor_user_id 目前只用于本地开发模拟身份；生产环境必须由认证中间件注入，不能信任客户端查询参数。

## SSE 验证

curl.exe -N -X POST http://127.0.0.1:8000/api/v1/chat/stream
  -H "Content-Type: application/json"
  -d '{"message":"查询课时和出勤","actor_role":"parent","actor_user_id":"P1001","learner_id":"L1001"}'

预期事件顺序包含 status(accepted)、status(routed)、多个 token 和 complete。
如需多轮实体指代，在每轮请求中传入相同的 `conversation_id`；不传则保持
向后兼容的单轮无状态行为。complete 事件还包含 `recognition_source`，用于
区分真实模型、确定性高风险守卫和模型异常回退。
FAQ 在配置 LangChain 模型后使用 astream 转发真实模型片段；未配置时使用固定回答切片，
因此离线环境也能验证 SSE 协议。RAGFlow 当前使用非流式 Chat API，但会统一切片为 token，
并在 complete.sources 中返回最多 10 条经过截断的来源引用。学情和人工分支仍由 LangGraph
完整执行，完成事件会携带 provider 和 sources 字段。

完成事件示例：

{
  "route": "faq",
  "provider": "offline",
  "sources": []
}

家长 P1001 只能查询已绑定的学员 L1001。

## 本地 HTTP A2A 演示

独立子服务入口为 `backend.app.a2a.mock_server:app`，默认监听建议端口为 8101。
只有显式设置 `A2A_LEARNING_ENABLED=true`、`A2A_LEARNING_MODE=local_http`，并在
主服务和子服务中配置相同的至少 16 位本地服务令牌时，主服务才会跨进程调用。
详细启动命令、安全边界和测试结果参见：
`D:/uPil/docs/技术方案/阶段13-D_独立HTTP-A2A学情分析子服务.md`。
阶段 13-E 的任务幂等、TTL、容量限制和指标设计参见：
`D:/uPil/docs/技术方案/阶段13-E_A2A任务幂等状态与可观测性.md`。
阶段 13-F 的 DSH 门禁和适配器边界参见：
`D:/uPil/docs/技术方案/阶段13-F_DSH受控执行门禁与适配器边界.md`。

项目正式开发基线为 Python 3.11，版本由 .python-version 固定。Python 3.14 仅用于早期临时冒烟验证。

RAGFlow 本地服务：控制台 http://localhost:19080，OpenAI 兼容 API http://localhost:19380。
当前还需要在控制台配置 Chat Model 和 Embedding Model，创建 Chat Assistant 后再填写
RAGFLOW_API_KEY 与 RAGFLOW_CHAT_ID；未填写时 FAQ 会安全回退到离线回答。

## 测试

pytest -q

默认测试不会访问真实模型，即使本地 .env 已配置 API Key。显式运行真实
DeepSeek 意图识别评估：

    $env:PYTHONUTF8 = "1"
    .\.venv\Scripts\python.exe -m scripts.evaluate_real_intent_model

显式运行真实模型 pytest 冒烟测试：

    $env:UPIL_RUN_REAL_LLM_TESTS = "true"
    .\.venv\Scripts\python.exe -m pytest tests/test_real_intent_model.py -q

普通语义用例必须显示 source=model；实时名额、课时和出勤等高风险用例
应显示 source=deterministic_guard。若出现 source=deterministic_fallback，
说明模型调用或结构化校验失败，不能把回退恰好答对误报为真实模型成功。

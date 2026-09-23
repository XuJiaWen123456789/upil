# uPil

uPil 是一个面向素质教育机构的多 Agent 智能客服与学情服务项目。系统围绕家长咨询、课程规则问答、学情查询、家长与教师报告、试听报名线索跟进等真实业务场景构建，并通过统一身份上下文、确定性业务工具和权限校验控制模型的能力边界。

本仓库是个人求职项目的运行交付副本，提供前后端及基础设施；按交付范围不包含自动化测试源码。它不宣称已经接入真实教育机构数据、正式身份提供方、CRM、电话、短信或支付系统。

## 核心能力

- **多 Agent 对话编排**：Supervisor 负责意图规划和状态仲裁，FAQ、服务规则、统一学情分析、人工转接等节点只处理各自职责。
- **结构化意图识别**：使用 Pydantic 校验模型输出，并结合确定性守卫、模型失败回退、槽位确认和 pending flow 防止错误路由。
- **多轮上下文治理**：支持课程指代消解、用户纠错、话题恢复、显式取消、槽位补全和会话摘要。
- **受控长期记忆**：仅保存课程兴趣、上课时间偏好和孩子昵称等低敏感稳定信息，新会话可以按可信用户身份继承。
- **RAGFlow 知识问答**：公开课程咨询和服务规则使用独立知识域，支持来源引用、混合检索及不可用时的受控降级。
- **确定性学情查询**：出勤、课时、学习进度和班级统计由数据库与业务工具计算，LLM 只负责理解、归纳和表达。
- **学情报告闭环**：家长和教师可通过聊天或页面入口生成报告，系统完成统计、PDF 生成、MinIO 私有存储和下载时重新鉴权。
- **试听报名线索闭环**：主业务回答与报课意向分析并行运行，高意向时主动征得联系方式授权，并将线索交给具有最小权限的销售顾问老师跟进。
- **多角色工作台**：Vue 前端按家长、任课教师和销售顾问老师的能力动态展示页面与操作。

## 技术栈

| 层次 | 技术 | 用途 |
| --- | --- | --- |
| 后端 | Python 3.11、FastAPI、SQLAlchemy | API、SSE、业务服务与持久化 |
| Agent | LangChain 1.x、LangGraph 1.x、Pydantic | 模型适配、工作流编排和结构化输出 |
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Pinia | 多角色业务工作台 |
| 业务数据库 | PostgreSQL | 用户、学员、课程、会话目录、报告、线索和长期偏好 |
| 短期状态 | Redis | 会话窗口、滚动摘要、确认槽位和 pending 状态 |
| 对象存储 | MinIO | 私有保存学情报告 PDF |
| 知识库 | RAGFlow | 文档解析、切片、检索和来源引用 |
| PDF | markdown-it-py、WeasyPrint、pypdf | 受控 Markdown 渲染、PDF 生成与交付前校验 |
| 测试 | pytest、Vitest、vue-tsc | 后端、前端、类型和构建验证 |

## 系统架构

```text
浏览器 / Vue 3
       |  REST + SSE
       v
FastAPI API
       |
       +-- 身份认证与 AccessContext
       +-- 会话目录、报告、线索等业务 API
       +-- LangGraph 对话工作流
       |      |
       |      +-- Supervisor / 意图仲裁
       |      +-- FAQ Agent ---------> RAGFlow 公开咨询知识域
       |      +-- 服务规则 Agent ----> RAGFlow 服务规则知识域
       |      +-- 统一学情分析 Agent -> SQLAlchemy 业务工具
       |      +-- 人工转接、澄清、闲聊和越界节点
       |      +-- 报课意向 Agent（旁路分析）
       |
       +-- PostgreSQL：业务数据、会话历史、长期偏好、报告和线索
       +-- Redis：短期会话状态
       +-- MinIO：私有 PDF 对象
```

多 Agent 在本项目中表示**职责、上下文和工具权限的隔离**，不表示每个 Agent 都是独立进程或远程服务。需要共享业务能力的节点通过受控 Service 和 Tool 复用实现，而不是复制一套逻辑。

当前运行链路已经移除 A2A/DSH。相关文档仅保留为历史技术探索和取舍记录，不是当前部署依赖。

## Agent 工作流

当前对话图定义在 `backend/app/workflows/conversation/`，主要节点如下。

| 节点 | 职责 | 主要数据来源 |
| --- | --- | --- |
| Supervisor | 识别主意图、旁路意图、实体和槽位，仲裁 pending flow | 当前消息、受控上下文、Router 模型 |
| FAQ Agent | 回答课程、适龄、装备、校区和活动等公开问题 | RAGFlow 公开咨询知识域 |
| 服务规则 Agent | 回答请假、调课、补课等规则问题 | RAGFlow 服务规则知识域 |
| 统一学情分析 Agent | 处理个人学情、家长报告和教师班级报告 | 权限校验后的数据库工具 |
| 报告历史节点 | 查询当前身份有权访问的报告记录 | PostgreSQL |
| 人工转接节点 | 对需要人工确认的事项给出受控转接说明 | 当前会话状态 |
| 槽位澄清节点 | 只追问完成当前任务所缺少的信息 | 已确认槽位与 pending 状态 |
| 闲聊节点 | 处理问候、结束和礼貌表达 | 当前消息 |
| 超出范围节点 | 拒绝与教育咨询无关的请求 | 意图决策 |
| 报课意向 Agent | 与主回答并行识别试听、报名和顾问联系意图 | 脱敏后的受控上下文 |

报课意向 Agent 不直接替代主业务回复。FAQ 或规则节点继续回答用户问题，旁路分析只更新线索状态；只有满足高意向规则时，系统才附加联系方式授权询问。

## 意图识别与仲裁

Supervisor 不是单纯依赖一个分类 Prompt，而是组合以下机制：

1. Router 模型输出强结构化结果，使用 Pydantic 校验；Router 可单独配置模型，并固定 `temperature=0`。
2. 课程名称、角色、报告动作和服务规则等高风险实体经过白名单和确定性规则复核。
3. 模型失败、超时或输出不合法时进入确定性回退，不把异常直接暴露给用户。
4. 用户原话提供的槽位标记为已确认；模型推断值不能直接驱动学情报告等高风险工具。
5. 课程纠错会覆盖旧实体，指代消解优先使用最近已确认主题，pending 任务不能劫持无关的新问题。
6. `UNKNOWN` 区分“信息不足”和“超出业务范围”，前者澄清，后者拒绝，不统一丢给 FAQ。

当前仲裁优先级为：

```text
显式取消或安全边界
  > 与当前 pending 兼容的槽位补全
  > 本轮主意图
  > 旁路能力
  > UNKNOWN 处理
```

决策链日志只记录脱敏原因码和必要诊断信息，不记录完整手机号、邮箱、Token 或原始敏感消息。

## 上下文与记忆

项目没有把全部聊天记录无限塞入 Prompt，也没有把所有对话无差别写入向量数据库。当前采用分层、受控的上下文与记忆方案。

### 当前请求上下文

`ContextEnvelope` 是服务端构造的不可变上下文投影，包含可信身份、角色、会话编号、确认槽位和允许暴露的业务信息。Agent 只能读取完成当前职责所需的字段，不能自行声明用户身份或扩大数据范围。

### 短期会话记忆

Redis 按租户、用户和会话作用域保存：

- 最近若干轮脱敏对话；
- 滚动摘要；
- 已确认课程、年龄、基础和时间偏好等槽位；
- pending flow 及其状态；
- TTL 和容量限制。

提示词输入由“结构化槽位 + 最近原始轮次 + 历史摘要”组成，并受 Token 预算控制。Redis 是 uPil 独立实例，不复用 RAGFlow 内部的 Redis/Valkey。

### 会话历史

PostgreSQL 保存会话目录和脱敏后的消息历史，用于侧边栏的新建、继续、重命名、删除和恢复。会话访问始终按可信用户身份隔离。

### 长期偏好

长期记忆当前只允许以下低敏感、相对稳定的结构化类型：

- `course_interest`：课程兴趣；
- `class_time_preference`：上课时间偏好；
- `child_nickname`：孩子昵称。

用户明确说“请记住”时可触发写入；高置信度的稳定陈述也可在受控规则下保守写入。相同用户更换 `conversation_id` 后仍可读取这些偏好。手机号、邮箱、密码、Token、银行卡、实时名额、动态课时、出勤和报告状态不会作为长期偏好保存。

当前实现采用自定义 Redis 会话状态和 PostgreSQL 结构化长期记忆，并非 LangGraph Checkpointer/Store。情景向量记忆默认关闭（`EPISODIC_MEMORY_ENABLED=false`），因此 README 不把尚未评测的向量召回写成已上线能力。

## RAGFlow 检索链路

RAGFlow 负责知识文档的 PDF/Markdown 解析、OCR、表格处理、切片、向量或混合检索和来源引用；uPil 负责意图路由、身份权限、会话状态、SSE、业务统计、报告和线索。两者的职责边界保持分离。

```text
用户问题
  -> Supervisor 判断 FAQ 或服务规则
  -> 查询改写与课程实体标准化
  -> 调用对应的 RAGFlow Chat Assistant
  -> 解析答案和来源引用
  -> 安全过滤与业务边界补充
  -> SSE 返回前端
```

公开 FAQ 与服务规则使用两个独立 Chat Assistant，避免知识域相互污染。本地 RAGFlow 可使用 Ollama `bge-m3:latest` 作为 Embedding 模型；具体部署和知识库初始化见 [infra/ragflow/README.md](infra/ragflow/README.md)。

## 学情与报告

### 确定性学情统计

个人与班级学情由后端查询数据库并计算，包含课时、出勤、阶段进度、完课率、缺勤情况和数据缺失提示。LLM 不负责编造统计值，只在经过授权的统计快照上生成自然语言归纳。

### 报告生成与下载

家长可生成绑定孩子的学情报告，教师可生成自己实际授课且属于本人校区范围内的班级报告。报告周期支持自然语言表达；未指定时默认最近 30 天。

```text
生成请求
  -> 身份、学员或班级归属校验
  -> 相同范围与周期的幂等检查
  -> 数据库确定性统计
  -> 固定模板 Markdown（仅内存中间态）
  -> markdown-it-py 白名单渲染
  -> WeasyPrint 生成 PDF
  -> pypdf 检查页数、模板文字和敏感信息泄漏
  -> MinIO 私有桶保存
  -> PostgreSQL 保存任务和 Artifact 元数据
```

新任务只生成一个 PDF Artifact，不生成 CSV 双产物。下载由后端重新校验当前用户权限后代理返回，不向浏览器暴露 MinIO 对象键、内部地址、访问密钥或预签名 URL。系统仍兼容读取早期家长 Markdown Artifact，但不会为新任务继续创建它。

## 报课意向与销售跟进

线索流程保持在聊天主体验中，不要求家长进入后台表单：

1. 主 Agent 正常回答课程问题，报课意向 Agent 在旁路读取同一轮脱敏上下文。
2. 系统结合模型证据和确定性规则判断意向强度。
3. 明确提出试听、报名或要求顾问联系视为高意向。
4. 如果没有联系方式，系统主动询问用户是否愿意提供并同意销售顾问老师联系。
5. 只有用户主动提供联系方式且在同一轮明确授权，系统才保存密文、检索指纹和掩码。
6. 具有 `lead_followup` 权限的销售顾问老师可领取线索、按需查看联系方式并记录跟进。

联系方式会在进入 LLM 和 RAGFlow 前脱敏。销售顾问老师复用 `teacher` 认证角色，但只按能力点开放线索工作台；销售顾问不显示教师班级统计页面。项目不提供运营角色、转化漏斗、综合 CRM、外呼、短信或支付集成。

## 身份、权限与隔离

后端支持三种认证模式：

| 模式 | 用途 | 说明 |
| --- | --- | --- |
| `demo` | 本地开发与自动化测试 | 允许使用数据库中的演示身份，不可作为生产认证 |
| `trusted_headers` | 可信认证网关后方部署 | 仅接受带共享代理密钥的身份 Header |
| `oidc_jwt` | OIDC Resource Server | 验证非对称 JWT、issuer、audience、有效期和 JWKS |

OIDC 外部身份通过 `(issuer, subject)` 映射到本地用户；角色、账号状态、校区和能力点始终以本地数据库为准，不能由 Token 或客户端任意覆盖。仓库实现了 Resource Server 侧能力，但没有部署真实 Keycloak、Auth0 或机构 IdP。

核心授权规则：

- 家长只能访问本人绑定的孩子、报告和会话；
- 教师只能访问自己实际授课且处于本人校区范围内的班级和学员；
- 销售顾问老师必须具有 `lead_followup` 权限才能访问线索；
- 报告的生成、列表、详情和下载均重新执行资源归属校验；
- Redis 和 PostgreSQL 的会话、偏好按租户、用户、角色及必要的学员作用域隔离；
- 客户端提交的模拟身份在 `trusted_headers` 和 `oidc_jwt` 模式下会被忽略。

当前业务用户模型只有 `parent` 和 `teacher`，没有管理员或运营业务角色。

## 前端页面

| 路由 | 页面 | 访问条件 |
| --- | --- | --- |
| `/chat` | 多轮咨询、会话历史和报告入口 | `chat_access` |
| `/parent/learning` | 家长实时学情 | 家长 + `learning_read` |
| `/parent/reports` | 学生学情报告列表 | 家长 + `report_read` |
| `/parent/reports/:taskId` | 学生学情报告详情 | 家长 + `report_read` |
| `/teacher/classes` | 教师班级学情 | 教师 + `class_summary_read` |
| `/teacher/reports/:taskId` | 班级报告详情 | 教师 + `class_summary_read` |
| `/teacher/leads` | 销售线索工作台 | 教师 + `lead_followup` |

Vue 3 + TypeScript + Vite 用于承载多角色导航、SSE、会话历史、报告详情和线索工作台。Chainlit 或 Streamlit 更适合快速原型，不适合当前细粒度权限、复杂页面路由和文件交付需求。生产构建由 FastAPI 同源托管，减少跨域和重复认证配置。

## 项目目录

```text
uPil/
├─ backend/app/
│  ├─ agents/          # 各业务 Agent 及单职责处理器
│  ├─ api/             # FastAPI 路由、依赖和响应边界
│  ├─ configuration/   # 配置模型、弃用项检查和配置审计
│  ├─ connectors/      # RAGFlow、模型和外部边界适配器
│  ├─ context/         # ContextEnvelope 与可信上下文构造
│  ├─ conversations/   # 会话目录和消息历史
│  ├─ dialogue/        # 意图、槽位、课程实体和状态仲裁
│  ├─ integrations/    # 数据库、Redis、MinIO 等集成
│  ├─ memory/          # 结构化长期记忆及写入策略
│  ├─ observability/   # 脱敏日志和运行观测
│  ├─ prompts/         # Prompt 常量和装配逻辑
│  ├─ services/        # 报告、线索、认证等业务服务
│  ├─ tools/           # Agent 可调用的受控业务工具
│  └─ workflows/       # LangGraph 状态、节点、路由和图构建
├─ frontend/           # Vue 3 多角色前端
├─ infra/              # uPil、RAGFlow 和 staging 编排
├─ knowledge_base/     # 知识库源文件与构建资源
├─ scripts/            # 初始化、审计、评测和构建脚本
└─ docs/               # 技术方案、日志、测评集和面试问答
```

生产 Python 代码按 Agent、API、Workflow、Service、Tool、Connector 和 Prompt 分层，当前没有超过 800 行的生产 Python 文件。测试文件不参与该限制。

## 主要 API

### 健康、会话与聊天

```text
GET    /api/v1/health
GET    /api/v1/health/dependencies
GET    /api/v1/health/dependencies/deep
GET    /api/v1/frontend/bootstrap
GET    /api/v1/session
POST   /api/v1/chat/stream

POST   /api/v1/conversations
GET    /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}/messages
PATCH  /api/v1/conversations/{conversation_id}
DELETE /api/v1/conversations/{conversation_id}
```

### 学情与报告

```text
GET    /api/v1/learners/{learner_id}/learning-snapshot
GET    /api/v1/classes/{class_id}/learning-summary

POST   /api/v1/learners/{learner_id}/reports
POST   /api/v1/classes/{class_id}/reports
GET    /api/v1/classes/{class_id}/reports
GET    /api/v1/reports
GET    /api/v1/reports/{task_id}
GET    /api/v1/reports/{task_id}/download
```

### 销售线索

```text
GET    /api/v1/leads
GET    /api/v1/leads/{lead_id}
GET    /api/v1/leads/{lead_id}/contact
POST   /api/v1/leads/{lead_id}/follow-ups
```

`POST /api/v1/internal/demo/class-availability` 只供开发环境演示数据使用，不是生产业务接口。

## 本地启动

以下命令以 Windows PowerShell 和项目目录 `D:\uPil` 为例。

### 1. 安装后端依赖

```powershell
Set-Location D:\uPil
uv venv --python 3.11 .venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev,memory,llm,storage]"
Copy-Item .env.example .env
```

复制配置后，至少应修改 `.env` 中的 Redis 密码。需要真实模型、RAGFlow 或 PDF 下载时，再填写对应密钥和开关；不要把本地 `.env` 提交到 Git。

### 2. 启动 uPil 基础设施

```powershell
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

该 Compose 只启动 uPil 自己的 PostgreSQL、MinIO 和 Redis，不包含 RAGFlow。

### 3. 初始化数据库

```powershell
python -m scripts.init_db --database-url "postgresql+psycopg://upil:upil@localhost:5432/upil"
```

### 4. 启动后端

```powershell
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：`http://127.0.0.1:8000/api/v1/health`。

Windows 本机直接运行 WeasyPrint 时，除 Python 依赖外还必须安装兼容的
Pango、GLib 原生运行库。`/api/v1/health/dependencies` 中的
`pdf_renderer` 必须为 `ok` 才能在该 API 实例生成 PDF；若为 `error`，请使用
Docker 完整运行环境，不要从本机开发 API 发起报告任务。

### 5. 启动前端开发服务器

```powershell
Set-Location D:\uPil\frontend
npm ci
npm run dev
```

Vite 默认运行在 `http://127.0.0.1:5173`，并将 `/api` 请求代理到开发 API。

需要由 FastAPI 同源托管前端时，在 `frontend` 目录执行：

```powershell
npm run build:backend
```

然后访问 `http://127.0.0.1:8000/chat`。

### 6. 启用 RAGFlow 和 PDF 报告

RAGFlow 使用独立编排，启动、模型配置和知识库初始化见 [infra/ragflow/README.md](infra/ragflow/README.md)。根 `.env` 需要配置：

```dotenv
RAGFLOW_BASE_URL=http://localhost:29380
RAGFLOW_API_KEY=...
RAGFLOW_PUBLIC_CHAT_ID=...
RAGFLOW_SERVICE_RULES_CHAT_ID=...
```

启用 PDF 私有交付前，确认中文字体存在且 MinIO 可访问：

```dotenv
MINIO_ENABLED=true
REPORT_PDF_ENABLED=true
REPORT_PDF_FONT_PATH=C:\Windows\Fonts\NotoSansSC-VF.ttf
REPORT_PDF_BUCKET=upil-reports
```

### 7. 可选 staging API

Staging API 使用独立 Compose，只编排 API 容器，并连接已经运行的 uPil 基础设施：

```powershell
docker compose -f infra/staging/docker-compose.staging.yml up -d --build
```

启动后访问 `http://127.0.0.1:18000`。首次运行前需要按 staging 模板准备 `infra/staging/.env.staging`。

## Docker 与端口

| 服务 | 默认地址或端口 | 编排归属 |
| --- | --- | --- |
| 开发 API | `http://127.0.0.1:8000` | 本机进程 |
| Vite 前端 | `http://127.0.0.1:5173` | 本机进程 |
| Staging API | `http://127.0.0.1:18000` | `infra/staging/docker-compose.staging.yml` |
| PostgreSQL | `127.0.0.1:5432` | `infra/docker-compose.yml` |
| uPil Redis | `127.0.0.1:16380` | `infra/docker-compose.yml` |
| MinIO API | `http://127.0.0.1:29000` | `infra/docker-compose.yml` |
| MinIO Console | `http://127.0.0.1:29001` | `infra/docker-compose.yml` |
| RAGFlow Console | `http://127.0.0.1:29080` | RAGFlow 独立编排 |
| RAGFlow API | `http://127.0.0.1:29380` | RAGFlow 独立编排 |
| Ollama | `127.0.0.1:11528` | RAGFlow 本地模型环境 |

RAGFlow 还维护自己的 Elasticsearch、MySQL 和 Valkey。它们不是 uPil 业务 PostgreSQL 和会话 Redis 的替代品，也不应共用数据卷或清理策略。

## 关键配置

| 配置 | 说明 | 默认状态 |
| --- | --- | --- |
| `AUTH_MODE` | `demo`、`trusted_headers` 或 `oidc_jwt` | `demo` |
| `DATABASE_URL` | PostgreSQL 连接地址 | 本地 PostgreSQL |
| `CONVERSATION_STORE_BACKEND` | 短期会话存储后端 | `redis` |
| `REDIS_URL` | uPil 独立 Redis 地址 | 本地 `16380` |
| `MEMORY_WRITE_ENABLED` | 结构化长期偏好写入 | 开启 |
| `EPISODIC_MEMORY_ENABLED` | 情景向量记忆 | 关闭 |
| `LLM_ENABLED` | 启用真实 OpenAI-compatible 模型 | 关闭 |
| `LLM_ROUTER_MODEL` | 可选独立 Router 模型 | 复用主模型 |
| `RAGFLOW_*` | RAGFlow 地址、密钥和两个 Chat ID | 需本地配置 |
| `MINIO_ENABLED` | 将 MinIO 纳入对象存储与健康检查 | 关闭 |
| `REPORT_PDF_ENABLED` | 启用 PDF 报告生成 | 关闭 |
| `LEAD_CONTACT_ENCRYPTION_KEY` | 联系方式 Fernet 加密密钥 | 需安全注入 |
| `LEAD_CONTACT_FINGERPRINT_KEY` | 联系方式 HMAC 指纹密钥 | 需安全注入 |
| `LEAD_NOTIFICATION_ENABLED` | 启用招生线索外部提醒 | 关闭 |
| `LEAD_NOTIFICATION_MIN_LEVEL` | 飞书通知最低意向等级 | `high` |
| `FEISHU_WEBHOOK_URL` | 飞书群机器人 Webhook，禁止提交仓库 | 需安全注入 |

完整示例见 [.env.example](.env.example)。启动前可运行配置审计：

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_configuration
```

审计会检查弃用配置、敏感值误提交、生产模式认证、Redis、MinIO、报告和 RAGFlow 等组合约束。

## 测试与质量门禁

此运行交付副本不包含后端测试源码，不能直接执行 pytest。下列测试数字是开发工作区的历史验收记录；发布副本可执行配置审计、Python 编译检查、前端类型检查和生产构建。

开发工作区后端测试（本交付副本不包含测试源码）：

```powershell
Set-Location D:\uPil
.\.venv\Scripts\python.exe -m pytest -q
```

前端测试、类型检查和生产构建：

```powershell
Set-Location D:\uPil-deliverable\frontend
npm test
npm run typecheck
npm run build
npm run build:backend
```

Python 编译检查：

```powershell
Set-Location D:\uPil-deliverable
.\.venv\Scripts\python.exe -m compileall -q backend scripts
```

最近一次项目闭环验证结果：

- 后端：657 passed，8 skipped；
- 前端 Vitest：30 passed；
- `vue-tsc --noEmit` 通过；
- Vite 生产构建和 `build:backend` 通过；
- Python `compileall` 通过；
- 生产 Python 文件超过 800 行：0。

现有 7 条测试 warning 来自 FastAPI/Starlette 的弃用提示，不影响当前测试通过状态。

## 当前边界与技术取舍

- 项目可本地完整运行，但没有宣称已经生产上线。
- 仓库没有真实机构数据，初始化内容用于开发和测评。
- 认证层实现了 OIDC Resource Server 能力，但没有随仓库部署真实身份提供方。
- A2A/DSH 已从运行链路、配置和部署中移除；统一学情能力通过进程内 Service、Tool 和 LangGraph 节点复用。
- 情景向量长期记忆尚未启用；当前跨会话记忆使用 PostgreSQL 结构化偏好。
- 报告只交付 PDF，不提供 CSV 双产物。
- 不提供教师媒体工作台、运营后台、转化漏斗、综合教务、CRM、电话、短信或支付能力。
- 报课意向 Agent 是旁路分析能力，不会绕过用户授权保存联系方式。
- 飞书只接收低敏线索摘要并提醒顾问回 uPil 处理；线索池仍是唯一事实源，
  通知失败由 PostgreSQL Outbox 自动重试，不回滚已保存的线索。
- RAGFlow 负责知识检索，不负责 uPil 的身份授权、学情统计和业务状态。

## 文档索引

- [PROJECT_LOG](docs/PROJECT_LOG.md)：当前阶段实施记录、问题与验证结果。
- [TECH_DECISIONS](docs/TECH_DECISIONS.md)：核心技术选型和取舍。
- [PROJECT_HANDOFF](docs/PROJECT_HANDOFF.md)：项目交接和运行检查信息。
- [DEFENSE_INTERVIEW_QA](docs/DEFENSE_INTERVIEW_QA.md)：项目级答辩与面试问答。
- [真实场景多轮对话测评集](docs/测试与验收/项目收尾_真实场景多轮对话测评集.md)：课程、规则、报告、记忆和线索场景验收。
- [多 Agent 意图决策与上下文治理](docs/技术方案/项目收尾_多Agent意图决策与上下文治理优化.md)：路由、状态机和评测方案。
- [Agent 上下文与记忆治理](docs/技术方案/项目收尾_Agent上下文与记忆治理.md)：短期状态、长期偏好和隔离策略。
- [移除 A2A 与统一学情分析 Agent](docs/技术方案/项目收尾_移除A2A与统一学情分析Agent.md)：当前方案与历史方案的取舍。
- [Agent 生产代码模块化重构](docs/技术方案/项目收尾_Agent生产代码模块化重构与目录治理.md)：目录职责和依赖方向。
- [招生线索 Outbox 与飞书通知闭环](docs/技术方案/项目收尾_招生线索Outbox与飞书通知闭环.md)：事件、重试、幂等和隐私边界。

`docs/技术方案/阶段13-*` 及对应面试问答记录的是 A2A/DSH 历史探索过程。阅读这些文档时，应以本 README 和“项目收尾”系列文档描述的当前架构为准。

## License

本仓库当前未声明开源许可证，仅用于个人学习、作品展示和求职交流。

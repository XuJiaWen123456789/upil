# 项目收尾：Agent 生产代码模块化重构与目录治理

> 完成时间：2026-09-12
> 适用范围：`D:/uPil/backend/app` 生产 Python 代码
> 结论：本次只调整代码组织和依赖方向，不改变业务接口、鉴权规则、SSE 协议、报告产物语义或外部系统边界。

## 1. 背景

阶段 15-C 完成后，项目已经形成咨询、学情、报告和招生线索的业务闭环，但若干核心实现随着阶段累积集中在少数文件中：

- `backend/app/main.py` 同时承担应用装配、依赖工厂、路由、响应转换和 SSE 编排；
- `backend/app/graph.py` 同时包含 LangGraph State、路由、全部节点和图构建；
- `services/intent_recognition.py`、`services/report_tasks.py` 和 `tools/business_tools.py` 同时包含多类职责；
- A2A 协议映射、传输和响应校验集中在旧 integration 文件中；
- 大段 Prompt 与业务 Python 代码混排，难以单独审查和迭代。

单纯把文件按行数机械切开只能降低文件长度，不能减少耦合。因此本次以**职责、依赖方向和变更原因**作为主要拆分标准，以“生产 `.py` 文件不超过 800 行”作为结果门禁。

## 2. 目标与非目标

### 2.1 目标

1. 生产 Python 文件全部小于 800 行；
2. LangGraph 的状态契约、路由、节点和图构建分别维护；
3. 每个 LangGraph 节点单独一个文件；
4. Prompt 正文迁出业务 Python，动态 Schema 和白名单仍由代码安全注入；
5. Tool、Connector、Workflow、Service 和 HTTP API 的职责可从目录直接识别；
6. A2A 任务映射、传输、响应校验和禁用的 DSH 边界分离；
7. 报告任务的命令、查询、产物和完整性校验分离；
8. 保留旧导入路径、Uvicorn 入口、FastAPI dependency override 和测试 monkeypatch；
9. 通过专项、相关和全量测试证明业务行为未改变。

### 2.2 非目标

- 不新增业务功能，不调整 HTTP URL、请求体或响应体；
- 不改变家长/教师授权、报告幂等、单 PDF、MinIO 私有代理下载和招生线索规则；
- 不接入真实 DSH、真实 MinIO、真实 PostgreSQL、真实 OIDC、真实模型或机构数据；
- 不把已经暂缓的阶段 15-A-3 异步 worker、消息队列、保留期和对象对账夹带进本次重构；
- 按用户要求，本次暂不拆分测试文件；
- 不为了统一形式强行增加会隐藏事务边界的通用装饰器。

## 3. 对拆分规则的落地解释

### 3.1 单一职责优先于行数

800 行是风险报警线，不是架构边界。一个 300 行文件如果同时负责鉴权、数据库事务、网络重试和响应转换，仍然需要拆分；一个职责稳定、内聚清晰的 480 行领域服务，则不应为了数字好看被切成相互回调的碎片。

### 3.2 一个节点一个文件

对话图中每个节点都有独立输入假设、数据权限和降级路径，因此分别放在 `workflows/conversation/nodes`。图构建器只注册节点与边，不包含节点实现。

### 3.3 Prompt 资源化但不静态化动态契约

稳定的角色说明、安全约束和输出要求放入 `.txt`；Pydantic JSON Schema、课程白名单和当前可用意图集合仍在运行时由 Python 注入。这样既可独立审阅 Prompt，又不会出现 Prompt 枚举与代码契约漂移。

### 3.4 Tool 和 Connector 不参与路由

- Tool 只校验工具输入并执行确定性业务动作，不判断 LangGraph 下一跳；
- Connector 只完成协议映射、传输、超时/重试和响应校验，不决定用户是否有权访问学员或班级；
- Workflow 决定调用顺序，Service 维护领域状态与事务，HTTP Router 负责协议映射和认证入口。

### 3.5 横切逻辑按语义复用，不滥用装饰器

本次将稳定异常放入 `services/reporting/exceptions.py`，将 A2A 校验和安全失败放入 Connector，将 Tool 策略放入 `tools/policies.py`，将报告脱敏和完整性检查放入 `services/reporting/integrity.py`。

没有把所有异常、事务回滚和 HTTP 错误转换套进一个通用装饰器，因为不同路由的 404 防枚举、409 产物冲突、503 存储不可用和数据库回滚语义不同。强行装饰会隐藏事务提交点和安全差异。只有在未来出现三处以上完全同构的重试或脱敏流程时，再提取窄职责装饰器。

## 4. 重构前后结构

### 4.1 重构前的主要集中点

```text
backend/app/
├── main.py                         # 1717 行，HTTP 与工作流混合
├── graph.py                        # 560 行，State/路由/节点/构图混合
├── services/intent_recognition.py # 752 行
├── services/report_tasks.py       # 678 行
├── tools/business_tools.py        # 590 行
└── integrations/
    ├── a2a_client.py               # 342 行
    └── a2a_http_client.py          # 157 行
```

### 4.2 重构后的生产目录

```text
backend/app/
├── main.py                         # ASGI 与历史符号兼容门面
├── application.py                  # FastAPI 应用装配
├── graph.py                        # 旧 LangGraph 导入兼容门面
├── agents/
│   └── supervisor/                 # Supervisor 意图识别 Agent
├── api/
│   ├── compat.py                   # 历史 monkeypatch 兼容桥
│   ├── dependencies.py             # FastAPI 依赖工厂
│   ├── middleware.py               # HTTP 中间件
│   ├── runtime.py                  # 共享运行时对象
│   ├── static_files.py             # Vue SPA 静态托管
│   ├── presenters/                 # 领域对象到响应模型转换
│   └── routers/                    # 按业务资源拆分的 HTTP 路由
├── connectors/
│   └── a2a/                        # A2A 契约、映射、传输和校验
├── prompts/                        # Prompt 资源和安全加载器
├── services/
│   └── reporting/                  # 报告任务领域服务
├── tools/                          # 每个业务 Tool 独立实现
└── workflows/
    ├── chat_stream.py              # 一轮聊天和 SSE 编排
    └── conversation/               # LangGraph 对话工作流
        ├── contracts.py
        ├── routing.py
        ├── builder.py
        └── nodes/
```

## 5. 完整拆分文件清单与职责

### 5.1 Supervisor Agent

| 文件 | 职责 |
| --- | --- |
| `agents/supervisor/contracts.py` | 模型协议、识别来源和识别结果契约 |
| `agents/supervisor/constants.py` | 关键词、阈值、课程和属性白名单 |
| `agents/supervisor/prompt.py` | 注入动态 Schema、意图枚举和受控上下文 |
| `agents/supervisor/parsing.py` | 解析 LangChain/字典/JSON 等供应商返回 |
| `agents/supervisor/rules.py` | 确定性安全守卫与模型失败降级 |
| `agents/supervisor/validation.py` | 实体、属性、课程白名单和实时数据边界复核 |
| `agents/supervisor/service.py` | 串联 Prompt、模型、解析、规则和校验 |
| `agents/supervisor/__init__.py` | 新路径稳定公开接口 |

### 5.2 FastAPI HTTP 层

| 文件 | 职责 |
| --- | --- |
| `application.py` | 创建 FastAPI、注册 CORS、中间件、启动探测、Router 和 SPA |
| `api/compat.py` | 从 `backend.app.main` 读取历史测试替换点 |
| `api/dependencies.py` | 组装模型、A2A、MinIO 和会话存储依赖 |
| `api/middleware.py` | 生成/回传 request ID |
| `api/runtime.py` | 共享 Settings 与会话存储实例 |
| `api/static_files.py` | Vue history deep-link 回退和静态资源 404 规则 |
| `api/presenters/leads.py` | 线索领域对象响应映射 |
| `api/presenters/media.py` | 媒体对象响应映射 |
| `api/presenters/reports.py` | 报告任务与产物响应映射 |
| `api/routers/system.py` | 根接口、健康检查和 bootstrap/session |
| `api/routers/learning.py` | 家长学情和教师班级统计查询 |
| `api/routers/reports.py` | 家长/教师报告生成、列表、详情和代理下载 |
| `api/routers/leads.py` | 顾问线索列表、详情、领取、联系方式和跟进 |
| `api/routers/media.py` | 上传、双人复核和受控访问地址 |
| `api/routers/chat.py` | POST SSE 对话入口 |
| `api/routers/demo.py` | 仅本地演示身份接口 |

### 5.3 LangGraph 与聊天工作流

| 文件 | 职责 |
| --- | --- |
| `workflows/chat_stream.py` | 联系方式预脱敏、主链/招生旁路并行、图调用和 SSE 事件编排 |
| `workflows/conversation/contracts.py` | `ConversationState` 与路由类型 |
| `workflows/conversation/routing.py` | Supervisor 节点和条件边选择 |
| `workflows/conversation/builder.py` | 只注册节点、边并编译图 |
| `workflows/conversation/nodes/faq.py` | FAQ 节点 |
| `workflows/conversation/nodes/service_rules.py` | 服务规则节点 |
| `workflows/conversation/nodes/learning_summary.py` | 家长学情摘要节点 |
| `workflows/conversation/nodes/class_learning_summary.py` | 教师班级确定性统计节点 |
| `workflows/conversation/nodes/learning_report.py` | 家长/教师报告图入口节点 |
| `workflows/conversation/nodes/human_handoff.py` | 人工转接节点 |
| `workflows/conversation/nodes/clarification.py` | 澄清节点 |

### 5.4 Prompt

| 文件 | 职责 |
| --- | --- |
| `prompts/loader.py` | 限定文件名、UTF-8 读取和缓存 |
| `prompts/intent_router.txt` | Supervisor 角色、安全和 JSON 输出要求 |
| `prompts/enrollment_intent.txt` | 报课意向旁路 Agent 的有限证据约束 |
| `prompts/faq_fallback.txt` | FAQ 模型降级提示 |

### 5.5 业务 Tool

| 文件 | 职责 |
| --- | --- |
| `tools/contracts.py` | Tool 名称、状态、请求、结果和审计协议 |
| `tools/policies.py` | 每个 Tool 的角色、必填参数和副作用策略 |
| `tools/registry.py` | 注册、查找、校验、执行和最小审计 |
| `tools/learning_snapshot.py` | 学情快照 Tool |
| `tools/class_availability.py` | 班级名额 Tool |
| `tools/order_status.py` | 订单状态 Tool |
| `tools/human_ticket.py` | 人工工单 Tool |
| `tools/adapter_registry.py` | 注册真实业务系统适配器的窄入口 |

既有 `learning_tools.py` 和 `class_learning_tools.py` 继续承载学员/班级确定性数据库统计；它们职责内聚且远低于 800 行，本次不做无收益的机械拆分。

### 5.6 A2A Connector

| 文件 | 职责 |
| --- | --- |
| `connectors/a2a/contracts.py` | A2A 客户端协议与校验异常 |
| `connectors/a2a/task_builder.py` | 把权威快照映射为最小化、脱敏的 A2A Task |
| `connectors/a2a/validation.py` | 对不可信 A2A 结果做协议、关联、终态和内容复核 |
| `connectors/a2a/local.py` | 离线 Mock A2A 实现 |
| `connectors/a2a/http.py` | 本机白名单 HTTP、超时、有限重试和安全失败 |
| `connectors/a2a/dsh.py` | 默认拒绝真实 DSH 的显式禁用 Connector |

### 5.7 报告任务领域服务

| 文件 | 职责 |
| --- | --- |
| `services/reporting/constants.py` | 报告类型、状态和合法状态迁移 |
| `services/reporting/exceptions.py` | 稳定领域异常 |
| `services/reporting/commands.py` | 创建、领取、推进、完成和失败命令 |
| `services/reporting/queries.py` | 本人任务、班级任务、产物和下载查询 |
| `services/reporting/artifacts.py` | Artifact 基础写入 |
| `services/reporting/integrity.py` | 摘要、PDF 元数据、历史 Markdown 和错误脱敏校验 |
| `services/reporting/__init__.py` | 新路径稳定公开接口 |

## 6. 兼容门面

以下旧文件不再承载真实实现，只保留重导出或应用入口：

| 兼容文件 | 新实现位置 | 保留原因 |
| --- | --- | --- |
| `main.py` | `application.py`、`api/*`、`workflows/chat_stream.py` | 保留 `backend.app.main:app` 和测试替换点 |
| `graph.py` | `workflows/conversation/*` | 保留旧图、节点和构建函数导入 |
| `services/intent_recognition.py` | `agents/supervisor/*` | 保留评估脚本和测试导入 |
| `services/report_tasks.py` | `services/reporting/*` | 保留历史服务调用方 |
| `integrations/a2a_client.py` | `connectors/a2a/*` | 保留旧 A2A 公共符号 |
| `integrations/a2a_http_client.py` | `connectors/a2a/http.py` | 保留旧 HTTP 客户端路径 |
| `tools/business_tools.py` | `tools/contracts.py` 等具体模块 | 保留既有 Tool 测试和渐进迁移 |

兼容门面不是永久复制实现：新生产代码均直接导入新模块；旧门面只为外部调用和测试提供过渡路径。

## 7. 依赖方向

```text
main.py
  -> application.py
     -> api/routers
        -> workflows / services
           -> agents / tools / connectors
              -> integrations / database / external adapters

api/presenters <- services 的领域对象
prompts        <- agents 或有限的模型服务
```

约束如下：

1. `application.py` 不导入具体领域查询；
2. Router 不实现 LangGraph 节点；
3. Workflow 不拼接 A2A HTTP 请求；
4. Connector 不读取 JWT、不判断家长绑定或教师授课关系；
5. Tool 不控制 LangGraph 路由；
6. Agent 不直接持有 HTTP Request/Response；
7. 新生产模块不通过兼容门面反向依赖旧路径。

## 8. 关键兼容与安全处理

### 8.1 FastAPI dependency override

`Depends(...)` 对函数对象身份敏感。`main.py` 继续从 `api/dependencies.py` 重导出同一个函数对象，Router 也直接使用该对象，因此既有 `app.dependency_overrides[main_module.get_report_store]` 仍然有效。

### 8.2 monkeypatch

历史测试会替换 `backend.app.main.settings`、`plan_conversation`、`stream_faq_answer`、`inspect_report_pdf` 等符号。`api.compat.main_symbol()` 在运行时读取旧入口上的替换值，避免路由迁出后 monkeypatch 静默失效。这个桥只服务兼容，新代码不得把它当成普通依赖注入容器。

### 8.3 部署和前端

- Uvicorn 入口仍是 `backend.app.main:app`；
- CORS、request ID、非阻断依赖检查和 Router 注册顺序不变；
- Vue 静态目录仍由 FastAPI 同源托管；
- SPA deep-link 回退只处理无扩展名的非 API 路径，缺失资源仍返回 404。

### 8.4 数据与外部边界

- 报告仍是自然语言周期、单 PDF Artifact、私有 MinIO 和服务端鉴权代理下载；
- 每次查询/下载仍重新校验家长绑定或教师授课关系；
- 联系方式仍在进入模型前本地脱敏，同轮主动提供并明确授权后才加密保存；
- A2A 任务仍使用不可逆引用和聚合指标；
- `DisabledDSHConnector` 明确拒绝真实 DSH，阶段 15-A-3 仍为“生产增强，暂缓”。

## 9. 代码迁移指引

### 9.1 新代码导入方式

```python
# Supervisor
from backend.app.agents.supervisor import recognize_intent_detailed

# 报告任务领域服务
from backend.app.services.reporting import create_report_task

# A2A Connector
from backend.app.connectors.a2a import LocalMockA2AClient

# 具体 Tool
from backend.app.tools.learning_snapshot import execute_learning_snapshot

# LangGraph
from backend.app.workflows.conversation import conversation_graph
```

### 9.2 旧路径到新路径

```text
services.intent_recognition  -> agents.supervisor
services.report_tasks        -> services.reporting
integrations.a2a_client      -> connectors.a2a
integrations.a2a_http_client -> connectors.a2a.http
tools.business_tools         -> tools 下具体模块
graph.py 的真实实现          -> workflows.conversation
main.py 的路由和编排         -> api.routers + application.py + workflows.chat_stream
```

### 9.3 渐进迁移原则

1. 生产代码必须直接导入新路径；
2. 测试和外部脚本可暂时使用旧路径；
3. 删除兼容门面前，先用 `rg` 确认仓库与外部调用方不再引用；
4. 每删除一个门面都应单独提交并运行对应专项测试；
5. 不允许在新旧路径各保留一份实现。

## 10. 文件规模结果

- `backend/app/main.py`：1717 行降为 53 行；
- `backend/app/graph.py`：560 行降为 42 行；
- `services/intent_recognition.py`：752 行降为 58 行；
- `services/report_tasks.py`：678 行降为 36 行；
- `tools/business_tools.py`：590 行降为 56 行；
- 旧 A2A 两个文件分别降为 24 行和 6 行；
- 媒体工作台退出当前产品边界后，`backend/app` 共 114 个生产 Python 文件；
- 当前最大生产文件为 `services/enrollment_leads.py`，480 行；
- 超过 800 行的生产 Python 文件数量为 0。

行数使用 Python `splitlines()` 统计并包含中文注释和文档字符串。测试文件按本次范围未纳入拆分门禁。

## 11. 验证结果

专项测试：

```text
报告任务拆分专项：67 passed, 1 skipped, 4 warnings
Supervisor 拆分相关专项：77 passed, 1 skipped, 4 warnings
```

全量验证：

```text
419 passed, 8 skipped, 3 warnings
python -m compileall -q backend scripts tests：通过
git diff --check：通过
```

8 个跳过项仍来自 Windows WeasyPrint/Pango 环境和默认关闭的真实外部模型测试。最终全量 3 条 warning 属于 Starlette `BlockingPortal` 和 FastAPI `on_event` 生命周期弃用；部分专项命令另显示一条 pytest `cache_dir` 配置提示。它们都不是本次模块拆分引入的业务失败。

## 12. 后续维护门禁

1. 新生产 `.py` 文件建议控制在 500 行内，达到 650 行触发职责复核，800 行禁止合入；
2. 一个 LangGraph 节点一个文件，复杂节点优先下沉到领域 Service；
3. 新 Prompt 放入 `prompts`，不得在节点内新增大段角色提示；
4. 新 Tool 一工具一文件，不得把路由判断写入 Tool；
5. 新外部通信放入 Connector，不得在图节点中直接调用 `httpx`；
6. 兼容门面只允许重导出、入口装配和明确的兼容桥，禁止继续堆业务；
7. 测试文件拆分在后续独立治理，不与业务功能变更混合；
8. 真实 DSH、生产身份和真实外部依赖必须另立阶段并经过安全评审。

## 13. 结论

本次重构完成了从“按阶段向大文件叠加代码”到“按 Agent、HTTP、Workflow、Service、Tool、Connector 和 Prompt 分层维护”的转换。目录现在能直接表达能力边界，同时通过兼容门面保住部署和测试契约。全量回归证明当前是代码组织重构，而不是业务重写。

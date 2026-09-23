# uPil 项目续接说明

> 更新时间：2026-09-15
> 项目目录：`D:\uPil`
> 用途：新对话先读取本文、`git status --short` 和当前阶段源码，不重放旧聊天历史。

## 1. 当前状态

- 阶段 15-A-2：家长固定模板 PDF、MinIO 私有存储和鉴权代理下载已完成；
- 阶段 15-A-3：报告生命周期与异步可靠性标记为**生产增强，暂缓**；
- 阶段 15-B-1：Vue 3 双角色业务工作台已完成；
- 阶段 15-B-2：家长/教师报告显式入口、单 PDF 生成、查询和下载已完成；
- 阶段 15-C：对话式试听与报名线索闭环已完成，是当前最后一个业务功能阶段。
- 项目收尾模块化重构已完成：生产代码按 Agent、API、Workflow、Service、
  Tool、Connector 和 Prompt 分层，所有生产 Python 文件均小于 800 行。
- 项目收尾架构收敛已完成：当前运行、配置和部署不再包含 A2A/DSH。Supervisor
  将个人摘要、家长报告和教师班级报告统一路由到 `learning_analysis_agent`，内部
  仍由三个单职责处理器执行。
- 用户可见文案治理已完成：纯问候走确定性短路，前端和运行时回答不再显示
  “答辩、演示咨询、正式接入”等研发阶段措辞；知识库虚构数据声明仍保留，避免
  样例课程、价格和校区信息被误认为真实机构事实。
- 教师媒体工作台已完成退役：前后端入口、媒体权限、图片存储方法和 `MediaAsset`
  模型已删除；报告 PDF 的 MinIO 私有存储与鉴权代理下载不受影响。

本项目仍只保留 `parent` 和 `teacher` 两个业务角色。销售顾问老师属于 `teacher`，通过 `lead_followup` 权限进入线索工作台；没有运营端、运营账号、转化漏斗或 `lead_analytics`。

## 2. 阶段 15-C 业务链路

~~~text
家长正常咨询
  -> 本地提取手机号/邮箱并在进入模型前脱敏
  -> 主业务 Agent 正常回答
     与报课意向 Agent 旁路并行分析脱敏文本
  -> 确定性代码负责证据守卫、强度、分流、幂等和状态迁移
  -> 高意向且无已授权联系方式时返回后端固定询问
  -> 家长同一轮主动提供联系方式并明确授权后加密保存
  -> 销售顾问老师领取、按需查看联系方式并记录跟进
~~~

固定询问为：

> 如果您愿意由销售顾问老师继续确认试听或报名安排，请主动提供手机号或邮箱，并明确同意由销售顾问老师联系您。

“舞蹈启蒙班怎么试听？”是试听流程咨询，只进入线索池；“我想预约舞蹈启蒙班试听”是明确行动，进入顾问队列并由家长端自然提示下一步。家长端不展示“高/中/低意向”等内部销售术语；模型只能补充低风险语义证据，明确试听、报名、顾问联系、授权和拒绝必须由确定性规则直接命中。

## 3. 联系方式与权限边界

- 入口先本地提取联系方式是为了在模型前脱敏，不代表立即保存；
- 只有主动提供联系方式、同一轮明确授权，并且存在有效意向时才保存；
- 没有已有意向时，“同意 + 联系方式”不能凭空创建线索；
- 只提供联系方式但未授权时不保存，并要求同一轮重新提供及明确授权；
- Fernet 保存密文，HMAC-SHA-256 指纹只用于受控去重；
- 普通列表/详情不返回家长 ID、证据码、密文或明文；
- 顾问必须先显式领取，再通过专用 no-store 接口查看明文；
- 联系方式明文只保留在当前浏览器页面内存中；
- 拒绝或撤回会关闭当前会话线索并清除联系方式；
- 生产配置必须注入有效 Fernet 密钥和至少 32 字节 HMAC 密钥。

## 4. 当前生产代码入口

- `backend/app/main.py`：ASGI 部署入口和历史测试符号兼容门面；
- `backend/app/application.py`：FastAPI 应用装配；
- `backend/app/api/routers/`：system、learning、reports、leads、chat 和 demo 路由；
- `backend/app/workflows/chat_stream.py`：单轮聊天、SSE 和招生旁路编排；
- `backend/app/workflows/conversation/`：LangGraph State、路由、builder 和独立节点；
- `backend/app/agents/supervisor/`：Supervisor Prompt、解析、规则、校验和识别编排；
- `backend/app/services/reporting/`：报告任务命令、查询、产物和完整性服务；
- `backend/app/integrations/`：MinIO、RAGFlow 等现行外部基础设施适配；
- `backend/app/tools/`：业务 Tool 契约、策略、注册表和单工具实现；
- `backend/app/prompts/`：Prompt 文本资源与安全加载器。

`graph.py`、`services/intent_recognition.py`、`services/report_tasks.py` 和
`tools/business_tools.py` 只保留兼容重导出。新增生产代码应直接导入
新路径，不应继续向兼容门面堆业务。详细清单和迁移方法见：
`docs/技术方案/项目收尾_Agent生产代码模块化重构与目录治理.md`。

## 5. 15-C 关键实现

- `backend/app/services/enrollment_intent.py`：严格意向证据契约、确定性回退和模型低风险补充；
- `backend/app/services/enrollment_leads.py`：强度、分流、幂等、授权和跟进状态机；
- `backend/app/services/lead_contacts.py`：联系方式提取、脱敏、Fernet 加密和 HMAC 指纹；
- `backend/app/workflows/chat_stream.py`：旁路并行和 `lead` SSE 事件；
- `backend/app/api/routers/leads.py`：顾问 HTTP API；
- `backend/app/models.py`：`EnrollmentLead` 与 `LeadFollowUp`；
- `infra/production/migrations/005_add_enrollment_leads.sql`：生产增量表、约束、索引和旧运营残留清理；
- `frontend/src/views/ChatView.vue`：家长固定授权询问与结果卡片；
- `frontend/src/views/LeadWorkspaceView.vue`：顾问队列、线索池、领取、联系方式和跟进；
- `frontend/src/api/leads.ts`：线索 API 客户端；
- `tests/test_enrollment_intent.py`、`test_lead_contacts.py`、`test_enrollment_leads.py`、`test_lead_api.py`：专项回归。

API：

~~~text
GET  /api/v1/leads
GET  /api/v1/leads/{lead_id}
GET  /api/v1/leads/{lead_id}/contact
POST /api/v1/leads/{lead_id}/follow-ups
~~~

Demo 身份：家长 `P1001`、普通教师 `T1001`、销售顾问老师 `T1004`。生产迁移不创建演示账号。

## 6. 教师媒体工作台退役边界

- 不再提供 `/teacher/media` 页面和 `/api/v1/media/*` 接口；
- 不再支持图片上传、双人审核、图片读取或预签名 URL；
- 认证权限白名单只保留 `lead_followup`，历史媒体权限不会进入 `AccessContext`；
- 生产环境执行 `006_retire_teacher_media_workspace.sql` 删除旧权限和业务表；
- 历史 MinIO 图片对象由运维独立盘点，不在数据库迁移中跨系统删除；
- `SourceReference.media_asset_id` 仅作为 RAGFlow 外部来源协议字段保留；
- `MinioMediaStore` 是报告服务仍在使用的历史兼容类名，当前只实现 PDF 报告方法。

## 7. 报告链路保留状态

家长和教师可从聊天意图或页面按钮进入相同的报告执行服务。页面只提交自然语言周期，默认“最近30天”；新任务仅保存一个 PDF Artifact。本地固定模板生成的 Markdown 只作为内存中间态。PDF 使用 `markdown-it-py + WeasyPrint + pypdf`，保存至私有 MinIO 桶并由 FastAPI 动态鉴权代理下载。教师没有 CSV 或 Markdown 新产物。

报告接口：

~~~text
POST /api/v1/learners/{learner_id}/reports
GET  /api/v1/reports
POST /api/v1/classes/{class_id}/reports
GET  /api/v1/classes/{class_id}/reports
GET  /api/v1/reports/{task_id}
GET  /api/v1/reports/{task_id}/download
~~~

## 8. 最终验证基线

- 15-C 原有四组专项：`33 passed`；
- 本轮课程多轮、意向和线索回归专项：`67 passed, 3 warnings`；
- 线索 API 专项：`10 passed`；
- 报告专项：`70 passed, 7 skipped, 3 warnings`；
- 相关 API、线索、班级统计、staging 和 production 回归：`100 passed, 3 warnings`；
- Windows 后端当前全量：`477 passed, 8 skipped, 3 warnings`；
- frontend typecheck：通过；
- frontend Vitest：`12 passed`；
- frontend 普通构建与 `build:backend`：通过；
- Python `compileall backend scripts tests`：通过。
- 媒体退役专项（storage/config/auth/database/API）：`129 passed`；
- integrations 相关回归：`24 passed`；
- 统一 Seed 与招生线索测试夹具兼容回归：`21 passed`；
- 前端退役回归：typecheck、`12 passed`、普通构建与 `build:backend` 均通过，
  后端静态资源中不存在 `MediaWorkspaceView-*.js`。

Windows 跳过项仍来自本机 WeasyPrint/Pango 依赖及默认关闭的真实外部模型测试。
最终全量的 3 条 warning 属于 Starlette `BlockingPortal` 和 FastAPI `on_event`
等既有弃用提示；部分专项命令另显示一条 pytest `cache_dir` 配置提示。
阶段 15-B-2 已在 Linux `report-tests` 验证
真实 PDF 链路 `24 passed`。当前生产文件规模扫描结果为 101 个 `.py`、最大 523 行、
超过 800 行为 0；`compileall -q backend scripts tests` 和 `git diff --check` 通过。

## 9. 外部系统边界

当前架构已移除 A2A/DSH，不接 CRM、电话、短信或支付。真实 MinIO、OIDC、
PostgreSQL、RAGFlow、模型和教育机构数据仍需按部署环境联调；当前完成的是基于
SQLite、适配器和 Demo 身份的本地可验证业务闭环，不得表述为生产招生平台或
大规模生产就绪。

## 10. 文档

- `docs/技术方案/阶段15-C_对话式试听与报名线索闭环.md`；
- `docs/面试问答/阶段15-C_多Agent意向识别与招生线索闭环.md`；
- `docs/技术方案/阶段15-B-2_教师班级学情报告闭环.md`；
- `docs/面试问答/阶段15-B-2_教师班级学情报告闭环.md`；
- `docs/技术方案/项目收尾_Agent生产代码模块化重构与目录治理.md`；
- `docs/面试问答/项目收尾_Agent模块拆分与兼容迁移.md`；
- `docs/技术方案/项目收尾_教师媒体工作台下线与核心业务边界收缩.md`；
- `docs/技术方案/项目收尾_移除A2A与统一学情分析Agent.md`；
- `docs/面试问答/项目收尾_为什么移除A2A并统一学情分析Agent.md`；
- `docs/PROJECT_LOG.md`、`docs/TECH_DECISIONS.md`、`docs/DEFENSE_INTERVIEW_QA.md`。

## 11. 续接与验证规则

不得回退工作区已有改动，禁止执行：

~~~text
git reset --hard
git checkout .
git clean -fd
~~~

自动化测试不得访问真实外部服务。复核命令：

~~~powershell
.venv\Scripts\python.exe -m pytest tests/test_enrollment_intent.py tests/test_lead_contacts.py tests/test_enrollment_leads.py tests/test_lead_api.py -q
Set-Location frontend
npm run typecheck
npm run test
npm run build
npm run build:backend
Set-Location ..
.venv\Scripts\python.exe -m compileall backend scripts tests
.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
~~~

若继续项目，优先做发布准备、真实身份和外部依赖联调，或有明确容量目标后的生产增强；不要再无边界扩张成运营、财务、排课或通用教务后台。

## 12. 上下文与记忆治理收尾

当前已完成对话上下文与记忆治理的第一版闭环：

- `backend/app/context/`：不可变共享 Envelope、Agent 视图和 reducer；
- `backend/app/memory/conversation/`：内存/Redis 工作记忆、最近窗口和滚动摘要；
- `backend/app/memory/structured/`：显式/高置信度准入、字段白名单、版本化事实、删除恢复；
- `backend/app/memory/episodic/`：可替换的情景记忆协议，默认 Noop；
- `backend/app/memory/chat_memory.py`：聊天读取、作用域解析和可选写入边界；
- `infra/production/migrations/007_add_agent_memory.sql`：长期记忆生产表迁移；
- `tests/test_memory_policies.py`、`test_redis_conversation_store.py`、
  `test_structured_memory.py`、`test_episodic_memory.py`、`test_context_envelope.py`、
  `test_context_reducer.py`、`test_chat_memory_integration.py`：本轮专项回归。

业务边界：联系方式、Token、密码、银行卡、动态课时、出勤、名额和报告状态不进入
共享上下文摘要或长期记忆。长期记忆除显式“请记住”外，也允许对课程兴趣、上课时间
偏好和孩子昵称做高置信度稳定陈述识别；不确定、否定、临时表达以及非白名单字段仍拒绝。
自主判断不能覆盖已有冲突值，显式修改才生成新版本。情景记忆未配置嵌入模型时保持关闭，
不影响主聊天。短期上下文按会话、租户、用户、角色和学员作用域隔离；Agent
只读 projector 视图并通过 reducer 白名单返回结果。

本轮验证基线：专项 `26 passed`；后端全量 `419 passed, 8 skipped, 3 warnings`；
生产 Python 文件超过 800 行为 `0`。完整方案和面试口径分别见：

- `docs/技术方案/项目收尾_Agent上下文与记忆治理.md`；
- `docs/面试问答/项目收尾_Agent上下文与记忆治理.md`。

## 13. Redis 短期会话启用状态

- 当前本地 `.env` 已选择 Redis，会话服务是独立 `upil-redis`，不复用 RAGFlow Redis；
- 本机 API 地址为 `localhost:16380`，staging 容器地址为 `upil-redis:6379`；
- Redis 密码只存在于被 Git 忽略的环境文件，文档和示例不得写入真实值；
- staging Dockerfile 已安装 `.[storage,memory]`，根 Compose 提供密码鉴权、AOF 和健康检查；
- 应用启动工厂会先 Ping，Redis 故障不静默退回进程内存；
- `scripts/check_infrastructure.ps1` 已纳入 Redis 容器、端口和鉴权 Ping；
- 本机容器、Python 客户端、API 重启恢复、工厂和全量回归已通过；本轮记忆专项
  `30 passed`，后端全量 `424 passed, 8 skipped, 3 warnings`；生产 Redis 高可用、容量和
  故障转移仍属于部署联调，不宣称已完成。

## 14. 结构化长期记忆已启用

- 本地、staging 和 production 环境模板已显式设置 `MEMORY_WRITE_ENABLED=true`；
- `Settings` 的代码默认值仍为 false，避免单元测试和离线工具在未执行迁移时隐式写库；
- 本机 PostgreSQL 已执行 `007_add_agent_memory.sql`，真实表写入与跨会话读取冒烟验证通过；
- 新会话按租户、用户、角色和学员范围读取 active 偏好，不依赖旧 `conversation_id`；
- 自主判断只允许新增或同值去重，冲突安全跳过；显式修改允许生成新版本；
- FAQ 只在课程推荐和上课时间问题中使用安全偏好投影，不影响动态业务事实；
- 教师端不自动写入家长孩子偏好，联系方式和完整聊天原文不进入本表。
- 最新验证：相关专项与 API 回归 `83 passed, 3 warnings`，后端全量
  `447 passed, 8 skipped, 3 warnings`，compileall 与 diff check 通过，生产 Python
  文件超过 800 行为 0（当前最大 480 行）。


## 15. 最新交接：跨课程多轮咨询与联系方式承接修复

### 当前已完成

- “12岁，没有编程基础”会直接使用零基础事实推荐少儿编程基础班，不再追问 Scratch；
- 已确认课程后，年龄、编程基础和上课时段通过 Redis/会话状态复用；服务规则插话后，“回到刚才那个班/那个课程”可以恢复原课程实体；
- 明确试听或报名后生成 `awaiting_contact_consent` 线索；后续合法手机号/邮箱和明确授权命中同一条线索后进入 `ready_for_followup`，不会退回欢迎语；跨会话复用已授权活动线索后，再次提供或更正联系方式也继续走专用补全路由；
- 联系方式在 Supervisor、旁路 Agent、FAQ/RAGFlow 和长期记忆之前脱敏；数据库仅保存密文、指纹和掩码，SSE 不输出明文；
- “工作日晚上有具体班吗”“现在有名额吗”“有空位吗”“目前还能报名吗”“这个时间有班吗”等表达统一进入实时人工确认，不由静态 FAQ 推断；
- 编程、舞蹈、美术、音乐四条完整 HTTP 多轮链路已回放通过。

### 关键实现位置

- 实时可用性确定性识别：`backend/app/agents/supervisor/rules.py`；
- 实时数据关键词和课程白名单：`backend/app/agents/supervisor/constants.py`；
- 课程年龄/基础/时段/试听确定性承接：`backend/app/services/course_consultation.py`；
- 联系方式提取与脱敏：`backend/app/services/lead_contacts.py`；
- 等待授权线索补全：`backend/app/services/enrollment_contact_follow_up.py`；
- 聊天前置路由与状态写回：`backend/app/workflows/chat_stream.py`、`backend/app/services/conversation_state.py`；
- 统一实时人工回答：`backend/app/workflows/conversation/nodes/human_handoff.py`。

### 最新验证

- 整合专项：`140 passed, 3 warnings`；
- API 与记忆集成：`58 passed, 3 warnings`；
- 联系方式与跨会话线索专项：`28 passed, 3 warnings`；
- 后端全量：`514 passed, 8 skipped, 3 warnings`；
- 前端 typecheck、`12 passed`、普通构建与 `build:backend` 均通过；
- `compileall` 与 `git diff --check` 通过。
- 本机最新服务健康检查为 `GET /api/v1/health`；根路径 `/health` 会被前端 SPA 回退接管，不是后端健康接口。
- 家长提交手机号或邮箱后，聊天页会在请求完成时擦除用户消息原文，只保留“已提交联系方式（原文已隐藏）”和后端返回的脱敏值；对应前端回归在 `frontend/src/views/ChatView.spec.ts`。
- 销售顾问老师的能力画像与授课教师互斥：顾问只获得 `lead_followup`，不获得 `class_summary_read`；因此不显示班级统计页面，直接调用班级统计/报告接口也会被后端拒绝。

### 仍需注意

- 本地回归使用内存 SQLite、模型桩和受控会话存储，不代表已接入真实排课/名额系统；
- 不得把“销售顾问老师已确认”写成已经预约成功；
- 不得恢复联系方式明文进入 Prompt、日志、长期记忆或普通 SSE；
- 不得让联系方式明文长期留在聊天页 DOM；前端只负责隐藏展示，授权、校验和入库仍由后端统一判断；
- 不得为销售顾问重新下发 `class_summary_read`；顾问与授课教师虽然共用 teacher 认证角色，但必须按 capability 保持最小权限隔离；
- 继续工作时优先运行全量后再改动，不要回退工作区已有改动。

## 16. 本地多用户身份切换

- 页面身份切换器按业务画像分组，提供家长P1001～P1003、教师T1001～T1002、销售顾问T1004和T1006；
- 页面编号与数据库业务账号保持一致，不再维护一套容易混淆的自定义短编号；
- 第二位顾问 `T1006` 只拥有 `lead_followup`，不能访问班级统计；
- 切换身份会重新挂载当前业务页面，防止前一个身份的前端状态残留；后端数据访问仍按用户、角色、绑定关系、授课关系和线索归属独立鉴权；
- 该切换器仅在 `demo_mode=true` 的本地认证模式显示，不能作为生产登录方案。
- 本轮验证：前端 `16 passed`，数据库与会话专项 `57 passed`，后端全量
  `516 passed, 8 skipped, 3 warnings`；本机 PostgreSQL 已幂等补入第二位顾问，
  7 个身份的会话接口与服务端静态页面资源均已实际验证。

## 17. 家长实时学情与历史报告入口修复

- “我想查一下我孩子的学习情况”“查看阶段反馈”“查看孩子最近表现”等表达固定进入 `learning_summary`，直接读取授权数据库，不再进入 FAQ/RAGFlow；
- 个人学情回答包含课时、消课、出勤、缺勤、阶段、完成度、优势和下一步重点，不展示内部 `learner_id` 和教师内部 `teacher_note`；
- 家长只有一个有效绑定孩子时自动解析；多个孩子时不按数据库顺序猜测，必须在问题中点名孩子，提示只展示当前家长可访问的孩子姓名；
- 显式越权、资源不存在和绑定失效使用统一安全提示，避免通过错误文案枚举学员；停用学员不参与候选；
- “查看学习报告”“历史学情报告”固定进入 `report_history`，只返回 `/parent/reports` 站内入口，不创建 `ReportTask`、不生成 PDF；
- “生成学习报告”“帮我做一份学情报告”继续进入现有 `learning_report`，与历史查看保持副作用隔离；
- 生成报告未说明周期时进入报告专用澄清，提示家长直接回复“本月”“上个月”或
  “最近30天”；下一轮自然语言周期通过 `pending_intent` 恢复生成流程，不要求填写
  开始日期和结束日期；
- 前端只渲染后端签发且路径等于 `/parent/reports` 的按钮，外链、管理路径和脚本 URL 均不执行；
- 最新验证：核心专项 `135 passed`，相关多轮回归 `162 passed`，前端聊天测试
  `5 passed`，后端全量 `534 passed, 8 skipped, 3 warnings`；前端 typecheck、
  compileall 和 diff check 均通过；生产 Python 文件超过 800 行为 0。

## 18. 多 Agent 意图决策与上下文治理最新状态

- 新增 `backend/app/dialogue/` 统一仲裁层，核心契约为不可变 `TurnDecision`；
- Supervisor 结果、确定性实体/槽位、pending 和 UNKNOWN 分类只仲裁一次，主业务 Agent
  与报课意向旁路通过 `ContextEnvelope` 读取同一决策，不共享可写大字典；
- 固定优先级为：身份/隐私 > 取消 > pending 补全 > 纠错/切换 > 实体槽位 >
  确定性守卫 > 模型意图 > 冲突仲裁 > 招生旁路 > UNKNOWN；
- 纯问候走 `small_talk`，股票等域外问题走 `out_of_scope`，无上文“这个课程”走
  专用澄清，以上路径不访问 FAQ/RAGFlow；
- “生成报告 → 谢谢 → 上个月”会保留并恢复 pending；明确“不用了”会清除；
- “这个班多少钱，我还想预约试听”以 `course_detail` 为主意图、`trial_booking` 为
  旁路意图，不再由试听覆盖价格主回答；
- 报告和班级统计只接受已确认日期/班级槽位，模型推断值不能直接驱动工具；
- SSE complete 增加主意图、旁路意图和 UNKNOWN 白名单枚举，不包含正文、槽位值、
  学员标识或联系方式；
- 报告幂等范围已忽略 `period_type` 展示差异：同一日期范围用“上个月”或显式日期
  表达时复用同一任务和 PDF。

最新验证：

- 专项 `140 passed, 3 warnings`；相关回归 `96 passed, 3 warnings`；
- 后端全量 `553 passed, 8 skipped, 3 warnings`；
- 前端 typecheck、Vitest `20 passed`、普通构建和 `build:backend` 通过；
- compileall、diff check 通过；生产 Python 最大 599 行，超过 800 行为 0。

详细文档：

- `docs/技术方案/项目收尾_多Agent意图决策与上下文治理优化.md`；
- `docs/面试问答/项目收尾_多Agent意图仲裁与会话状态机.md`。

继续修改时不要重新引入 A2A，不要把完整对话无筛选写入向量数据库，也不要允许
模型推断槽位绕过 confirmed 门禁。当前工作区包含多个前置阶段未提交改动，禁止清理或回退。

## 23. 配置治理与外部依赖深度健康检查

- 配置治理入口位于 `backend/app/configuration/` 和 `scripts/audit_configuration.py`。受管环境必须使用 Redis 会话并开启结构化长期记忆；PDF 开启时 MinIO 必须完整可用；RAGFlow 必须同时配置公开咨询与服务规则两个 Assistant。
- 已删除不再生效的运行变量：`MEDIA_MAX_BYTES`、`MINIO_BUCKET`、`MINIO_PRESIGNED_URL_SECONDS`、`RAGFLOW_CHAT_ID`。不要恢复单 Chat ID 兼容逻辑，也不要重新引入 A2A/DSH。
- `/api/v1/health/dependencies` 是快速浅探针；`/api/v1/health/dependencies/deep` 会真实调用两个 RAGFlow Assistant。深探针可能触发模型冷启动，只用于部署验收和故障诊断，不应配置为高频负载均衡探针。
- RAGFlow 页面 HTTP 200 不代表 RAG 可用。查询链路还依赖宿主机 Ollama、`bge-m3:latest`、容器网络、检索索引和回答模型。Windows 登录自启必须执行 `D:\ollama\ollama.exe serve`，当前监听 11528；基础设施脚本覆盖完整链路。
- 根 `.env` 允许存在 Docker Compose、RAGFlow 等同仓工具使用的额外变量，不能直接通过 Pydantic `extra=forbid` 拒绝整个文件；应用已知字段由 Settings 校验，废弃字段和跨组件关系由独立审计器处理。
- 本轮已真实验证 FAQ、服务规则、长期偏好、PDF、MinIO 和家长越权 404，并在结束后精确回收 P1008 临时数据。当前 P1008 的临时 conversations/memories/reports 均为 0。
- `scripts/check_infrastructure.ps1` 保存为 UTF-8 BOM，以支持 Windows PowerShell 5.1 解析中文字符串；后续编辑不要无意改回无 BOM UTF-8。

## 19. 第三阶段 Router 模型与评测优化最新状态

- `get_intent_model()` 已固定 `temperature=0`；可用 `LLM_ROUTER_MODEL` 单独配置
  Supervisor，未配置时复用 `LLM_MODEL`。当前本地继续复用 `deepseek-chat` 即可；
- `backend/app/prompts/intent_router_examples.txt` 已加入高价值混淆 few-shot，Prompt
  仍从运行时代码注入 Schema、意图、实体、课程和班级白名单；
- `scripts/evaluate_real_intent_model.py` 已输出主意图混淆矩阵、逐类指标及实体、
  实时数据标记和来源准确率。该脚本只有人工显式运行才访问真实模型；
- `scripts/evaluate_multiturn_state.py` 提供完全离线的状态评测，当前覆盖 12 组、
  20 轮，路由、主/旁路意图、UNKNOWN、槽位值/来源/确认、pending 状态及
  建立/保留/恢复/取消均为 `100%`；
- `backend/app/observability/decision_events.py` 与聊天编排已输出白名单
  `dialogue_decision` JSON。日志不包含消息正文、conversation_id、用户/学员/班级
  内部 ID、手机号、邮箱、Token、Prompt、模型原始输出或 CoT；
- 安全回退原因只允许 `model_not_configured`、
  `invalid_or_timed_out_model_output`、`model_provider_error` 等低基数枚举；
- 本轮评测发现并修复“生成上个月的学情报告”确定性守卫漏识别。查看已有报告
  仍走 `report_history`，不会被组合规则错误创建报告任务。

本阶段已验证：专项 `51 passed, 3 warnings`；相关回归 `181 passed, 3 warnings`；
后端全量 `567 passed, 8 skipped, 3 warnings in 59.17s`。`compileall -q backend scripts tests`
与 `git diff --check` 均通过；diff check 只有 LF/CRLF 转换提示，没有空白错误。生产
Python 文件超过 800 行为 0，当前最大文件为
`backend/app/services/conversation_state.py`，共 603 行。3 条 warning 仍为既有
FastAPI/Starlette 弃用提示，不是本阶段业务失败。

续接时可用以下命令分别执行离线与真实模型评测：

~~~powershell
.venv\Scripts\python.exe scripts\evaluate_multiturn_state.py
# 下一条会调用当前 .env 配置的真实 Router，只有需要模型测评时才执行：
.venv\Scripts\python.exe scripts\evaluate_real_intent_model.py
~~~
## 20. 会话历史 MVP 与 Redis 过期恢复

当前已按收尾范围完成：会话列表、继续、新建、重命名、删除、主体隔离、敏感信息脱敏和 Redis 过期恢复。前端入口位于聊天页左侧会话历史栏；后端接口为：

~~~text
POST   /api/v1/conversations
GET    /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}/messages
PATCH  /api/v1/conversations/{conversation_id}
DELETE /api/v1/conversations/{conversation_id}
~~~

数据职责：PostgreSQL 保存会话目录、脱敏消息和 `ConversationMemory` 白名单快照；Redis 保存短期高频状态。Redis 键以租户、用户、角色和会话共同隔离。聊天 SSE 建立前必须完成会话所有权校验和 Redis 恢复，不能先返回 200 后再发现越权或失忆。Redis 为空时只恢复数据库快照和有限最近消息；Redis 已有新状态时数据库旧快照不得覆盖。

安全边界：联系方式、Token、内部地址不能明文进入消息表；删除会话不级联招生线索、报告或结构化长期偏好。邮箱正则边界必须继续使用 ASCII 字符集合，不能改回 Unicode `\w`。服务规则流必须继续把每个 chunk 加入 `answer_parts`，否则刷新后 assistant 历史会为空。

本机已执行 `infra/production/migrations/008_add_chat_conversations.sql`，并重建 staging API。最新结果：专项 `17 passed`，相关回归 `18 passed, 3 warnings`，前端 `26 passed`，后端全量 `586 passed, 8 skipped, 3 warnings`；真实 staging 创建/列表/重命名/删除、服务规则持久化和 Redis 清空后 PostgreSQL 恢复冒烟均通过。

本阶段明确不做搜索、置顶、分享、附件、会话分支和完整聊天向量化。后续修改不得把 PostgreSQL 历史消息直接全量注入 Prompt，也不得让前端提交的用户 ID 代替认证上下文成为所有权依据。

## 21. 本地多身份聊天 404 修复

- 2026-09-16 已修复 P1002、P1003、教师和销售顾问在自己的会话中聊天返回
  `404 会话不存在` 的问题；
- 根因是前端 SSE 身份位于查询参数，而聊天路由此前只读取请求体身份，导致聊天认证
  退回默认 P1001；会话目录仍按当前身份创建，所以正确的所有权校验产生 404；
- `backend/app/api/routers/chat.py` 现在与其他业务接口一致读取查询参数，并兼容旧请求体：
  查询参数优先，请求体回退；trusted headers/OIDC 继续忽略客户端 Demo 身份；
- 不得为了多身份可用性移除或放宽会话所有权校验。跨用户、跨角色和跨租户访问仍应
  返回统一 404；
- 回归覆盖 P1002、P1003、T1001、T1002、T1004、T1006，自有会话聊天和历史读取
  均为 200，其他主体访问仍为 404；
- 最新验证：相关后端 `82 passed, 3 warnings`，前端 `27 passed`、typecheck 通过，
  后端全量 `599 passed, 8 skipped, 3 warnings`；
- staging `18000` 与本地页面 `8000` 已分别完成 7 个身份的真实创建、聊天、历史读取
  冒烟，跨主体读取继续为 404；本地 8000 旧进程已重启到当前代码。后续若新增路由
  或修改非 reload 服务代码，必须重启对应 Uvicorn/容器，避免“静态资源已更新但
  后端路由仍是旧版本”的假故障。

## 22. 课程装备、外部知识降级与拒绝联系最新状态

- 稳定课程装备事实已从 FAQ/RAGFlow 中前移到
  `backend/app/services/course_equipment.py`，当前覆盖 9 个正式课程；
- `equipment` 已成为受控课程属性。“它需要自己买乐器吗”会继承童声合唱班并直接
  回答机构提供课堂乐器，不再依赖 RAGFlow 的瞬时可用性；
- FAQ 和服务规则外部调用必须继续保留最外层异常收敛。知识服务失败时允许返回安全
  离线说明，但不能让 SSE 中断成 503，也不能泄露供应商异常、URL 或 Token；
- “名额 + 费用”属于复合实时咨询，两个请求属性必须同时保留。系统说明当前不能
  直接确认实时名额，费用也需结合校区、班型和当期收费核实，不得只回答其中一项；
- “不用联系我”等明确否定优先于“联系我”子串和联系方式补全 pending。该轮应走
  `small_talk`，同时撤回活动线索、清空联系方式密文并停止显示授权卡；
- 最新验证：专项 `121 passed`，相关回归 `154 passed`，后端全量
  `613 passed, 8 skipped, 3 warnings`。生产 Python 文件仍全部低于 800 行；本轮新增
  装备目录独立成文件，没有继续膨胀课程咨询模块。

## 23. 结构化长期偏好 staging 开关与读取边界

- staging 页面曾出现“请记住……”无法保存，根因不是迁移或 PostgreSQL，而是本机
  私有 infra/staging/.env.staging 遗漏 MEMORY_WRITE_ENABLED=true；该文件已修复，
  容器运行时已确认开关开启；
- 当前允许家长保存三个低敏感字段：course_interest、
  class_time_preference、child_nickname。显式写入成功才回复“我记住了”，普通
  稳定陈述可按高置信度自主写入；联系方式、动态学情和临时时间继续拒绝；
- 显式命令识别必须保持“句首祈使表达”边界，不得退回任意 in 子串匹配。
  “请根据以前记住的偏好推荐课程”是读取请求，不能进入 memory 写入路由；
- 用户明确要求根据已保存偏好推荐时，先使用 PostgreSQL 安全投影生成确定性回答，
  不允许 RAGFlow 旧客服话术否定已经启用的系统能力；实时班次、价格和名额仍需
  业务系统或销售顾问确认；
- 最新验证：记忆/上下文专项 86 passed，API、多轮相关回归
  98 passed, 3 warnings，staging 依赖探针全部为 ok。

## 24. 字段级长期记忆回忆

- `course_interest`、`class_time_preference`、`child_nickname` 除了能辅助推荐，现在也支持新会话中的自然语言直接回忆；
- 示例：“你还记得孩子的小名吗？”应由 PostgreSQL 安全投影确定性回答“记得，孩子的小名叫果果。”，不得进入 UNKNOWN 通用澄清或访问 RAGFlow；
- 读取发生在 Supervisor 规划之后、路由执行之前，因为初始规划可能仍把自然回忆问句判为 `clarification`；只有固定字段和固定读取短语可以覆盖为 `faq`，其他 UNKNOWN 行为保持不变；
- 读取问句不是写入命令，不能增加记忆版本。长期记忆继续按租户、可信用户、角色和可选学员隔离，P1002 不得读取 P1001 的昵称；
- 最新验证为 API/上下文 `83 passed, 3 warnings`，记忆、会话和多轮相关回归 `104 passed`。

## 25. 最终工作区归档基线

- 2026-09-16 已将此前尚未提交的多轮意图仲裁、会话历史、Redis 恢复、结构化长期
  偏好、学情与报告入口、招生线索、销售顾问权限、配置治理、评测工具、前端工作台、
  数据库迁移和项目文档统一纳入版本控制；
- 本次提交前后端全量测试为 `643 passed, 8 skipped, 3 warnings`，前端 Vitest 为
  `8 files passed, 30 tests passed`，`build:backend`、配置审计和 compileall 均通过；
- 生产 Python 文件没有超过 800 行，当前扫描最大文件为
  `backend/app/services/conversation_state.py`，560 行；
- `.codex_tmp/`、`data/runtime-checks/`、本地数据库、日志、下载 PDF 和 RAGFlow 上游源码
  副本均为本机运行或检查产物，不进入 Git；
- 后续答辩材料必须以本节及 `PROJECT_LOG` 的最终归档记录为事实基线，不得把已移除的
  A2A/DSH、未接入的 CRM/支付/短信、真实 OIDC、情景向量记忆或阶段 15-A-3 生产补偿
  写成已完成功能。

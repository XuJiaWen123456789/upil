# uPil 多 Agent 意图决策与上下文治理优化

> 日期：2026-09-15
> 范围：对话理解、主/旁路意图、槽位确认、pending 状态机、多 Agent 共享上下文、SSE 可观测性
> 原则：不重新引入 A2A，不改变报告、线索、Redis 和 PostgreSQL 长期记忆的既有业务边界

## 1. 背景与问题

项目原有 Supervisor 已能识别课程咨询、服务规则、学情、报告和试听报名等意图，
但真实多轮对话暴露出一个典型问题：**单轮分类结果不能代替完整对话决策**。

优化前的主要风险如下：

1. `UNKNOWN` 缺少细分，纯问候、信息不足、域外问题都可能进入 FAQ/RAGFlow；
2. 礼貌插话可能清除尚未完成的报告周期补全流程；
3. “这个班多少钱，我还想预约试听”中的试听动作可能覆盖价格主问题；
4. 模型推断的周期、班级等参数没有统一的确认门禁；
5. 主 Agent 与报课意向旁路如果分别理解同一轮消息，可能得到不同实体和意图；
6. 图节点同时承担理解、路由和业务执行，边界不够清晰；
7. SSE 只能看到最终路由，难以离线评估主意图、旁路意图和 UNKNOWN 类型。

本次优化没有把所有能力继续塞进一个大 Prompt，而是在原 Supervisor 与 LangGraph
之间增加一层独立的**对话决策与仲裁层**。

## 2. 最终架构

```text
用户消息
  -> 身份、权限和隐私前置处理
  -> Redis 会话窗口、滚动摘要、已确认实体和 pending 读取
  -> 确定性规则与实体/槽位解析
  -> 可选一次 Supervisor 模型分类
  -> Dialogue Arbitration 统一仲裁
       - 主意图 primary_intent
       - 旁路意图 secondary_intents
       - 对话行为 dialogue_act
       - 确认槽位 slot_updates
       - 未完成流程 pending_flow
       - UNKNOWN 细分类 unknown_kind
       - 最终 route 与副作用等级
  -> 不可变 TurnDecision 写入 ContextEnvelope
  -> LangGraph 主业务节点
  -> 报课意向 Agent 只做旁路分析
  -> reducer/业务服务执行受控副作用
```

这套设计仍然是“确定性状态机 + 可选 LLM 分类 + LangGraph 执行”，没有把权限、
报告周期、数据库范围或联系方式授权交给模型自由决定。

## 3. 统一不可变决策契约

新增 `backend/app/dialogue/contracts.py`，核心对象为 `TurnDecision`：

```python
TurnDecision(
    primary_intent=...,
    secondary_intents=(...),
    dialogue_act=...,
    active_entity=...,
    slot_updates={...},
    pending_flow=...,
    missing_slots=(...),
    requires_live_data=...,
    side_effect_level=...,
    route=...,
    confidence=...,
    recognition_source=...,
    unknown_kind=...,
)
```

决策对象使用冻结 dataclass，槽位映射转换为只读 `MappingProxyType`。其目的不是
追求形式上的不可变，而是保证 FAQ、学情分析和招生旁路读取的是**同一份已仲裁事实**，
任何 Agent 都不能就地修改共享字典并影响其他 Agent。

## 4. 决策优先级

本项目使用以下固定顺序：

```text
身份/权限/隐私
> 显式取消
> 已有 pending 参数补全
> 用户纠错和明确话题切换
> 实体、指代和槽位更新
> 高风险确定性守卫
> Supervisor 主意图
> 主/旁路意图冲突仲裁
> 试听报名旁路
> UNKNOWN 细分类
```

优先级写入代码职责和测试，而不是仅依赖 Prompt。模型可以协助分类，但不能推翻
已经确认的身份、权限、取消动作、联系方式保护和高风险槽位门禁。

## 5. 主意图与旁路意图

复合诉求不再强迫分类器只选择一个标签。

示例：

```text
这个班多少钱，我还想预约试听
```

仲裁结果：

```text
primary_intent   = course_detail
secondary_intents = [trial_booking]
route            = faq
```

价格问题决定主回答，试听信号交给报课意向 Agent 旁路分析。旁路可以生成或更新线索，
但不能覆盖用户正在等待的价格答复。该设计保留了多 Agent 的并行价值，同时避免多个
Agent 同时争夺最终回复。

## 6. pending 状态机

当前受控 pending 流程包括：

- 家长学情报告：需要确认 `period_start`、`period_end`；
- 教师班级学情：需要确认 `class_id`、`period_start`、`period_end`。

行为规则：

1. “生成学情报告”缺少周期时建立 pending，并返回报告专用澄清；
2. 用户说“谢谢”时自然回复，但 pending 保留；
3. 用户随后说“上个月”时恢复原报告流程；
4. 用户说“不用了/取消/不生成了”时显式清除；
5. 用户明确切换到其他业务时不允许旧 pending 劫持新问题。

这解决了“礼貌插话导致系统忘记任务”和“旧任务无期限绑架后续对话”两个相反问题。

## 7. 槽位来源与确认门禁

每个槽位都带有来源、置信度和确认状态：

```text
user_explicit    用户本轮明确提供
deterministic    白名单解析器确定得到
session          会话中已经确认并继承
database         授权数据库范围
model_inferred   模型推断候选
```

报告周期和班级范围只有 `confirmed=True` 才算完成。模型推断值可以作为候选用于澄清，
但不能直接驱动报告生成或扩大数据库查询范围。

这不是对模型能力的不信任，而是副作用分级：课程介绍可以容忍低风险语义判断，
报告、班级统计和权限范围必须依赖可解释、可追溯的确定值。

## 8. UNKNOWN 细分类与固定边界

`UNKNOWN` 被拆分为：

| 类型 | 示例 | 处理 |
|---|---|---|
| `small_talk` | 你好、谢谢 | 固定寒暄节点 |
| `needs_clarification` | 无上文的“这个课程” | 要求提供具体名称 |
| `unsupported_in_domain` | 实时名额、实时排课 | 人工确认 |
| `out_of_scope` | 股票、数字货币 | 固定域外说明 |
| `in_domain_general` | 属于机构业务但未细分 | 允许 FAQ |
| `unknown` | 无法判断 | 保守澄清 |

新增 `small_talk` 和 `out_of_scope` LangGraph 节点。纯问候、域外问题和无上下文指代
均不访问 RAGFlow，避免把知识库当作万能聊天模型。

## 9. 多 Agent 共享上下文

`ContextEnvelope` 新增 `decision` 字段。共享内容仍遵循最小投影原则：

- 共享：最终路由、主/旁路意图、已确认实体、受控槽位、pending、摘要和近期窗口；
- 不共享：联系方式明文、Token、数据库连接信息、完整 Prompt、其他用户数据；
- Agent 只读取 Envelope，业务结果通过既有 reducer/服务边界写回；
- 不创建跨进程 A2A 服务，不增加网络故障面。

Redis 继续负责按租户、用户、角色、学员和会话隔离短期状态；PostgreSQL 继续保存
低敏感结构化长期偏好。当前问题主要是状态仲裁，不需要把完整聊天写入向量数据库。

## 10. LangGraph 执行边界

图层只消费已完成的决策：

- `small_talk`：固定问候、感谢和取消确认；
- `out_of_scope`：固定域外说明；
- `clarification`：根据报告、班级或指代缺失返回专用澄清；
- FAQ、服务规则、个人学情、报告、人工处理保持原有单职责节点；
- 图定义不再重新猜主意图或修改共享槽位。

## 11. 安全可观测性

SSE `complete` 事件增加：

```json
{
  "primary_intent": "course_detail",
  "secondary_intents": ["trial_booking"],
  "unknown_kind": null
}
```

这些字段只包含白名单枚举，不包含消息正文、手机号、邮箱、学员内部编号或槽位值。
它们可用于构建意图混淆矩阵、复合意图命中率、UNKNOWN 分布和路由回归统计。

## 12. 全量测试发现并修复的幂等边界

第一次全量测试发现：既有测试先用显式日期生成 2026 年 8 月报告，新增多轮测试再用
“上个月”生成同一日期范围时，稳定任务 ID 相同，但 `period_type` 展示元数据不同，
导致数据库把它误判为冲突请求。

修复后报告幂等范围只依据：

```text
请求人 + 报告类型 + 业务对象 + period_start + period_end + 模板版本
```

`period_type` 仅描述用户采用“自然月/最近 30 天/显式日期”的表达方式，不参与业务
同一性判断。同一范围不重复渲染或上传 PDF，并增加专项回归测试。

## 13. 主要代码清单

新增：

- `backend/app/dialogue/contracts.py`
- `backend/app/dialogue/slots.py`
- `backend/app/dialogue/unknown.py`
- `backend/app/dialogue/classification.py`
- `backend/app/dialogue/pending.py`
- `backend/app/dialogue/arbitration.py`
- `backend/app/workflows/conversation/nodes/small_talk.py`
- `backend/app/workflows/conversation/nodes/out_of_scope.py`
- `tests/test_dialogue_decision.py`
- `tests/test_dialogue_api.py`

修改：

- `backend/app/services/conversation_state.py`
- `backend/app/context/contracts.py`
- `backend/app/context/assembler.py`
- `backend/app/workflows/chat_stream.py`
- `backend/app/workflows/conversation/builder.py`
- `backend/app/workflows/conversation/contracts.py`
- `backend/app/workflows/conversation/nodes/clarification.py`
- `backend/app/services/report_execution.py`
- 相关 API、会话、上下文和报告测试

## 14. 优化效果

| 场景 | 优化前风险 | 优化后结果 |
|---|---|---|
| “你好” | 进入 FAQ/RAG | 固定回复，FAQ 调用 1 次降为 0 次 |
| 股票问题 | 知识库可能越界回答 | 固定域外节点，FAQ 调用降为 0 次 |
| 无上文“这个课程” | 猜课程或全库检索 | 明确要求课程名，FAQ 调用降为 0 次 |
| 报告→谢谢→上个月 | pending 可能丢失 | 礼貌插话后恢复报告 |
| 价格+预约试听 | 试听覆盖价格 | 价格主回答 + 试听旁路 |
| 模型猜周期 | 可能触发报告工具 | 未确认槽位强制澄清 |
| 多 Agent 理解 | 各自猜测、结果漂移 | 共享同一不可变 TurnDecision |
| 同日期不同周期说法 | 报告任务冲突 | 复用同一任务和 PDF |
| 多用户同会话 ID | 上下文串用风险 | 按主体作用域隔离 |

以上是自动化测试中的确定性结果，不等同于未经评测的线上准确率承诺。

## 15. 验证结果

- 对话决策、API、意图、会话、记忆、招生相关专项：`140 passed, 3 warnings`；
- 图、API、线索、家长学员解析相关回归：`96 passed, 3 warnings`；
- 报告幂等与对话边界补充回归：`121 passed, 3 warnings`；
- 后端全量：`553 passed, 8 skipped, 3 warnings`；
- 前端：typecheck 通过，Vitest `20 passed`，普通构建与 `build:backend` 通过；
- `compileall -q backend scripts tests`：通过；
- `git diff --check`：通过，仅显示工作区既有换行符提示；
- 生产 Python 文件最大 `599` 行，超过 `800` 行为 `0`。

跳过项仍来自需要额外 PDF 原生依赖或显式外部服务配置的既有用例。3 条 warning
仍为 FastAPI `on_event` 和 Starlette `BlockingPortal` 弃用提示，不是本阶段业务失败。

## 16. 当前边界与后续可选项

本阶段已经完成个人求职项目所需的业务和工程闭环。若未来有明确线上数据，可继续：

1. 使用真实测评集统计主意图、旁路意图、UNKNOWN 和槽位错误；
2. 对 Supervisor 模型输出增加按错误类型分组的重试指标，而不是盲目增加调用次数；
3. 将 FastAPI 启动事件迁移到 lifespan，消除弃用 warning；
4. 在有容量目标后做 Redis 高可用、报告异步 worker 和观测看板；
5. 只有历史情景召回确有业务收益时，再评估 Embedding 和向量记忆。

当前不建议为了展示技术栈重新引入 A2A，也不建议把所有聊天历史无筛选写入向量库。

## 17. 第三阶段：Router 模型与自动化评测治理

在统一 `TurnDecision` 和状态机稳定后，第三阶段继续补齐“模型可重复、错误可量化、
线上可诊断”三项工程能力。该阶段不是重新改写业务路由，而是为已有决策链增加
受控模型配置、代表性样例、离线评测和隐私安全日志。

### 17.1 Router 固定零温度与可选专用模型

`backend/app/api/dependencies.py` 的 `get_intent_model()` 不再继承普通回答模型的
`LLM_TEMPERATURE`，而是始终使用 `temperature=0`。原因是 Router 只输出结构化
意图，不需要语言多样性；零温度可以减少同一输入在多次执行时发生分类漂移。

模型选择顺序为：

```text
LLM_ROUTER_MODEL（配置时优先）
  -> LLM_MODEL（未单独配置时复用）
```

本地仍可复用 `deepseek-chat`，个人项目无需为了“专用 Router”额外绑定第二家模型
供应商。配置项的价值是保留独立调优和成本切换能力，不是强制增加部署复杂度。

### 17.2 高价值 few-shot 与确定性规则分工

新增 `backend/app/prompts/intent_router_examples.txt`，只放置历史报告与报告生成、
实时学情、课程详情、价格加试听、实时排课、服务规则、指代和域外问题等高混淆
边界。Prompt 样例不能替代确定性规则：身份、联系方式脱敏、报告周期确认、实时
名额、pending 和工具副作用仍由代码守卫。

为兼容“帮我生成上个月的学情报告”这类周期插在动词与报告名之间的自然表达，
报告生成守卫改为“报告对象词 + 生成动作词”的组合判断，周期继续由日期白名单
解析器确认。这样既补足自然语言覆盖，也不会把单纯“查看报告”误判成生成任务。

### 17.3 两类评测链路

真实模型分类评测：

- `scripts/evaluate_real_intent_model.py`；
- 输出主意图 accuracy、逐类 Precision/Recall/F1、expected×actual 混淆矩阵；
- 另外计算实体、实时数据标记和识别来源准确率；
- 只有人工显式运行时才调用真实模型，普通 pytest 不访问外部供应商。

离线多轮状态评测：

- `scripts/evaluate_multiturn_state.py`；
- `scripts/intent_evaluation/multiturn.py` 与 `multiturn_cases.py`；
- 使用 `InMemoryConversationStore`、`model=None` 回放 12 组、20 轮虚构场景；
- 统计路由、主意图、旁路意图、UNKNOWN、pending 状态、槽位值/来源/确认状态；
- 分别统计 pending 建立、保留、恢复和取消成功率；
- 包含相同 `conversation_id`、不同用户主体不得共享实体的隔离用例。

当前离线数据集各项准确率均为 `100%`。这是确定性回归集结果，用于发现代码回归，
不等同于真实用户流量上的模型泛化准确率。

### 17.4 脱敏结构化决策事件

新增 `backend/app/observability/decision_events.py`，每轮只记录低基数白名单字段：

```text
request_id / decision_source / primary_intent / secondary_intents
route / dialogue_act / unknown_kind / pending_flow
missing_slot_names / slot_sources
model_fallback_reason / lead_sidecar_fallback_reason
contact_redaction_applied / planning_duration_ms / total_duration_ms
```

日志不接收消息正文、姓名、手机号、邮箱、用户/学员/班级内部 ID、conversation_id、
Token、Prompt、模型原始输出或思维链。request ID、route、source 和失败原因均经过
格式或枚举白名单。HTTP 集成测试进一步验证：模型未配置时会记录
`model_not_configured`；输入手机号时只记录 `contact_redaction_applied=true`，日志中
不存在号码明文。

### 17.5 阶段结果

- Router 零温度：已采用；
- 可选专用 Router 模型：已采用，未配置时复用主模型；
- 高价值混淆 few-shot：已采用；
- 主意图混淆矩阵和字段指标：已采用；
- 多轮槽位与 pending 指标：已采用；
- 脱敏结构化决策日志：已采用；
- 普通自动化测试：保持离线，不产生真实模型费用。

## 18. 稳定课程属性短路、复合请求保真与外部服务降级

### 18.1 为什么课程装备不应全部依赖 RAG

童声合唱是否需要自带乐器、舞蹈试听准备什么、编程课堂是否提供设备，属于课程目录中
低频变更、可枚举、可审计的稳定事实。若每次都调用 RAGFlow，不仅增加延迟，还会把外部
Embedding、检索和适配器的瞬时故障放大为用户可见的 503。

本项目将这类事实建模为 `equipment` 属性，并在独立
`backend/app/services/course_equipment.py` 中维护 9 个正式课程的回答。执行顺序为：

```text
课程实体/指代消解 -> 本轮属性提取 -> 单一稳定属性确定性回答 -> FAQ/RAG 兜底
```

一次只短路一个稳定属性；复合问题继续交给主决策链，避免为了快速回答装备而吞掉价格、
名额或试听等其他诉求。

### 18.2 外部知识服务的故障边界

`RagflowClient` 负责常见网络异常，但 FAQ 和服务规则门面仍需要最外层异常收敛，原因是
测试桩、SDK 或第三方适配器可能抛出非 `httpx` 异常。安全降级遵循三项原则：

1. 主 SSE 尽量完整结束，不因知识服务异常直接返回 HTTP 503；
2. FAQ 可继续尝试 LangChain 或离线回答，服务规则返回受控不可用说明；
3. 日志只记录低敏感故障类型，不向前端暴露 URL、Token、堆栈或供应商异常正文。

### 18.3 复合请求必须保留全部属性

“现在有名额吗？费用多少？”主路由仍是实时数据人工兜底，但决策中同时保留
`available_seats` 与 `price`。节点根据属性集合生成名额、费用或二者组合说明，避免
路由正确但回答不完整。LLM 或节点不得用一个主意图覆盖同轮其余明确诉求。

### 18.4 否定优先于联系方式 pending

招生联系方式补全是高优先级 pending，但不能高于明确取消。系统先判断
`has_explicit_enrollment_decline()`，只有非拒绝消息才进入联系方式补全专用路由。
明确拒绝继续进入普通仲裁与招生旁路，由同一线索事务完成：

```text
识别 DEFER/明确拒绝 -> small_talk 承接 -> 撤回活动线索
-> 清除联系方式密文/指纹/掩码 -> 不再返回授权提示
```

这避免页面已经回复“不联系”，后台线索却仍处于待跟进的状态漂移。

### 18.5 验证结果

- 核心缺陷回归：`3 passed`；
- 对话、异常降级、招生专项：`121 passed`；
- 意图、状态、API 与线索相关回归：`154 passed`；
- 后端全量：`613 passed, 8 skipped`。

覆盖课程包括舞蹈、美术、音乐与编程；因此本轮实现是属性模型和状态优先级修复，而不是
对“童声合唱班”单个样本硬编码。

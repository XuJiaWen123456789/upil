# 阶段 13-C：LangGraph 接入 A2A 学情分析

> 数据声明：本阶段只使用本地虚构演示数据和 Mock A2A 节点，不代表真实机构生产数据或真实远程 DSH 服务。

## 1. 阶段目标

在现有学情查询链路之后增加可开关的 A2A 分析增强，同时确保关闭开关或 A2A 失败时，原有数据库摘要仍然可用。

## 2. 最终调用顺序

1. Supervisor 将问题路由到 learning_summary。
2. 主系统校验演示身份和学员访问权限。
3. BusinessToolRegistry 从结构化数据服务取得可信学情快照。
4. 功能开关关闭时，直接返回原有数据库摘要。
5. 功能开关开启时，将快照再次通过 LearningSummary 契约校验。
6. LocalMockA2AClient 对学员编号脱敏并执行分析。
7. 主系统校验 A2A 状态和 Artifact。
8. 成功时返回数据库动态事实加 A2A 分析；失败时回退数据库摘要。

## 3. 配置

新增环境变量：

~~~text
A2A_LEARNING_ENABLED=false
A2A_LEARNING_MODE=mock
A2A_LEARNING_TIMEOUT_SECONDS=10
A2A_LEARNING_MAX_RETRIES=2
~~~

默认关闭是为了保证向后兼容。当前只允许 mock 模式，尚未配置任何真实远程服务地址或密钥。

## 4. SSE 事件

功能开关开启且实际尝试 A2A 后，服务会在 routed 事件之后增加一个状态事件。

成功示例：

~~~json
{
  "stage": "a2a_task",
  "status": "completed",
  "task_id": "task_xxx",
  "correlation_id": "req_xxx"
}
~~~

失败回退示例：

~~~json
{
  "stage": "a2a_task",
  "status": "failed",
  "task_id": "task_xxx",
  "correlation_id": "req_xxx",
  "fallback": "database"
}
~~~

事件不包含学员姓名、内部编号、完整快照、Artifact 正文或任何凭据。

## 5. 降级策略

- 数据库或权限校验失败：不调用 A2A，按原学情链路返回安全提示。
- A2A 客户端未构造：回退数据库摘要。
- A2A 超时达到重试上限：回退数据库摘要，并输出 failed 状态事件。
- Artifact 校验失败：回退数据库摘要，不向用户输出不可信产物。
- 功能开关关闭：响应行为与阶段 13-B 之前保持一致。

## 6. 测试结果

- 阶段定向测试：27 passed。
- 全量回归测试：105 passed, 1 skipped。

新增验证包括：

- A2A 开启后的 LangGraph 与 SSE 成功链路；
- request ID 与 correlation ID 一致；
- SSE 返回 task ID，但不暴露业务快照；
- A2A 连续超时后最多执行 3 次尝试；
- 失败后 provider 回到 database；
- 默认关闭时原有测试保持不变。

## 7. 当前边界

- 仍是单进程本地 Mock，不是跨进程或跨主机调用。
- 没有连接真实 DeepSeekHarness。
- 没有在客户端请求体中开放故障模式、任意 skill 或 A2A 地址。
- 未让 A2A 节点直连数据库、RAGFlow 或对象存储。
- 暂未实现独立任务查询、取消和持久化。

## 8. 下一阶段

阶段 13-D 建立独立的本地 HTTP A2A 子服务和受控 HTTP Client，使主服务与学情分析节点真正跨进程通信；仍使用 Mock 分析逻辑，先验证网络超时、协议版本、鉴权占位和故障隔离，再评估是否接入 DSH。

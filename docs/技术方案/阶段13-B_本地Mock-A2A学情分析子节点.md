# 阶段 13-B：本地 Mock A2A 学情分析子节点技术方案

> 本阶段使用的学员、课程和统计数据均为虚构演示数据，不代表真实教育机构或真实学员。

## 阶段目标

在不安装完整 A2A SDK、不连接真实 DeepSeekHarness 服务的前提下，用严格协议模型和本地 Mock 节点验证主系统调度远程学情分析能力的关键边界。

验证范围包括：

- 严格校验任务体；
- 将 HTTP request ID 映射为 A2A correlation ID；
- 学员身份在出站前脱敏；
- 主系统再次校验 Artifact；
- 超时只进行有限重试；
- 子节点失败后安全降级并要求人工兜底。

## 模块结构

- backend/app/a2a/contracts.py：A2A 请求、约束、Artifact 和结果模型。
- backend/app/a2a/mock_learning_agent.py：不联网、不执行代码的本地 Mock 子节点。
- backend/app/integrations/a2a_client.py：脱敏、调度、重试和结果校验门面。
- tests/test_a2a_learning_agent.py：协议、安全、重试和降级测试。

## 关键协议

任务包含 task_id、parent_task_id、correlation_id、skill、input 和 constraints。skill 当前只允许 learning_summary。

输入只保留不可逆哈希后的 learner_ref、分析周期、出勤率、已完成课时和最小必要阶段记录；不包含学员真实姓名、手机号、身份证、数据库连接、API Key、密码、完整聊天记录、命令、脚本或 SQL。

## 安全设计

1. 所有 Pydantic 协议模型使用 extra=forbid，未知字段直接拒绝。
2. no_external_network 和 no_side_effects 使用 Literal[True]，调用方不能关闭。
3. Artifact 只允许 text/markdown 和 artifact:// 引用。
4. 主系统再次检查任务关联 ID、状态、Artifact 数量、危险命令和本地路径。
5. Mock 节点不访问网络、数据库、RAGFlow、MinIO 或 Docker Socket。
6. Mock 节点不执行代码，输出由确定性模板生成。

## 重试与降级

- 单次任务约束为 10 秒。
- 只对明确的超时异常重试。
- 最多重试 2 次，即首次调用加 2 次重试，共最多 3 次尝试。
- 明确业务失败和 Artifact 校验失败不重试。
- 最终失败返回 failed、handoff_required=true，不继续生成确定性业务结论。

## 当前边界

当前是协议原型，不是完整 A2A 网络服务：尚未启动独立 A2A Server，未接入真实 DeepSeekHarness，未修改公开聊天路由，也未实现任务持久化、取消和异步轮询。

这是主动收敛。先通过自动化测试验证安全合同，再进入网络化和 LangGraph 编排，可降低调试复杂度与数据泄漏风险。

## 验证结果

- 阶段定向测试：8 passed。
- 全量回归测试：103 passed, 1 skipped。

覆盖合法任务、未知字段拒绝、强制安全开关、身份脱敏、关联 ID、任务 ID 唯一性、超时重试上限、失败兜底和危险 Artifact 拒绝。

## 下一阶段

阶段 13-C 将本地 A2A 客户端接入 LangGraph 的 learning_summary 分支，并使用功能开关。默认保持现有数据库摘要链路；只有完成身份校验并取得可信结构化快照后，才允许调用学情分析子节点。

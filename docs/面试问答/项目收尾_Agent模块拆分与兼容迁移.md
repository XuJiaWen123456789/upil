# 项目收尾：Agent 模块拆分与兼容迁移面试问答

## Q1：为什么不能只以“单文件不超过 800 行”作为拆分标准？

**答：** 行数只能提示维护风险，不能定义职责边界。一个 300 行文件若同时处理 HTTP、数据库事务、LangGraph 路由和外部请求，依然高度耦合；反过来，一个 480 行但只维护同一领域状态机的文件可能仍然内聚。uPil 先按变更原因和依赖方向拆分，再用 800 行做合入门禁，最终最大生产文件为 480 行。

## Q2：为什么 LangGraph State、路由、节点和 builder 要分开？

**答：** State 是跨节点契约，路由决定控制流，节点实现业务能力，builder 只声明拓扑，它们的变化原因不同。分开后可单测路由，可独立替换节点，也能在不阅读业务细节的情况下审核整张图。uPil 进一步保持一个节点一个文件，避免 `graph.py` 再次成为所有 Agent 逻辑的汇总文件。

## Q3：为什么保留兼容门面，而不是一次性删除旧路径？

**答：** 旧路径不仅被生产代码使用，还被测试、评估脚本、Uvicorn 命令和可能的外部调用使用。一次性改名会把“目录重构”和“公开契约迁移”混在一起，扩大风险。兼容门面只重导出新实现，不复制逻辑；生产代码已改用新路径，测试和外部脚本可渐进迁移。

## Q4：如何避免 FastAPI 拆路由后破坏 dependency override？

**答：** FastAPI 的 override 以依赖函数对象为键，而不是按函数名匹配。uPil 让 `main.py` 与 Router 都引用 `api/dependencies.py` 中的同一个函数对象，所以原有 `app.dependency_overrides[main_module.get_report_store]` 仍有效。若在 `main.py` 再包一层同名函数，测试会看似覆盖成功但实际不生效。

## Q5：如何保持既有 monkeypatch？

**答：** 一些测试会替换 `backend.app.main.plan_conversation`、`inspect_report_pdf` 或查询函数。路由迁出后如果直接静态导入实现，替换点会失效。项目使用窄职责的 `api.compat.main_symbol()` 在调用时读取旧入口符号，同时给出真实实现作为 fallback。该机制只用于迁移兼容，新业务依赖仍应通过显式参数或 FastAPI Depends 注入。

## Q6：Prompt 为什么资源化，但动态 Schema 仍由 Python 注入？

**答：** 角色说明、安全要求和输出原则适合放在可审阅的文本资源中；Pydantic Schema、意图枚举和课程白名单则是运行时契约。如果把这些动态内容复制到文本文件，会产生两套真相。uPil 由 Prompt loader 读取稳定正文，再由 Python 注入最新 Schema 和白名单。

## Q7：Tool、Connector、Workflow 和 Service 的边界是什么？

**答：** Tool 执行一个确定性动作，不控制图路由；Connector 隔离外部通信和协议，不做业务授权；Workflow 编排调用顺序和分支；Service 维护领域规则、状态机和事务。HTTP Router 只负责认证入口、参数和响应映射。该边界避免节点既查数据库又拼 HTTP 请求再决定权限。

## Q8：为什么 A2A 从 integrations 迁到 connectors？

**答：** A2A 在项目中不是一个 SDK 调用，而是包含任务最小化映射、脱敏、HTTP 传输、主机白名单、超时、重试和不可信结果复核的通信边界。Connector 更准确地表达“主应用如何连接另一个执行节点”，而 integration 目录继续容纳较薄的第三方适配。旧 integration 路径仍保留兼容重导出。

## Q9：异常、重试和脱敏为什么没有全部做成装饰器？

**答：** 复用的前提是语义一致。报告 404 防枚举、409 产物完整性、503 存储故障和事务回滚虽然都属于异常处理，但安全与提交点不同。统一装饰器会隐藏差异。项目把稳定异常、校验函数、策略和安全失败构造器模块化；只有未来出现三处以上完全同构流程时，才提取窄职责装饰器。

## Q10：如何证明这是纯组织重构，而不是业务重写？

**答：** 一是保留 HTTP URL、Schema、SSE 事件、状态迁移和错误码；二是保留旧导入路径和测试替换点；三是不新增迁移或外部配置；四是报告、Supervisor 和全量测试均通过。最终结果为 419 passed、8 skipped、3 warnings，且 `compileall` 与 `git diff --check` 通过。

## Q11：如何避免循环依赖？

**答：** 先规定单向依赖：入口到 Router，Router 到 Workflow/Service，Workflow 到 Agent/Tool/Connector，底层不反向导入 HTTP。跨层数据使用 contracts，公共重导出只放 `__init__.py`。兼容桥通过运行时读取 `sys.modules` 保持旧 monkeypatch，但正常生产依赖不使用该方式。

## Q12：为什么暂不拆测试文件？

**答：** 用户明确要求当前先治理生产代码。测试文件按场景组织，体积大不一定意味着生产职责混乱；在同一提交中同时重排生产和测试会增加 diff 噪声，降低行为对比可信度。后续可单独按 fixture、API 场景和领域契约治理测试目录。

## Q13：拆分后如何防止大文件重新出现？

**答：** 规定建议 500 行、650 行触发职责复核、800 行禁止合入；新 LangGraph 节点一文件、新 Tool 一文件、新外部通信必须进入 Connector、大段 Prompt 必须资源化。比单纯 CI 统计行数更重要的是代码评审检查依赖方向和变更原因。

## Q14：当前还有哪些生产增强没有完成？

**答：** 阶段 15-A-3 仍暂缓，包括异步 worker、租约、死信/outbox、报告保留期、撤回删除、补偿重试和 MinIO/PostgreSQL 对账。真实 DSH、真实身份提供方、真实 MinIO/PostgreSQL/RAGFlow/模型和机构数据也未接入，因此只能称为离线可验证闭环，不能称为大规模生产就绪。

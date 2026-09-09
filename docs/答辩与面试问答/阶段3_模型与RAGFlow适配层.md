# 阶段 3：模型与 RAGFlow 适配层

## 阶段目标

在不破坏离线开发和既有 SSE、权限、数据库测试的前提下，为 FAQ 智能体建立真实模型和 RAGFlow 的可插拔接入层，明确“适配器已完成”与“外部服务已连接”的边界。

## 时间

2026-09-01

## 本轮任务清单

1. 扩展模型和 RAGFlow 配置项。
2. 使用 LangChain 适配 OpenAI 兼容模型接口。
3. 使用独立客户端适配 RAGFlow OpenAI 兼容 Chat API。
4. 将 FAQ 节点改为“RAGFlow 优先、LangChain 次之、离线回退”的调用链。
5. 保持没有 API Key、Chat ID 或外部服务不可用时的稳定运行能力。
6. 为适配器添加离线契约测试和响应解析测试。
7. 更新运行说明和答辩材料。

## 关键代码与配置

FAQ 调用链：

LangGraph FAQ 节点 -> services.faq.answer_faq_question -> RAGFlow Chat API -> LangChain ChatOpenAI（可选） -> 离线固定话术

LangChain 配置：

LLM_ENABLED=false
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TEMPERATURE=0.2

langchain-openai 放在 [project.optional-dependencies].llm 中，原因是离线测试不应因为没有供应商 SDK 而无法启动。OpenAI 兼容的模型网关可以通过 LLM_BASE_URL 接入，但真实密钥必须通过环境变量或密钥管理系统注入。

RAGFlow 配置：

RAGFLOW_BASE_URL=http://localhost:9380
RAGFLOW_API_KEY=
RAGFLOW_CHAT_ID=
RAGFLOW_TIMEOUT_SECONDS=15

RAGFlow 的作用是提供机构知识库事实和可追溯回答，不负责学员权限和学情统计。权限数据仍由 uPil 后端控制，不能让 RAGFlow 直接读取生产数据库。

## 风险点

- 当前环境没有配置真实 LLM API Key，因此没有进行在线模型调用。
- 当前环境没有配置 RAGFlow API Key 和 Chat ID，因此没有进行真实知识库检索。
- 适配器捕获外部调用异常并回退，生产环境还需要日志、指标、重试和熔断。
- FAQ 的离线回退只能用于演示，不能代替机构政策知识库。
- SSE 当前仍按最终回答逐字符发送，真实模型流式输出将在后续阶段接入。

## 验证结果

13 passed, 2 warnings。

额外验证：

- pyproject.toml 可以被 Python tomllib 正常解析。
- 未开启模型时，LangChain 适配器返回 None，不会尝试联网。
- 缺少 RAGFlow API Key 或 Chat ID 时，RAGFlow 客户端返回 None，不会发起请求。
- OpenAI 兼容的 RAGFlow 响应可以解析为普通文本。
- 使用本地持久化 SQLite 数据库时，FAQ SSE 路由仍返回 200，学情路由不受影响。

## 答辩问答

### 问：为什么不让所有 FAQ 请求直接调用大模型？

答：机构客服回答涉及请假、调课、补课和收费规则，优先需要知识库事实，而不是让模型自由生成。系统先调用 RAGFlow 获取机构知识，再将模型作为可选的语言组织能力；外部服务不可用时返回明确的离线提示，避免把模型幻觉当成机构政策。

### 问：LangChain 在项目中的价值是什么？

答：LangChain 统一了模型调用、消息格式和后续工具编排接口，使上层 LangGraph 不必绑定某一个模型供应商。通过 OpenAI 兼容接口，后续可以替换模型网关而不修改 FAQ 业务节点；同时保留独立适配器，便于测试和故障回退。

### 问：RAGFlow 和 uPil 的职责如何划分？

答：RAGFlow 负责非结构化机构知识的解析、检索和回答，uPil 负责用户身份、学员数据权限、结构化学情统计和审计。两者分工可以防止知识库系统直接接触敏感业务数据库。

### 问：为什么没有把 RAGFlow 直接写进 LangGraph 节点？

答：直接写入会让工作流节点同时承担第三方 HTTP 协议、密钥管理、异常处理和业务编排，后续替换 RAG 服务时修改范围大。独立适配器可以统一超时、错误回退和响应解析，使图节点只依赖稳定的业务服务接口。

### 问：本轮能否说项目已经接入真实大模型和 RAGFlow？

答：准确说法是“已经完成 LangChain 和 RAGFlow 的适配层，支持配置后接入”，不能说“已经完成在线服务联调”。当前没有提供真实 API Key 和 Chat ID，因此验证的是离线契约和回退逻辑。

## 项目日志

阶段：第 3 阶段第一小步
时间：2026-09-01
完成内容：模型配置、LangChain 适配器、RAGFlow 客户端、FAQ 服务调用链、离线契约测试、README 和答辩问答。
遇到问题：pyproject.toml 初次修改重复声明 optional-dependencies 段，导致 TOML 解析失败。
解决方案：合并为一个 optional-dependencies 段，并重新执行测试。
验证结果：13 passed, 2 warnings。
下一步：在用户提供可用模型配置和 RAGFlow Chat ID 后进行真实在线联调；同时接入真实模型流式输出和来源信息。

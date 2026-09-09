# 阶段 13-I-4：客服演示页与 SSE 可观测性

## 阶段目标

将 uPil 的后端多智能体链路通过一个可操作的客服演示页呈现出来，形成“提交问题—路由—Agent/业务服务执行—流式返回—完成确认”的可观察闭环。

## 本阶段完成内容

### 1. FastAPI 静态页面托管

FastAPI 统一托管客服页面、JavaScript 和样式文件。API 路由在静态目录挂载前注册，避免根路径静态资源遮蔽业务接口。静态目录不放置密钥、数据库文件、服务令牌或内部配置。

关键文件：

- D:/uPil/backend/app/main.py
- D:/uPil/backend/app/static/index.html
- D:/uPil/backend/app/static/app.js
- D:/uPil/backend/app/static/style.css

### 2. POST + SSE 流式响应

对话接口需要提交 JSON，因此前端使用 fetch 和 response.body.getReader() 消费 SSE，而不是原生 EventSource。前端支持网络包拆分、UTF-8 多字节字符跨包、CRLF、多行 data、尾部 buffer flush 和 AbortController 请求取消。

结构化事件包括：

| 事件 | 含义 |
|---|---|
| status accepted | API 已接收请求 |
| status routed | Supervisor 已确定业务路由 |
| status a2a_task | A2A 学情子任务状态 |
| token | 回答增量文本 |
| complete | 路由、供应商、识别来源和引用等最终信息 |

complete 是前端判断成功结束的明确标志。流意外结束且没有 complete 时，页面显示异常，不把半截答案当成成功。

### 3. 普通模式与调试模式隔离

普通模式只展示自然语言回答，不展示内部文档、切片、A2A 任务信息和原始业务数据。答辩调试模式额外展示 SSE 事件时间线、route、provider、识别来源、耗时和真实引用来源，并显示仅用于 staging 联调的演示学员编号。

演示学员编号默认 L1001，只有调试模式才会发送。正式环境不能信任浏览器提交的角色、用户编号或学员编号，应从登录态、JWT 或网关认证上下文注入。

## 验证结果

自动化检查：

- Python compileall 通过；
- app.js 的 Node 语法检查通过；
- 全量回归：152 passed, 1 skipped, 2 warnings。

staging 检查：

- upil-api：healthy；
- upil-a2a-learning：healthy；
- /api/v1/health：HTTP 200，status=ok；
- 根页面：HTTP 200，包含调试模式和演示学员字段。

FAQ 真实链路：

- 问题：编程课需要家长提前购买电脑吗？
- route：faq；provider：ragflow；
- 回答由真实 RAGFlow 返回，普通模式不展示内部来源。

A2A 真实联调链路：

- 问题：查询孩子的学情和出勤情况；学员：L1001；
- 事件包含 accepted、routed、a2a_task=completed、token 和 complete；
- route：learning_summary；provider：a2a_http；
- 主 API 先做权限校验和数据库查询，再通过 Docker 内网调用 A2A 子服务。

## 风险与边界

1. 当前是本地 staging 生产化约束原型，不代表真实机构生产上线。
2. 所有课程、学员和教务数据均为虚构演示数据。
3. A2A 子服务当前是本地受控 Mock，不是正式 DeepSeekHarness 集群。
4. 前端调试开关不是安全边界，正式身份必须由认证上下文提供。
5. 开发期会话仍使用进程内 Store，多实例部署应替换为 Redis 或 PostgreSQL。
6. FastAPI on_event 存在弃用 warning，后续可迁移为 lifespan。

## 阶段结论

阶段 13-I-4 完成。uPil 已形成客服页面、SSE 流式响应、LangGraph 路由、RAGFlow FAQ 和跨容器 A2A 学情分析的可观测演示闭环。

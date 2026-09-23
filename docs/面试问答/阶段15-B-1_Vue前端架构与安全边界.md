# 阶段 15-B-1 面试问答：Vue 前端架构与安全边界

## Q1：为什么从原生页面迁移到 Vue，而不是直接用 Chainlit 或 Streamlit？

因为系统已经不是单纯 Agent 聊天 Demo，而是包含家长学情、报告列表/详情/安全下载、教师班级统计、媒体上传、独立审核和 POST SSE 的双角色业务工作台。Chainlit 更适合 Agent 演示，Streamlit 更适合内部数据看板；两者都不能自然表达当前的角色导航、细粒度能力、文件交付和长期页面维护。Vue 3 + TypeScript + Vite 在当前规模下能以较低复杂度提供组件、路由、类型和构建能力。

## Q2：为什么不用 Nuxt？

当前没有 SEO、SSR 或公开内容页面需求。报告和工作台都是认证后的业务页面，FastAPI 已经是唯一安全边界。引入 Nuxt 的服务端渲染和部署层会增加复杂度，却不能替代后端授权，因此选择 Vite SPA。

## Q3：Vue 路由守卫能保证权限安全吗？

不能。守卫只是改善导航体验，防止用户进入明显不适合的页面。每个后端接口仍根据认证上下文、角色、资源绑定、校区范围和细粒度权限重新判断。隐藏按钮、前端 capability 和 URL 守卫都不能视为安全控制。

## Q4：报告下载为什么不能让浏览器直接访问 MinIO？

报告属于家长本人，下载前必须重新验证身份、任务所有权、Artifact 类型、摘要、大小、页数、模板文字和隐私字段。若给浏览器预签名 URL，容易绕开业务审计和状态门禁，也会扩大对象键和存储拓扑暴露面。因此浏览器只请求 FastAPI 下载代理，由服务端从私有桶读取并以不可缓存响应交付。

## Q5：Demo 身份会不会变成生产漏洞？

不会把 Demo 参数当生产认证。只有 `AUTH_MODE=demo` 时前端才显示切换器并追加 `actor_role`/`actor_user_id`；trusted header/OIDC 模式后端认证层忽略这些字段，分别只信任已校验 Header 或 Bearer JWT 映射到本地用户。前端也不保存真实 Token。

## Q6：为什么手写 SSE 消费，而不用更重的库？

当前是 POST SSE，不是标准 EventSource 的 GET 场景；原生 Fetch 可以携带 JSON、AbortController 和同源凭据。手写解析器明确覆盖 UTF-8 网络分块、CRLF、多行 data、尾部 buffer 和错误关闭，代码量小、行为可测试，也不会把第三方客户端状态层引入核心路径。

## Q7：前端拿到 bootstrap 的 feature flag 后，关闭功能是否安全？

不是安全控制。feature flag 只决定导航和体验；业务接口仍由后端鉴权，前端不能通过修改响应、URL 或请求参数扩大权限。bootstrap 特意不返回 DSN、MinIO、OIDC/JWKS、A2A 或密钥。

## Q8：如何保证 Vue 构建不会破坏旧静态页？

本地 `build:backend` 先在临时目录构建，成功后才执行目录级切换；Vite 构建失败不会清空现有 `backend/app/static`。staging 镜像则在独立 Node builder 中从 lockfile 执行 `npm ci`，Python runtime 只复制 dist，不依赖开发机 `node_modules`。

## Q9：当前是否已经生产就绪？

不能这样表述。前端迁移、接口消费和离线测试闭环已完成，但真实 OIDC、MinIO、PostgreSQL、模型、TLS、Secret、字体镜像、迁移、备份恢复和规模化异步可靠性仍需独立验收。15-A-3 已明确标记为“生产增强，暂缓”，没有被前端迁移隐含完成。

## Q10：这次最终验证覆盖了哪些层次？

前端执行了类型检查、Vitest 单元测试和生产构建；后端执行了认证、SPA 托管与 staging 专项测试、全量 pytest 以及 Python compileall；同时对前端源码和构建产物按精确配置键集合扫描，确认没有把 `MINIO_ENDPOINT`、`DATABASE_URL`、`OIDC_CLIENT_SECRET` 等敏感配置名带入浏览器侧。最终全量结果为 368 passed、1 skipped、2 warnings。跳过项是显式开启才会访问真实外部模型的测试，warning 是既有 FastAPI `on_event` 弃用提示。

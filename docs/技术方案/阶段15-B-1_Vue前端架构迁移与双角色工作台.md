# 阶段 15-B-1：Vue 前端架构迁移与双角色工作台

> 状态：完成（本地构建与离线测试闭环）
> 时间：2026-09-11（Asia/Shanghai）
> 项目目录：D:/uPil

## 1. 阶段目标

在不改变既有 FastAPI 业务接口、认证授权边界和报告安全交付规则的前提下，把原有客服演示页扩展为可维护的双角色业务工作台：家长访问学情与报告，教师访问班级统计和媒体上传/独立审核，同时继续支持 POST SSE 对话。

本阶段不接入真实 DSH、真实 MinIO、真实 OIDC、真实 PostgreSQL、真实模型或教育机构数据；阶段 15-A-3“报告生命周期与异步可靠性”保持“生产增强，暂缓”。

## 2. 现状与接口盘点

前端实际消费的接口包括：

| 场景 | 接口 | 约束 |
| --- | --- | --- |
| 启动与会话 | GET /api/v1/frontend/bootstrap、GET /api/v1/session | 只返回公开开关和最小能力，不下发内部连接配置 |
| 对话 | POST /api/v1/chat/stream | 手动消费 SSE，处理分块、CRLF、多行 data 和取消 |
| 家长学情 | GET /api/v1/learners/{learner_id}/learning-snapshot | 后端再次校验家长与学员绑定 |
| 家长报告 | GET /api/v1/reports、详情、下载 | 下载始终经过 FastAPI 鉴权、完整性复核和私有代理 |
| 教师统计 | GET /api/v1/classes/{class_id}/learning-summary | 后端按教师授课班级与校区授权计算 |
| 媒体工作台 | 上传、审核、短时地址 | 上传/审核能力分离，上传者不能自审 |

浏览器不访问数据库、MinIO、A2A、RAGFlow 或任何服务端密钥。报告不接收预签名 URL，前端只将 FastAPI 响应作为本地下载 Blob。

## 3. 框架决策

最终采用：

```text
Vue 3 + TypeScript + Vite + Vue Router + Pinia
原生 Fetch + 手动 POST SSE 消费
Vitest + @vue/test-utils/jsdom 基础测试能力
```

### 3.1 为什么适合当前项目

- 当前是中等规模业务工作台，不是纯聊天页面；组件、路由和状态边界清晰；
- TypeScript 可以收敛角色、能力、报告状态和媒体审核状态等 API 契约；
- Vite 构建快，适合本地演示、离线测试和容器多阶段构建；
- Vue Router 能表达家长/教师角色和 capability 守卫；Pinia 只保存最小会话展示信息；
- 原生 Fetch 足以满足当前同源 JSON、FormData、Blob 和 POST SSE，不增加不必要的 SDK。

### 3.2 为什么不选其他方案

- **Chainlit**：适合快速展示 Agent/聊天流程，但不适合本项目的双角色业务导航、报告文件交付、教师媒体审核职责和长期组件维护；
- **Streamlit**：适合内部数据分析和快速看板，但认证、权限、SSE、文件交付和精细路由不是它的强项；
- **Nuxt**：当前不需要 SEO、SSR 或服务端页面数据装载，采用会增加部署和运行复杂度；
- **React**：技术上可行，但当前团队和项目接口不需要为 React 生态额外引入复杂状态/请求层，Vue 的轻量组合已经满足目标；
- **继续原生 JavaScript**：短期可运行，但会继续扩大模板字符串、角色分支、请求错误和 SSE 处理的维护成本。

## 4. 前端模块设计

```text
frontend/src/
├── api/       同源请求、Demo 身份、SSE、报告、学情、媒体
├── router/    history 路由与角色/capability/feature 守卫
├── stores/    Pinia 会话状态，不保存真实 Token
├── types/     与后端响应对应的最小 TypeScript 契约
└── views/     对话、家长学情/报告、教师班级/媒体、404
```

`App.vue` 负责壳层和导航，页面负责业务交互，FastAPI 负责真实鉴权。路由守卫只改善体验，不能替代接口授权；业务请求即使来自隐藏页面，也必须再次通过后端权限检查。

Demo 模式的角色切换器写入 `sessionStorage`，不写入真实 Bearer Token；trusted header 和 OIDC 模式由后端忽略浏览器附带的 `actor_role`/`actor_user_id`，前端不把它们当成生产身份机制。

## 5. FastAPI 同源托管与构建

Vite 产物放入 `backend/app/static`，由自定义 `SpaStaticFiles` 提供 history 路由回退。仅不带扩展名、非 `/api/` 的前端路径回退到 `index.html`；缺失的 JS/CSS、API 路径仍为真实 404，避免把接口错误伪装成页面。

`frontend/scripts/build-backend.mjs` 先生成临时 dist，再进行目录级切换；构建失败时不清空现有静态页。staging Dockerfile 使用 Node builder + Python runtime 多阶段构建。

## 6. 安全边界

1. FastAPI 是唯一认证、授权、审计和文件交付边界；
2. bootstrap 只返回功能开关，不返回 DSN、桶名、内部地址或密钥；
3. `/api/v1/session` 的能力只用于导航，业务接口继续后端鉴权；
4. PDF 下载只走 `/api/v1/reports/{task_id}/download`，不暴露 MinIO 对象键/预签名 URL；
5. 浏览器不保存真实 Token，不直接连接数据库、MinIO、A2A 或 RAGFlow；
6. 上传和媒体审核界面按 capability 分开展示，后端继续执行上传者不能自审；
7. 错误消息使用固定或脱敏文案，不展示后端异常堆栈和内部连接信息。

## 7. 验证记录

已完成：

```text
frontend npm run typecheck：通过
frontend npm run test：7 passed
frontend npm run build：通过
frontend npm run build:backend：通过
后端认证、SPA 托管和 staging 专项：96 passed, 2 warnings
后端全量回归：368 passed, 1 skipped, 2 warnings
```

专项测试覆盖：Demo 身份只追加一次，trusted header/OIDC 不接受伪造 Demo 参数；SSE CRLF、多行 data、任意网络分块和尾部未闭合 buffer；报告下载文件名安全解析；静态资源、history 深层路由、缺失资源 404；staging 多阶段 Dockerfile、`.dockerignore` 和非 root 约束。

## 8. 未完成与后续

- 真实 OIDC 网关、真实 MinIO、真实 PostgreSQL、真实模型和真实机构数据仍需独立验收；
- 15-A-3 的 worker、outbox、报告保留期、撤回、版本替换和对象对账仍暂缓；
- 可继续补充端到端浏览器自动化，但不能把它等同于生产身份或可靠性验收；
- 生产部署仍需验证 TLS、Secret Manager、字体镜像、迁移、备份恢复、限流和监控告警。

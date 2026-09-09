# uPil 本地 staging 预发布环境

本目录用于模拟接近生产的本地预发布配置，不代表真实教育机构生产上线。
当前阶段先提供环境变量模板；正式启动前需要根据主机资源和 RAGFlow 部署
状态逐步启用服务，避免一次启动所有重量级组件。

## 环境边界

- dev：SQLite、离线 FAQ、A2A 关闭，适合快速开发；
- test：pytest 和依赖注入 Mock，不要求 Docker；
- staging：计划使用 PostgreSQL、MinIO、RAGFlow 和独立 A2A 服务；
- 所有学员、课程、班级和学情内容仍是虚构演示数据。

## 配置原则

1. 复制 .env.staging.example 为未提交的 .env.staging；
2. 使用真正的随机数据库密码、MinIO 密钥和内部 A2A Token；
3. 不把 .env.staging、API Key、密码和 Token 写入日志；
4. 不把 Docker Socket 挂载给 uPil 或 DSH；
5. 先启动依赖，再通过 GET /api/v1/health/dependencies 验证；
6. RAGFlow、模型和 A2A 均可选，故障时主 API 应保持可响应并明确降级。

## 健康检查

PowerShell 测试命令：

Set-Location D:\uPil
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-stage13g tests

API 启动后访问：

http://127.0.0.1:8000/api/v1/health
http://127.0.0.1:8000/api/v1/health/dependencies

依赖健康接口只返回 ok、degraded、not_configured、disabled 等状态，
不会返回地址、密码、Token、API Key 或第三方响应正文。

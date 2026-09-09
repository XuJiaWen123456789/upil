# uPil 的 RAGFlow 本地部署

本目录是 uPil 的独立 RAGFlow Compose 项目。RAGFlow 负责 PDF/Markdown 解析、表格识别、文档切片、向量或混合检索和来源引用；uPil 负责业务数据库、身份权限、SSE 和媒体访问控制。

## 服务边界

- ragflow-cpu：RAGFlow 应用，Web 控制台 http://localhost:19080，OpenAI 兼容 API http://localhost:19380
- es01：RAGFlow 检索索引，主机端口 19200
- mysql：RAGFlow 元数据数据库，主机端口 13306
- redis：RAGFlow 任务状态和缓存，主机端口 16379
- upil-minio：复用 uPil 已有 MinIO，通过 upil_network 网络访问

## 启动

确保 uPil 基础设施已启动，然后在 PowerShell 执行：

    Set-Location D:\uPil\infra
    docker compose up -d
    Set-Location D:\uPil\infra\ragflow
    docker compose config
    docker compose up -d
    docker compose ps

首次启动需要下载 RAGFlow、Elasticsearch、MySQL 和 Valkey 镜像，可能需要较长时间和较多磁盘空间。RAGFlow 应用完成初始化后访问 http://localhost:19080。

## 停止和日志

    docker compose logs -f ragflow-cpu
    docker compose stop

开发阶段不要使用 docker compose down -v，否则会删除知识库、索引和元数据卷。

## MinIO 说明

RAGFlow 容器使用 upil-minio:9000 访问 MinIO，这是 Docker 网络内地址；uPil API 在 Windows 主机上使用 localhost:19000。两者指向同一个 MinIO 服务，不能把主机映射端口 19000 写入 RAGFlow 容器内部配置。

RAGFlow 使用独立的 ragflow-data Bucket，uPil 的 upil-media Bucket 继续保存业务图片，避免知识库原文件与业务媒体混在一起。首次使用前需要在现有 MinIO 中创建 ragflow-data Bucket，或者按 RAGFlow 日志提示处理 Bucket 初始化错误。

## 后续配置顺序

1. 确认 RAGFlow 控制台可访问。
2. 在 RAGFlow 中配置聊天模型和 Embedding 模型。
3. 创建 星河素质教育中心 Dataset，导入 D:\uPil\knowledge_base 中的正式语料，不导入 evaluation 目录。
4. 创建 Chat Assistant，记录 API Key 和 Chat ID。
5. 只把这两个值写入 uPil 运行环境变量：RAGFLOW_API_KEY、RAGFLOW_CHAT_ID。
6. 回归测试 FAQ 检索、引用来源、图片相关问答和无答案兜底。

uPil 调用的推荐接口为 POST /api/v1/openai/{chat_id}/chat/completions，请求体会
通过 extra_body.reference=true 要求 RAGFlow 返回引用切片。主机访问端口是 19380，
不要把容器内部端口 9380 直接填写到 Windows 主机配置中。

## 当前限制

- 这是本地开发验证配置，密码为示例值，不能直接用于公网生产。
- 没有启用 RAGFlow 的代码执行沙箱。涉及数据统计的任务仍应走 uPil 受控工具或后续 A2A DSH 节点。
- 没有启用本地 TEI Embedding 服务。Embedding 模型需要在 RAGFlow 控制台中配置可用的模型提供方，否则只能完成控制台启动，不能完成文档向量化。

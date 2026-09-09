# 第 10 阶段：RAGFlow 真实知识库接入清单

## 本阶段目标

完成以下闭环：

星河机构语料 -> RAGFlow Dataset -> 文档解析与向量化 -> Chat Assistant -> uPil FAQ -> SSE 来源

本阶段只配置本地演示环境，不接入真实学员隐私数据，也不把 API Key、密码或 Chat ID 写入项目文件。

## A. 配置聊天模型与 Embedding 模型

1. 打开 http://localhost:19080，使用已经恢复的 RAGFlow 管理员账号登录。
2. 点击右上角头像，进入 Model providers（模型提供商）。
3. 配置聊天模型（当前下一步）：
   - 优先选择控制台中可用的 DeepSeek 官方提供商。
   - 如果没有 DeepSeek 专用入口，选择 OpenAI-API-Compatible。
   - API Key 只在 RAGFlow 页面本地填写，不要发送到对话中。
   - Base URL 按实际服务商文档填写；使用兼容接口时确认是否需要包含 /v1。
   - 添加服务商实际提供的模型 ID，例如服务商明确提供的 deepseek-chat，不要凭空填写不存在的模型名。
4. Embedding 模型已完成配置：
   - Provider：Ollama。
   - Model name：bge-m3。
   - Model type：Embedding。
   - Base URL：http://host.docker.internal:11434。
   - 向量维度：1024。
   - RAGFlow 控制台连接测试：成功。
5. 在 System Model Settings（系统模型设置）中设置默认 Chat model 和默认 Embedding model。
6. 使用控制台的连接测试确认聊天模型可用；Embedding 已完成验证。

## B. 创建正式 Dataset

建议名称：uPil-星河素质教育中心-FAQ

当前执行步骤：

1. 在 RAGFlow 顶部进入 Knowledge Base 或 Dataset 页面。
2. 点击 Create knowledge base、Create Dataset 或“创建知识库”。
3. 名称填写：uPil-星河素质教育中心-FAQ。
4. 描述填写：星河素质教育中心公开课程、师资、服务规则和边界场景知识库，仅用于本地演示与联调。
5. Embedding 模型选择已经连接成功的 bge-m3，确认向量维度为 1024。
6. 解析方式选择 Built-in 或系统默认的通用解析方式；暂不导入文件，先完成 Dataset 创建。
7. 权限选择仅自己可管理，完成创建后停在 Dataset 文档列表页面。

Dataset 创建结果：已成功创建“uPil-星河素质教育中心-FAQ”，Chunk method 为 General。本步骤已完成。

导入范围：

- D:\uPil\knowledge_base\demo_institution 下的正式机构资料；
- 包括 09_exception_handling 下的边界规则；
- 不导入 D:\uPil\knowledge_base\evaluation，评测集只用于离线验收；
- raw 下的原始 PDF 暂不进入正式 Dataset，后续单独建立对比 Dataset。

创建 Dataset 时建议：

- Embedding：选择已经连接测试成功的中文模型；
- Parse type：Built-in；
- 解析模板：优先选择适合 Markdown 和通用文档的模板；
- Dataset 权限：本地单人演示选择仅自己可管理；
- 在解析任何文档前确认 Embedding 模型，已有切片后不要随意更换。

## C. 文档导入与解析

当前执行步骤：

1. 在已创建的 Dataset 中批量添加 D:\uPil\knowledge_base\demo_institution 下的 12 个 Markdown 文件。
2. 上传后先核对文件数量为 12、文件名均来自正式机构目录，再点击解析。
3. 等待所有文档状态变为完成，并确认切片数量大于 0。
4. 图片文件和 raw 下的原始 PDF 暂不上传；它们在文本切片验收通过后单独测试。
5. 抽查以下内容：
   - 教师履历、授课风格和课程咨询方向；
   - 课程价值与适龄建议；
   - 收费、请假、补课和特殊情况规则；
   - Markdown 表格是否出现错行或跨段拼接；
   - 图片说明是否保留，是否出现内部路径或技术词。
6. 对错误切片进行人工修订或补充关键词，并在项目日志中记录调整原因。

## D. 创建 Chat Assistant

建议名称：星河素质教育中心 FAQ 客服助手

配置要求：

- 只关联正式 FAQ Dataset；
- Chat model 选择已经连接测试成功的聊天模型；
- Empty response 设置为：当前资料未覆盖该问题，我可以为你转人工客服确认；
- 不要留空 Empty response，否则无召回内容时模型可能自由发挥；
- 系统提示词要求：只依据关联知识库回答，动态课时、班级名额和退费金额必须转业务工具或人工，不泄露教师私人联系方式和其他学员信息；
- 开启引用或 Reference 返回，便于 uPil 在 complete.sources 中展示来源摘要。

创建后只在 RAGFlow 控制台查看并复制以下两个值到用户本地环境变量：

- API Key；
- Chat ID。

不要把这两个值粘贴到对话、Git、README 或项目日志中。

## E. 本轮反馈格式

完成聊天模型配置后，只需回复以下非敏感信息：

聊天模型：成功或失败（失败原因）
Embedding：成功
Dataset：尚未创建

不要回复 API Key、密码、完整私密 Base URL 参数或 Chat ID。A 步通过后再继续 B 步。


## F. Ollama + BGE-M3 本地验证记录

本轮已完成 Ollama + BGE-M3 的本地安装和接口联调：

- Ollama 版本：0.33.2。
- 模型名称：bge-m3:latest。
- 模型能力：embedding。
- 向量维度：1024。
- 本机接口：POST http://localhost:11434/api/embed，返回 HTTP 200。
- OpenAI 兼容接口：POST http://localhost:11434/v1/embeddings，返回 HTTP 200。
- Docker 容器访问宿主机 Ollama：GET http://host.docker.internal:11434/api/tags，验证成功。

RAGFlow 控制台配置参数：

- Provider：Ollama。
- Model name：bge-m3。
- Model type：Embedding。
- Base URL：http://host.docker.internal:11434。

说明：命令行和 Docker 网络验证已经完成；还需要在 RAGFlow 控制台中添加该模型并点击连接测试，成功后再创建 Dataset。

# 阶段 15-A-2：家长学情报告 PDF 与 MinIO 私有交付

## 1. 阶段目标

在家长报告任务、列表、详情和所有权校验的基础上，形成可下载的正式 PDF。家长既可通过聊天自然意图生成报告，也可在报告页使用显式按钮；两个入口共用同一执行服务，不形成两套业务逻辑。

本阶段不接真实外部教育机构数据。当前版本已移除 A2A/DSH 运行链路，报告由同进程统一学情分析 Agent 使用本地固定模板生成；不执行动态代码，也不把模型输出作为统计事实。

## 2. 端到端链路

~~~text
家长聊天意图或“生成报告”按钮
  -> 认证、角色与当前学员绑定校验
  -> 自然语言周期解析，默认页面输入为“最近30天”
  -> 主系统生成脱敏 LearningReportSnapshot
  -> 统一学情分析 Agent 根据家长报告处理器生成受控 learning-report.md
  -> Markdown 白名单和权威字段逐项校验
  -> markdown-it-py 转为受控 HTML
  -> WeasyPrint 使用固定 CSS 与 Noto CJK 生成 PDF
  -> pypdf 复核文本、页数、摘要与敏感标识
  -> MinIO 独立私有桶上传
  -> PostgreSQL 只保存一个 PDF Artifact 元数据
  -> 家长按任务 ID 重新鉴权，由 FastAPI 代理下载
~~~

## 3. 周期与入口设计

请求体只有一个自然语言字段：

~~~json
{"period": "最近30天"}
~~~

页面不提供开始日期、结束日期、低课时阈值或文件格式控件。后端支持“上个月”“本月”“最近30天”“2026年8月”和明确自然语言日期范围，并把最终日期写入任务范围。页面默认“最近30天”，但用户仍可用自然语言覆盖。

显式按钮不是新的报表 Agent。聊天适合自然意图触发；按钮用于稳定发起、查看状态、失败后重新生成、历史回看和下载。两者最终都调用 `backend/app/services/report_execution.py`，共享授权、本地模板、PDF、MinIO、幂等和补偿逻辑，所以不会把多 Agent 项目扩张成后台管理系统。

## 4. Markdown 与 PDF 安全边界

共享转换器只允许标题、段落、引用、列表、粗体、斜体和行内代码等有限 token。它拒绝 HTML、脚本、代码块、Markdown 链接、图片、网络 URL、data URL 和本地文件 URL；WeasyPrint 的资源加载器也只允许读取显式配置的本地字体。

家长报告中的周期、出勤、请假、缺勤、出勤率、已完成课时、剩余课时、课程概览和已发布进度直接来自 `LearningReportSnapshot`。模板不计算、不改写统计数字，渲染前后均执行敏感信息和完整性检查。

模板版本为 `learning-report-pdf-v2`。v1 专属于历史 ReportLab 产物，升级版本可防止两种渲染器共用同一个幂等缓存键。渲染后使用 pypdf 检查：

- PDF 魔数、未加密、大小和页数上限；
- 标题、隐私说明和模板版本可提取；
- SHA-256、文件大小和页数与元数据一致；
- PDF 不包含匿名学员引用、Token、服务地址或对象存储地址。

## 5. 单产物与历史兼容

新任务只保存一个 `pdf` Artifact：数据库记录对象键、SHA-256、媒体类型、文件名、字节数和页数，PDF 字节位于 MinIO。模板 Markdown 只在当前请求内存中完成校验和转换，不再写入数据库。

为避免破坏已有数据，读取路径保留两类家长历史兼容：

- 阶段 15-A-1 的单 Markdown 报告可继续下载 Markdown；
- 旧阶段 15-A-2 的 Markdown + PDF 双产物先复核 Markdown，再返回 PDF。

兼容逻辑不能反向放宽新写入路径。教师报告不接受 Markdown 或双产物历史形态。

## 6. MinIO 与失败补偿

报告使用独立 `REPORT_PDF_BUCKET` 私有桶，对象键固定为：

~~~text
reports/{report_task_id}/{sha256}.pdf
~~~

浏览器不会获得对象键、桶名、MinIO 地址或预签名 URL。MinIO 与 PostgreSQL 无法共享事务，执行顺序为先上传、后提交 PDF 元数据；数据库失败时回滚并尽力删除已上传对象。该补偿不是严格分布式事务，outbox、补偿重试和对象对账归入 15-A-3，当前标记为“生产增强，暂缓”。

## 7. 鉴权、幂等与重试

生成、列表、详情和下载均基于服务端 `AccessContext`。家长只能访问自己当前仍绑定的孩子；即使任务创建人未变，解绑后旧报告也立即不可见。未知任务、他人任务和绑定撤销统一 404，避免资源枚举。

相同请求人、学员匿名引用、解析后周期、任务类型和模板版本生成稳定业务键。pending 任务通过条件更新唯一领取执行权，避免并发重复生成和上传；running 和 completed 任务被复用；failed/cancelled 终态创建 `_a2` 等新尝试，不复活旧记录。

下载前重新读取对象并校验摘要、大小、页数、模板文字和内部标识。响应使用 `application/pdf`、安全文件名、`Cache-Control: private, no-store` 和 `X-Content-Type-Options: nosniff`；成功后写最小下载审计。

## 8. 配置与部署

~~~env
REPORT_PDF_ENABLED=true
REPORT_PDF_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
REPORT_PDF_MAX_BYTES=5242880
REPORT_PDF_MAX_PAGES=20
REPORT_PDF_TEMPLATE_VERSION=learning-report-pdf-v2
REPORT_PDF_BUCKET=upil-reports
~~~

staging 镜像安装 WeasyPrint 所需的 Pango、Cairo、字体配置和 Noto CJK。Windows 开发机若缺少原生 DLL，应用仍可启动，实际生成时失败关闭；字段安全测试继续运行，真实渲染在 Linux 容器专项中强制验收。

## 9. 保留边界

  - 当前运行链路不包含 A2A/DSH；真实 MinIO、真实 OIDC、真实 PostgreSQL 或真实模型仍需按部署环境联调；
- 不实现 CSV、Markdown 新产物或可选格式；
- 不实现异步 worker、报告撤回、删除、保留期、版本替换和对象对账；
- 生产上线前仍需验证桶策略、TLS、Secret、迁移、备份恢复和容量。

## 10. 结论

家长报告已经形成“自然语言意图或显式按钮 -> 统一学情分析 Agent -> 确定性快照与本地模板 -> 单 PDF 私有存储 -> 当前绑定关系鉴权下载”的闭环。显式页面补足任务可见性和文件交付，个人摘要、家长报告和教师班级报告仍共享一个 Agent 边界及不同单职责处理器。

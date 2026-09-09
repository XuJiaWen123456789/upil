# 阶段 13-I-1：RAGFlow Assistant 引用配置检查

## 1. 阶段定位

本阶段属于 uPil 本地 staging 环境的 RAGFlow 真实 FAQ 链路验证，目标是确认：

1. 公开咨询 Assistant 是否绑定正确的公开咨询知识库；
2. 服务规则 Assistant 是否绑定正确的服务规则知识库；
3. 两个 Assistant 的系统提示词是否包含 {knowledge}；
4. RAGFlow 是否开启引用输出；
5. uPil SSE complete 事件能否返回真实来源，而不是伪造来源。

本阶段不修改业务代码，不重新上传文档，不删除知识库，不删除 Docker Volume。

## 2. 已完成的只读检查

| 检查项 | 结果 |
|---|---|
| staging API 健康状态 | 正常 |
| PostgreSQL、MinIO、RAGFlow、A2A 探针 | 正常 |
| 公开咨询 Assistant 知识库绑定 | 1 个，正确 |
| 服务规则 Assistant 知识库绑定 | 1 个，正确 |
| 系统提示词 {knowledge} 占位符 | 两个 Assistant 均存在 |
| 公开咨询 FAQ 真实调用 | provider=ragflow |
| 服务规则真实调用 | 已注入独立 Chat ID |
| RAGFlow 引用开关 quote | 两个 Assistant 均为关闭 |

## 3. 问题定位

当前回答内容能够正确返回，说明 RAGFlow 的检索和生成链路已经工作；但 uPil 的 sources 为空，主要原因是 Assistant 的引用输出开关关闭。

客户端传递引用请求参数只能表达调用方希望获得引用，不能替代 RAGFlow Assistant 自身的引用配置。因此，不能通过 uPil 代码伪造来源，也不能仅凭回答文本猜测来源文件。

## 4. 用户侧操作

在 RAGFlow Web 页面中分别打开以下两个 Assistant 的配置：

### 公开咨询 Assistant

- 知识库：公开咨询知识库；
- 系统提示词：保留 {knowledge}；
- Quote / 引用 / 显示引用：开启；
- 保存配置。

### 服务规则 Assistant

- 知识库：uPil-服务规则与异常处置知识库；
- 系统提示词：保留 {knowledge}；
- Quote / 引用 / 显示引用：开启；
- 保存配置。

本阶段不需要修改模型、Embedding、Chunk Size 或元数据，不需要重新上传已有文档。

## 5. 回归验证

staging API 地址：http://127.0.0.1:18000

FAQ 测试问题：编程课需要家长提前购买电脑吗？

服务规则测试问题：孩子生病请假后可以补课吗？

预期两个请求都返回 provider=ragflow，并且最后的 complete 事件中 sources 数组至少包含一个真实引用，引用标题应与对应知识库文档相关。

## 6. 风险与边界

- 引用开关打开后，来源仍可能因模型、接口版本或 RAGFlow 返回格式差异而为空，需要以接口实际响应为准；
- 不能把 Assistant 的回答内容当作已经核验的业务系统结果；
- 实时课时、班级名额、排课和订单信息仍必须走结构化业务工具；
- 当前是本地 staging 原型，不等于真实教育机构生产上线；
- 所有机构资料和业务数据仍是虚构演示数据。

## 7. 阶段完成标准

完成以下条件后，本阶段才算闭环：

1. 两个 Assistant 的引用开关均已保存为开启；
2. FAQ 与服务规则请求均由 RAGFlow 返回；
3. 两个 complete 事件均能返回非空 sources；
4. 来源文档与问题意图匹配；
5. 现有全量测试未被破坏；
6. 结果记录到项目日志和答辩问答文档。

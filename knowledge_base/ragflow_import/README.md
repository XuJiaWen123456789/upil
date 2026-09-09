# RAGFlow 分层导入包

## 用途

本目录是 uPil 本地 RAGFlow 导入的分层资料包。资料以“星河素质教育中心”作为虚构演示机构，仅用于开发、测试、答辩演示和检索质量验证，不代表真实机构政策。

本导入包采用两个 Dataset，避免把公开课程介绍、客服回答边界和异常处置规则混在同一个检索空间中：

| Dataset | 导入目录 | 主要回答范围 |
|---|---|---|
| uPil-课程与公开咨询知识库 | 01_public_consultation | 课程介绍、课程价值、适龄建议、教师与校区、装备、活动和公开 FAQ |
| uPil-服务规则与异常处置知识库 | 02_service_rules | 报名收费、请假补课、安全健康、特殊情况、服务办理和客服升级 |

media 仅保存 Markdown 中引用的卡通演示图片原件。图片是否会被 RAGFlow 自动解析，需要在实际上传后检查；不能把 Markdown 图片链接当作已经完成的多模态索引。

## 当前导入基线

- Chunk method：General
- Chunk size：256
- Overlap：0
- Embedding：Ollama bge-m3
- Similarity threshold：0.20
- Vector weight：0.30
- Full-text weight：0.70
- Rerank：首轮关闭
- Cross-language search：关闭
- Top N：5

## 导入顺序

1. 先在 RAGFlow 中检查是否已经存在同名 Dataset，不删除历史 Dataset。
2. 创建或确认 uPil-课程与公开咨询知识库，先只上传 课程介绍与适龄建议.md 和 公开咨询FAQ.md。
3. 解析完成后抽查课程标题、适龄、时长、目标和阶段收获是否在同一 Chunk 中，并执行固定问题验证。
4. 首轮验证通过后，再上传 01_public_consultation 的其余 Markdown 文件。
5. 创建或确认 uPil-服务规则与异常处置知识库，先只上传 客服升级与回答规范.md 和 服务办理FAQ.md。
6. 先验证拒答、人工升级和动态数据路由，再上传其余服务规则文件。

## 不得放入静态知识库的内容

剩余课时、出勤记录、订单余额、退款核算结果、实时班级名额、实时教师排课和学员健康隐私均属于动态或敏感数据。它们应由 uPil 的结构化业务工具、权限校验和人工审核链路处理，不能由 RAGFlow 静态文档推测。

evaluation 目录中的标准问题、边界案例和对抗样例仅用于验收，不上传到生产 Dataset。

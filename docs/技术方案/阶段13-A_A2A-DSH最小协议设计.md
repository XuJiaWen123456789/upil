# 阶段 13-A：A2A/DSH 远程学情分析子节点最小协议设计

## 1. 阶段定位

本阶段只完成协议、数据边界和故障策略设计，不连接真实 DSH 账号，不启动远程服务，也不改变现有 RAGFlow FAQ 和服务规则链路。

## 2. 为什么选择“学情分析”作为远程子节点

学情分析比公开 FAQ 更适合作为跨智能体协作示范：它需要先读取受控的结构化学员数据，再进行指标计算、趋势判断和家长可理解的总结。Supervisor 负责意图识别、权限和任务编排；远程子节点只接收脱敏后的分析输入，不直接访问主系统数据库。

这体现 A2A 的真实价值：将一个相对独立、可以单独扩缩容和审计的分析能力封装成服务，而不是把所有代码堆在一个进程中。

## 3. 业务触发范围

仅在以下场景考虑创建远程分析任务：

- 家长或老师请求“分析学习情况”“总结近期表现”“给出学习建议”；
- 请求包含已绑定学员，且已通过服务端身份与数据权限校验；
- 主系统已经取得结构化学情快照；
- 任务是只读分析，不执行报名、退费、调课、删改数据等操作。

以下场景不触发 DSH：

- 普通课程介绍、适龄建议、试听和校区咨询，继续走 RAGFlow；
- 需要实时课时、出勤明细或班级名额但尚未查到可信结果；
- 受伤、严重不适等紧急安全事件；
- 投诉、合同争议、赔偿和退费金额核算；
- 用户要求执行任意代码、访问任意文件或调用任意工具。

## 4. 角色与职责

| 组件 | 职责 | 不负责的内容 |
| --- | --- | --- |
| LangGraph Supervisor | 判断意图、校验前置条件、生成任务、等待结果、组织客服话术 | 不把原始数据库连接交给远程节点 |
| uPil 工具层 | 按权限读取结构化学情快照、脱敏、设置超时和重试 | 不信任模型传入的身份字段 |
| A2A Client | 发送标准化任务、传递关联 ID、接收任务状态和 Artifact | 不绕过业务工具白名单 |
| DSH 远程子节点 | 在沙箱中做统计、趋势分析和报告生成 | 不直接访问生产数据库，不返回未校验的敏感原文 |
| 人工客服 | 处理超时、结果冲突、隐私争议和高风险业务 | 不把 DSH 结果视为最终业务裁决 |

## 5. 最小任务体

当前建议将 A2A Task 设计成“最小可用字段”，而不是把完整会话或数据库对象发送出去：

    {
      "task_id": "task_demo_001",
      "parent_task_id": null,
      "correlation_id": "req_demo_001",
      "skill": "learning_summary",
      "input": {
        "learner_ref": "learner_ref_demo_001",
        "period": "recent_30_days",
        "metrics": ["attendance_rate", "completed_hours", "progress_notes"],
        "snapshot": {
          "attendance_rate": 0.92,
          "completed_hours": 8,
          "progress_notes": ["能够完成基础组合", "需要加强节奏练习"]
        }
      },
      "constraints": {
        "max_runtime_seconds": 10,
        "output_format": "markdown_report",
        "no_external_network": true,
        "no_side_effects": true
      }
    }

说明：learner_ref 是不可逆或不可推断真实身份的演示引用，不使用姓名、手机号、身份证号、住址、订单号或完整聊天记录。生产实现中应由服务端生成脱敏引用，不能由用户或模型自行指定真实主键。

## 6. 返回结果与 Artifact

DSH 至少返回以下状态之一：working、completed、failed、cancelled。

完成时返回：

    {
      "task_id": "task_demo_001",
      "correlation_id": "req_demo_001",
      "status": "completed",
      "artifacts": [
        {
          "artifact_id": "artifact_demo_001",
          "media_type": "text/markdown",
          "name": "learning-summary.md",
          "content_ref": "internal://artifacts/artifact_demo_001"
        }
      ],
      "quality": {
        "validated": true,
        "contains_personal_data": false
      }
    }

Artifact 只通过受控引用返回，不能把任意本地路径、可执行脚本、密钥或未脱敏原始数据返回给前端。客服层还要做一次格式、隐私和指标一致性校验，再组织最终答复。

## 7. 超时、重试和人工兜底

- 单次远程任务设置较短超时，例如 10 秒；
- 只对网络暂时失败或明确可重试错误重试，最多 2 次；
- 同一 task_id 或幂等键不能重复产生副作用；
- 结果缺少 Artifact、指标无法校验或含敏感信息时，视为失败；
- 连续失败后返回“分析服务暂时不可用”，并根据业务需要登记人工工单；
- DSH 不可替代安全处置、教务事实、订单核算和人工责任判断。

## 8. 当前不做的内容

- 不实现完整 A2A Server/Client SDK；
- 不引入真实 DSH 账号或远程 API Key；
- 不让 DSH 直接连接 PostgreSQL、RAGFlow、MinIO 或 Docker Socket；
- 不开放任意代码执行 HTTP 接口；
- 不把本阶段的模拟结果包装成真实机构生产数据。

## 9. 答辩表达

本项目采用 A2A 的重点不是“多调用一个接口”，而是把学情分析从主客服编排中解耦为一个有明确输入、输出、权限和故障边界的远程能力。这样未来可以独立部署和扩缩容，也可以对任务、产物和失败进行审计；同时通过脱敏和只读约束，避免远程智能体直接接触学员隐私和核心业务系统。

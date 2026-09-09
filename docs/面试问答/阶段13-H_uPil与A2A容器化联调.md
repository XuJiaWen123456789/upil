# 阶段 13-H 答辩与面试问答：容器化联调

## Q1：为什么不直接在宿主机运行，而要增加 staging 容器环境？

**答：** 宿主机运行只能证明“我的电脑能启动”，不能证明服务发现、环境变量、端口边界和依赖顺序正确。staging 用 Python 3.11 镜像复现运行时，把 API 与 A2A 子服务放到独立容器和 Docker 网络中，能够提前发现本机环境差异，同时保留开发环境的快速迭代能力。

## Q2：A2A 子服务为什么不映射到宿主机端口？

**答：** 它是内部能力，不需要直接接受浏览器或局域网请求。只加入 `upil_network` 并由 API 通过服务名访问，可以缩小攻击面；API 负责入口鉴权、任务边界和降级，子服务再校验内部服务令牌。

## Q3：为什么要使用非 root 用户？

**答：** 如果应用进程被利用，root 权限会扩大文件、进程和系统资源的影响范围。镜像中创建 uid 10001 的 `upil` 用户，并配合 `no-new-privileges`、`cap_drop: ALL`，实现最小权限运行。它不是完整安全方案，但属于容器上线的基础防线。

## Q4：为什么依赖健康接口是 degraded，而 API health 仍然是 ok？

**答：** 两个接口语义不同。`health` 只检查 API 进程是否存活；`health/dependencies` 检查数据库、MinIO、RAGFlow 和 A2A。可选依赖失败时不能把进程存活误报为全部业务可用，因此允许 API 返回 ok，同时把依赖状态标为 degraded，让发布或监控系统决定是否阻断。

## Q5：MinIO 探针为什么会出现 InvalidAccessKeyId？

**答：** 容器网络是通的，健康端点也能返回 200，但 staging 使用的 S3 凭据与根 Compose 创建 MinIO 时的 root 凭据不一致。修复为使用同一组本机凭据后，API 容器内的只读 `list_buckets` 探针通过。这个案例说明“服务可达”和“凭据正确”必须分开诊断。

## Q6：本次能否说已经实现真实 A2A 生产能力？

**答：** 只能说完成了本地跨容器 A2A 风格协议联调：有独立子服务、版本化任务合同、令牌校验、幂等、超时重试和数据库降级。当前分析器仍是受控 Mock，尚未接入官方 A2A SDK、真实 DeepSeekHarness 或生产数据，简历应写“生产化约束 staging 原型”，不能写成真实生产上线。

## Q7：为什么 FAQ 没有返回 RAGFlow 结果？

**答：** staging 环境的 RAGFlow Chat ID 尚未注入，所以 FAQ 走离线安全回退；RAGFlow 服务本身仍由另一套 Compose 管理。下一步需要在本机 `.env.staging` 填入有效的 API Key 和对应 Assistant/Chat ID，再执行真实 FAQ 链路验证，密钥不能写入仓库、日志或答辩文档。

## Q8：为什么不执行 `docker compose down -v` 清理环境？

**答：** 根 Compose 管理 PostgreSQL、MinIO、RAGFlow 等有状态服务和数据卷，`-v` 可能删除演示数据或知识库相关数据。staging 只重建 API/A2A 自己的容器，不删除外部数据卷；清理必须先确认目标 Compose、容器和卷的归属。

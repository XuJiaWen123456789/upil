# 阶段 14-C：OIDC/JWT 认证与外部身份映射

## 1. 阶段目标

本阶段在阶段 14-B 可信网关 Header 边界之外，增加 uPil 直接验证 OIDC Bearer JWT
的生产接入方式。目标是让所有业务接口只消费服务端生成的 `AccessContext`，彻底忽略
生产请求中的 `actor_role`、`actor_user_id` 等开发期模拟身份。

当前交付范围是 OAuth2 Resource Server 侧能力，不包含真实身份提供方部署、登录页、
MFA、用户目录同步或生产发布。

## 2. 威胁模型

- 客户端伪造角色或用户编号，越权读取学员、班级和媒体数据。
- 接受 `none`、`HS256` 或 Header 指定的任意算法，形成算法降级攻击。
- 只验签但不校验 `issuer`、`audience`、过期时间和主体声明。
- 直接把 JWT 中的 `role=admin`、其他高权限声明或 `campus_id` 当作业务权限。
- 按可变邮箱映射本地用户，或首次登录时自动创建高权限账号。
- 攻击者连续提交随机 `kid`，迫使服务反复访问 IdP 的 JWKS 端点。
- 身份库或 JWKS 服务故障时回退到 Demo 身份。
- 认证失败日志记录完整 Token、密钥或内部数据库异常。

## 3. Resource Server 定位

uPil 不负责验证用户名和密码，不保存 IdP 密码，也不签发访问令牌。用户先在
Keycloak、Auth0 或企业 SSO 完成登录，客户端取得面向 `upil-api` 的 Access Token，
再以 `Authorization: Bearer <token>` 调用 uPil。

这种定位将职责拆成三层：

| 层次 | 职责 | 可信数据来源 |
| --- | --- | --- |
| IdP | 登录、密码策略、MFA、Token 签发 | 身份目录 |
| uPil 认证层 | JWT 验签、标准声明校验、外部身份映射 | OIDC 配置、JWKS、映射表 |
| uPil 授权层 | 家长绑定、教师授课关系、有效报名关系与教师校区隔离 | 本地业务数据库 |

## 4. 三种认证模式

| 模式 | 用途 | 身份入口 | 生产约束 |
| --- | --- | --- | --- |
| `demo` | 本地开发与测试 | 请求中的模拟字段 | `APP_ENV=production` 时拒绝启动 |
| `trusted_headers` | 认证网关后的内网 API | 网关 Header + 共享密钥 | 网关清洗 Header、网络隔离、至少 32 字符密钥 |
| `oidc_jwt` | uPil 直接作为 Resource Server | Bearer JWT | 完整 OIDC 参数、HTTPS issuer/JWKS、非对称算法 |

生产模板默认使用 `oidc_jwt`。可信 Header 仍作为已有企业 API 网关时的可选模式，
两种模式最终都会生成同一个 `AccessContext`，因此业务授权和 LangGraph 无需分叉。

## 5. JWT 验证流程

1. 只接受格式唯一的 `Authorization: Bearer` Header。
2. 无验签读取 JOSE Header，校验 `alg` 位于服务端白名单且 `kid` 格式有效。
3. 从配置的 JWKS URI 取得候选公钥，按 `kid`、`use=sig` 和算法唯一选择。
4. 使用 PyJWT 验证签名，并校验 `iss`、`aud`、`exp`、`iat` 和主体声明。
5. 使用经过验证的 `issuer + subject` 查询启用的外部身份映射。
6. 回查本地用户，读取启用状态、角色和校区范围，生成不可变 `AccessContext`。
7. 业务授权层继续校验家长学员绑定，或教师授课班级、有效报名关系和教师校区范围。

失败响应统一脱敏：无效凭据返回 `401` 和 `WWW-Authenticate: Bearer`；JWKS 或身份库
不可用返回 `503`。日志只写固定原因码，不记录 Token、数据库连接串或异常正文。

## 6. JWKS 缓存与密钥轮换

JWKS 只包含公钥，可以在进程内按 URI 缓存。缓存 TTL 默认 300 秒，响应正文限制为
1 MiB，Key 数量限制为 100，HTTP 客户端禁止自动跟随重定向。

密钥轮换时，新 Token 的 `kid` 可能不在旧缓存中。服务会强制刷新一次 JWKS。普通
缓存更新时间与强制刷新时间分开记录，因此刚完成普通拉取也能立即恢复真实轮换；只有
未知 `kid` 触发的强制刷新进入 30 秒冷却，防止随机 `kid` 造成出站请求放大。

当前缓存是单进程内存结构。多 Worker 各自维护缓存，会产生少量重复 JWKS 请求。生产
可接受该权衡，也可在网关或内部代理层缓存公钥；若引入共享缓存，仍需保留本地短缓存
和故障处理，不能让 Redis 成为每次认证的强依赖。

## 7. 外部身份映射

OIDC 的 `sub` 只在同一 `issuer` 内唯一，因此映射主键必须是：

```text
(issuer, subject) -> local user_id
```

数据库同时约束同一 issuer 下一个本地用户只能绑定一个 subject。系统不按邮箱映射，
不假设 `sub` 等于本地用户编号，也不在第一次登录时自动创建用户。运维人员需先通过受控
流程创建家长或教师本地账号，再使用 `scripts/manage_external_identity.py` 显式绑定或停用映射。
该脚本拒绝为历史管理员或其他未支持角色重新建立登录入口。

JWT 中的角色、组织和校区声明不参与最终授权。本地 `users` 表只承认 `parent` 与 `teacher`，
并决定账号状态及教师校区范围，
从而避免 IdP 声明配置错误或 Token 注入扩大业务权限。

## 8. 数据库迁移与运维

PostgreSQL 增量脚本位于：

```text
infra/production/migrations/001_create_external_identities.sql
```

上线时应由发布系统在事务中执行并记录迁移版本，不能依赖 SQLAlchemy `create_all()`
修改既有生产表。映射命令只接收 issuer、subject 和已存在的本地 user_id；数据库地址
默认从环境变量读取，避免把密码写入命令历史。停用操作保留记录，便于后续审计。

## 9. 状态码约定

| 状态码 | 含义 | 示例 |
| --- | --- | --- |
| `401` | 身份未建立或凭据无效 | Token 过期、签名错误、映射缺失、账号停用 |
| `403` | 身份有效但不允许执行动作 | 家长尝试上传或审核机构媒体 |
| `404` | 资源不存在或无权观察其存在 | 家长读取未绑定学员、教师跨班查询 |
| `503` | 认证依赖或权限配置不可用 | JWKS 超时、身份库故障、教师缺少校区范围 |

## 10. 配置基线

```dotenv
APP_ENV=production
AUTH_MODE=oidc_jwt
AUTH_OIDC_ISSUER=https://identity.example.com/realms/upil
AUTH_OIDC_AUDIENCE=upil-api
AUTH_OIDC_JWKS_URI=https://identity.example.com/realms/upil/protocol/openid-connect/certs
AUTH_OIDC_ALGORITHMS=RS256
AUTH_OIDC_SUBJECT_CLAIM=sub
AUTH_OIDC_JWKS_CACHE_SECONDS=300
AUTH_OIDC_CLOCK_SKEW_SECONDS=30
AUTH_OIDC_HTTP_TIMEOUT_SECONDS=3
```

真实值必须由部署平台注入。仓库模板只声明变量，不保存真实 Token、客户端密钥或用户密码。

## 11. 验证范围

自动化测试使用运行时生成的临时 RSA 私钥和内存 JWKS，不访问真实 IdP。覆盖有效 Token、
过期时间、错误 issuer/audience/签名/kid、算法降级、角色伪造、映射缺失或停用、用户停用、
教师校区范围缺失、历史管理员拒绝、依赖故障脱敏、HTTP 入口集成、JWKS 格式限制和轮换冷却。

## 12. 当前边界

- 未部署真实 Keycloak、Auth0 或企业 SSO，也未完成真实机构联调。
- 未实现登录 UI、Authorization Code + PKCE 前端流程和 MFA。
- 未实现 SCIM、Webhook 或定时任务形式的用户生命周期同步。
- 未实现 Token 主动撤销、黑名单或高风险操作的即时会话终止。
- 尚未建立完整 Alembic 版本链，当前仅提供显式 PostgreSQL 增量脚本。
- 尚未增加认证成功率、JWKS 刷新和失败原因的 Prometheus 指标及告警。

因此当前准确表述是：完成 Resource Server 侧 OIDC/JWT 验证、外部身份映射、统一授权
接入及本地自动化验证；不能表述为真实机构统一身份系统已经上线。

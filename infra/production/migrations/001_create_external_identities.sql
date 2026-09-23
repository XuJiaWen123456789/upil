-- 阶段 14-C：OIDC 外部身份到 uPil 本地账号的映射表。
--
-- 执行前提：users 表已经存在。生产发布工具应在事务中执行本文件，并在
-- 成功后记录迁移版本；不要使用应用启动时的 create_all 代替增量迁移。

BEGIN;

CREATE TABLE IF NOT EXISTS external_identities (
    issuer VARCHAR(512) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_external_identities PRIMARY KEY (issuer, subject),
    CONSTRAINT fk_external_identities_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT uq_external_identity_issuer_user UNIQUE (issuer, user_id)
);

CREATE INDEX IF NOT EXISTS ix_external_identities_user_id
    ON external_identities (user_id);

COMMIT;

-- 阶段 14-E：教师媒体上传与审核职责分离。
--
-- 本迁移只扩展现有 parent/teacher 双角色模型，不创建管理员或校区运营角色。
-- 应由生产发布流程按版本执行；不要依赖 ORM create_all 修改既有数据库。

BEGIN;

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id VARCHAR(64) NOT NULL,
    permission VARCHAR(64) NOT NULL,
    granted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_user_permissions PRIMARY KEY (user_id, permission),
    CONSTRAINT fk_user_permissions_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 字段先保持可空以兼容迁移前的历史媒体。应用只允许带真实 uploaded_by 的
-- 新素材进入审核流程，历史空值记录必须经过人工数据治理后才能复核。
ALTER TABLE media_assets
    ADD COLUMN IF NOT EXISTS uploaded_by VARCHAR(64)
        REFERENCES users (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(64)
        REFERENCES users (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS review_comment TEXT;

CREATE INDEX IF NOT EXISTS ix_media_assets_uploaded_by
    ON media_assets (uploaded_by);

CREATE INDEX IF NOT EXISTS ix_media_assets_reviewed_by
    ON media_assets (reviewed_by);

-- PostgreSQL 的 ADD CONSTRAINT 没有通用 IF NOT EXISTS，使用系统目录检查使
-- 迁移在灾难恢复或发布重试时保持幂等。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_media_assets_review_status'
    ) THEN
        ALTER TABLE media_assets
            ADD CONSTRAINT ck_media_assets_review_status
            CHECK (review_status IN ('pending', 'approved', 'rejected'));
    END IF;
END
$$;

COMMIT;

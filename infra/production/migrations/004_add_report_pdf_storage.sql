-- 阶段 15-A-2：学情报告 PDF 私有对象存储元数据。
-- PDF 字节不进入 PostgreSQL；数据库只保存完整性校验和与 MinIO 私有对象键。

BEGIN;

ALTER TABLE report_artifacts
    ALTER COLUMN content DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS object_key VARCHAR(500),
    ADD COLUMN IF NOT EXISTS media_type VARCHAR(100),
    ADD COLUMN IF NOT EXISTS filename VARCHAR(255),
    ADD COLUMN IF NOT EXISTS size_bytes INTEGER,
    ADD COLUMN IF NOT EXISTS page_count INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_report_artifact_task_type'
    ) THEN
        ALTER TABLE report_artifacts
            ADD CONSTRAINT uq_report_artifact_task_type
            UNIQUE (report_task_id, artifact_type);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_report_artifact_storage_shape'
    ) THEN
        ALTER TABLE report_artifacts
            ADD CONSTRAINT ck_report_artifact_storage_shape CHECK (
                (artifact_type = 'markdown' AND content IS NOT NULL)
                OR
                (artifact_type = 'pdf' AND content IS NULL
                    AND object_key IS NOT NULL
                    AND media_type = 'application/pdf'
                    AND filename IS NOT NULL
                    AND size_bytes > 0
                    AND page_count > 0)
            );
    END IF;
END
$$;

COMMIT;

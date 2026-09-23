-- 项目收尾：增加受治理的结构化长期记忆。
-- 只保存用户明确要求记住，或由保守规则高置信度识别的低敏感稳定偏好；
-- 联系方式、课时、出勤、名额、报告状态和整段聊天原文均不属于本表边界。

BEGIN;

CREATE TABLE IF NOT EXISTS agent_structured_memories (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL,
    owner_role VARCHAR(32) NOT NULL,
    learner_id VARCHAR(64),
    -- scope_key 是租户、用户、角色、学员和字段的不可读哈希，既用于幂等，
    -- 也规避 learner_id 为 NULL 时不同数据库唯一约束语义不一致的问题。
    scope_key VARCHAR(64) NOT NULL,
    memory_type VARCHAR(32) NOT NULL,
    memory_key VARCHAR(64) NOT NULL,
    memory_value JSON NOT NULL,
    status VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source_conversation_id VARCHAR(64),
    source_message_id VARCHAR(128),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    invalidated_at TIMESTAMP,
    deleted_at TIMESTAMP,
    CONSTRAINT ck_agent_memory_type
        CHECK (memory_type IN ('structured_preference')),
    CONSTRAINT ck_agent_memory_status
        CHECK (status IN ('active', 'invalidated', 'deleted', 'expired')),
    CONSTRAINT ck_agent_memory_version CHECK (version >= 1),
    CONSTRAINT ck_agent_memory_confidence
        CHECK (confidence >= 0 AND confidence <= 1)
);

-- 同一完整作用域在任一时刻只能有一个有效版本；旧值通过 invalidated
-- 状态保留，供冲突审计和用户主动恢复使用。
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memory_active_scope_key
    ON agent_structured_memories(scope_key)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_agent_memory_owner_scope
    ON agent_structured_memories(tenant_id, owner_user_id, owner_role);

CREATE INDEX IF NOT EXISTS ix_agent_memory_learner_scope
    ON agent_structured_memories(tenant_id, learner_id);

CREATE INDEX IF NOT EXISTS ix_agent_structured_memories_status
    ON agent_structured_memories(status);

COMMIT;

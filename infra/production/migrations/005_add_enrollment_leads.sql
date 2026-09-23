-- 阶段 15-C：对话式试听与报名线索闭环。
-- 只建立销售顾问老师跟进所需数据，不创建运营账号、漏斗或 CRM 集成。

BEGIN;

-- 产品范围已取消运营端。若测试环境曾执行早期草案，迁移时同步撤销
-- 运营权限并停用历史演示账号，销售顾问仍使用 teacher + lead_followup。
DELETE FROM user_permissions
WHERE permission = 'lead_analytics' OR user_id = 'T1005';
UPDATE users SET is_active = FALSE WHERE id = 'T1005';

CREATE TABLE IF NOT EXISTS enrollment_leads (
    id VARCHAR(64) PRIMARY KEY,
    deduplication_key VARCHAR(64) NOT NULL,
    parent_id VARCHAR(64) NOT NULL REFERENCES users(id),
    learner_id VARCHAR(64) REFERENCES learners(id) ON DELETE SET NULL,
    course_name VARCHAR(100) NOT NULL,
    interest_type VARCHAR(24) NOT NULL,
    strength VARCHAR(16) NOT NULL,
    destination VARCHAR(24) NOT NULL,
    status VARCHAR(32) NOT NULL,
    conversation_ref VARCHAR(64) NOT NULL,
    evidence_codes JSON NOT NULL DEFAULT '[]',
    contact_type VARCHAR(16),
    contact_ciphertext TEXT,
    contact_fingerprint VARCHAR(64),
    contact_masked VARCHAR(120),
    contact_consent_at TIMESTAMP,
    assigned_advisor_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_enrollment_lead_interest_type
        CHECK (interest_type IN ('trial', 'enrollment', 'unknown')),
    CONSTRAINT ck_enrollment_lead_strength
        CHECK (strength IN ('low', 'medium', 'high')),
    CONSTRAINT ck_enrollment_lead_destination
        CHECK (destination IN ('lead_pool', 'advisor_queue')),
    CONSTRAINT ck_enrollment_lead_status CHECK (status IN (
        'open', 'awaiting_contact_consent', 'ready_for_followup', 'contacted',
        'trial_scheduled', 'enrolled', 'closed_won', 'closed_lost', 'withdrawn'
    )),
    CONSTRAINT ck_enrollment_lead_contact_shape CHECK (
        (contact_type IS NULL AND contact_ciphertext IS NULL
            AND contact_fingerprint IS NULL AND contact_masked IS NULL
            AND contact_consent_at IS NULL)
        OR
        (contact_type IN ('phone', 'email') AND contact_ciphertext IS NOT NULL
            AND contact_fingerprint IS NOT NULL AND contact_masked IS NOT NULL
            AND contact_consent_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_enrollment_leads_parent_id
    ON enrollment_leads(parent_id);
CREATE INDEX IF NOT EXISTS ix_enrollment_leads_destination_updated
    ON enrollment_leads(destination, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_enrollment_leads_assigned_advisor
    ON enrollment_leads(assigned_advisor_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_enrollment_lead_open_scope
    ON enrollment_leads(deduplication_key)
    WHERE status NOT IN ('closed_won', 'closed_lost', 'withdrawn');

CREATE TABLE IF NOT EXISTS lead_follow_ups (
    id SERIAL PRIMARY KEY,
    lead_id VARCHAR(64) NOT NULL REFERENCES enrollment_leads(id) ON DELETE CASCADE,
    advisor_id VARCHAR(64) NOT NULL REFERENCES users(id),
    action VARCHAR(32) NOT NULL,
    result VARCHAR(32) NOT NULL,
    note TEXT,
    next_follow_up_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_lead_follow_up_action CHECK (
        action IN ('claim', 'contact', 'schedule_trial', 'confirm_enrollment', 'close')
    ),
    CONSTRAINT ck_lead_follow_up_result CHECK (
        result IN ('claimed', 'reached', 'unreachable', 'declined', 'scheduled',
                   'cancelled', 'enrolled', 'won', 'lost')
    )
);

CREATE INDEX IF NOT EXISTS ix_lead_follow_ups_lead_created
    ON lead_follow_ups(lead_id, created_at);

COMMIT;

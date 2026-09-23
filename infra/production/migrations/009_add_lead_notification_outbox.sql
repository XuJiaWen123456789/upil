-- 招生线索外部通知 Transactional Outbox。
-- 飞书只是提醒渠道；线索状态和顾问操作仍以 enrollment_leads 为事实源。

BEGIN;

CREATE TABLE IF NOT EXISTS lead_notification_outbox (
    id VARCHAR(64) PRIMARY KEY,
    lead_id VARCHAR(64) NOT NULL REFERENCES enrollment_leads(id) ON DELETE CASCADE,
    event_type VARCHAR(48) NOT NULL,
    channel VARCHAR(24) NOT NULL,
    payload_json JSON NOT NULL DEFAULT '{}',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMP,
    last_error_code VARCHAR(48),
    intent_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_lead_notification_event_type CHECK (event_type IN (
        'medium_intent_created', 'high_intent_waiting_contact', 'contact_authorized'
    )),
    CONSTRAINT ck_lead_notification_channel CHECK (channel IN ('feishu')),
    CONSTRAINT ck_lead_notification_status CHECK (status IN (
        'pending', 'sending', 'retry', 'sent', 'failed'
    )),
    CONSTRAINT uq_lead_notification_idempotency UNIQUE (
        lead_id, event_type, channel, intent_version
    )
);

CREATE INDEX IF NOT EXISTS ix_lead_notification_outbox_lead_id
    ON lead_notification_outbox(lead_id);
CREATE INDEX IF NOT EXISTS ix_lead_notification_outbox_due
    ON lead_notification_outbox(status, next_retry_at, created_at);

COMMIT;

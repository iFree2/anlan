CREATE TABLE IF NOT EXISTS anlan_v2.perception_events (
    receipt_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    source_id text NOT NULL,
    event_id text NOT NULL,
    body_hash text NOT NULL,
    document jsonb NOT NULL,
    result jsonb,
    UNIQUE (tenant_id, user_id, source_id, event_id)
);
CREATE TABLE IF NOT EXISTS anlan_v2.perception_heads (
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    source_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    observed_at timestamptz NOT NULL,
    receipt_id text NOT NULL REFERENCES anlan_v2.perception_events(receipt_id),
    PRIMARY KEY (tenant_id, user_id, source_id)
);
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (5) ON CONFLICT DO NOTHING;

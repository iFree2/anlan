CREATE TABLE IF NOT EXISTS anlan_v2.perception_reviews (
    review_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    receipt_id text NOT NULL REFERENCES anlan_v2.perception_events(receipt_id),
    request_id text NOT NULL,
    document jsonb NOT NULL,
    result jsonb,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    feedback jsonb,
    UNIQUE (tenant_id, user_id, receipt_id, request_id)
);
CREATE TABLE IF NOT EXISTS anlan_v2.perception_feedback (
    review_id text NOT NULL REFERENCES anlan_v2.perception_reviews(review_id),
    request_id text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (review_id, request_id)
);
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (7) ON CONFLICT DO NOTHING;

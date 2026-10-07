-- Database order is independent of the fixed synthetic business clock.
ALTER TABLE anlan_v2.perception_events ADD COLUMN IF NOT EXISTS console_order bigserial;
ALTER TABLE anlan_v2.perception_reviews ADD COLUMN IF NOT EXISTS console_order bigserial;
CREATE INDEX IF NOT EXISTS console_events_scope_order ON anlan_v2.perception_events
    (tenant_id,user_id,(document->'binding'->>'task_id'),console_order DESC);
CREATE INDEX IF NOT EXISTS console_reviews_scope_order ON anlan_v2.perception_reviews
    (tenant_id,user_id,receipt_id,console_order DESC);
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (9) ON CONFLICT DO NOTHING;

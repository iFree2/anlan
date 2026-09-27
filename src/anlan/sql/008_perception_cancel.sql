ALTER TABLE anlan_v2.perception_reviews
    ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false;
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (8) ON CONFLICT DO NOTHING;

-- Explicit administrator policy; absence preserves the original bounded behavior.
-- No attempt, authorization limit, or package history is reset or relabelled.
CREATE TABLE IF NOT EXISTS anlan_v2.model_call_policies (
    authorization_id text PRIMARY KEY
        REFERENCES anlan_v2.model_budget_authorizations(authorization_id),
    limits_enforced boolean NOT NULL DEFAULT true,
    reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 500),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (18) ON CONFLICT DO NOTHING;

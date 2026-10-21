-- Cumulative package contract for the conversation release; no attempt or limit reset.
ALTER TABLE anlan_v2.model_budget_attempts
    DROP CONSTRAINT IF EXISTS model_budget_attempts_work_package_check;
ALTER TABLE anlan_v2.model_budget_attempts
    ADD CONSTRAINT model_budget_attempts_work_package_check
    CHECK (
        work_package ~ '^P[1-7]-WP[0-9]{2}$'
        OR work_package IN ('P8-WP03', 'P8-WP04', 'P11-WP01', 'P11-WP02')
    );
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (15) ON CONFLICT DO NOTHING;

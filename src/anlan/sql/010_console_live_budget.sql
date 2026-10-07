-- Extend only the explicitly authorized console package; no budget data changes.
ALTER TABLE anlan_v2.model_budget_attempts
    DROP CONSTRAINT IF EXISTS model_budget_attempts_work_package_check;
ALTER TABLE anlan_v2.model_budget_attempts
    ADD CONSTRAINT model_budget_attempts_work_package_check
    CHECK (work_package ~ '^P[1-7]-WP[0-9]{2}$' OR work_package = 'P8-WP03');

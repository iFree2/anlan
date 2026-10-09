-- Add the isolated materials-v2 release package without altering prior attempts or limits.
ALTER TABLE anlan_v2.model_budget_attempts
    DROP CONSTRAINT IF EXISTS model_budget_attempts_work_package_check;
ALTER TABLE anlan_v2.model_budget_attempts
    ADD CONSTRAINT model_budget_attempts_work_package_check
    CHECK (work_package ~ '^P[1-7]-WP[0-9]{2}$' OR work_package IN ('P8-WP03', 'P8-WP04'));

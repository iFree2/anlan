CREATE TABLE IF NOT EXISTS anlan_v2.model_budget_authorizations (
    authorization_id text PRIMARY KEY,
    total_limit integer NOT NULL CHECK (total_limit BETWEEN 1 AND 100),
    package_limit integer NOT NULL CHECK (package_limit BETWEEN 1 AND 10),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS anlan_v2.model_budget_attempts (
    attempt_id uuid PRIMARY KEY,
    authorization_id text NOT NULL REFERENCES anlan_v2.model_budget_authorizations,
    work_package text NOT NULL CHECK (work_package ~ '^P[1-7]-WP[0-9]{2}$'),
    run_id text NOT NULL,
    status text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'succeeded', 'failed')),
    usage jsonb,
    error text,
    reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    CHECK ((status = 'reserved' AND finished_at IS NULL AND usage IS NULL AND error IS NULL)
           OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS model_budget_attempts_authorization_package
    ON anlan_v2.model_budget_attempts (authorization_id, work_package);

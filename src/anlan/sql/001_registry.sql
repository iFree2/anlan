CREATE TABLE IF NOT EXISTS anlan_schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS anlan_tasks (
    task_id text PRIMARY KEY,
    thread_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    mode text NOT NULL,
    contract_version text NOT NULL,
    initial_state jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS anlan_operations (
    task_id text NOT NULL REFERENCES anlan_tasks(task_id),
    request_id text NOT NULL,
    run_id text NOT NULL UNIQUE,
    kind text NOT NULL CHECK (kind IN ('start', 'resume')),
    expected_revision integer NOT NULL,
    fields jsonb NOT NULL,
    result jsonb,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    PRIMARY KEY (task_id, request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS anlan_one_pending_operation
    ON anlan_operations(task_id) WHERE result IS NULL;
INSERT INTO anlan_schema_migrations(version) VALUES (1) ON CONFLICT DO NOTHING;

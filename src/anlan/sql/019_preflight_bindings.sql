-- B1 is additive and explicitly initialized. No existing application is gated here.
CREATE TABLE IF NOT EXISTS anlan_v2.precheck_policies (
    task_id text PRIMARY KEY REFERENCES anlan_v2.anlan_tasks(task_id),
    tenant_id text NOT NULL,
    required boolean NOT NULL,
    legacy_completed boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (required <> legacy_completed),
    FOREIGN KEY (tenant_id,task_id)
        REFERENCES anlan_v2.collaboration_applications(tenant_id,task_id)
);

CREATE TABLE IF NOT EXISTS anlan_v2.precheck_binding_versions (
    tenant_id text NOT NULL,
    task_id text NOT NULL REFERENCES anlan_v2.anlan_tasks(task_id),
    binding_revision integer NOT NULL CHECK (binding_revision >= 1),
    material_revision_at_confirmation integer NOT NULL
        CHECK (material_revision_at_confirmation >= 1),
    worker_id text NOT NULL CHECK (worker_id ~ '^[a-zA-Z0-9_-]{1,100}$'),
    qualification_type text NOT NULL CHECK (qualification_type ~ '^[a-zA-Z0-9_-]{1,100}$'),
    area_id text NOT NULL CHECK (area_id ~ '^[a-zA-Z0-9_-]{1,100}$'),
    confirmed_by_user_id text NOT NULL
        CHECK (char_length(confirmed_by_user_id) BETWEEN 1 AND 500
            AND char_length(btrim(confirmed_by_user_id)) >= 1),
    confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,task_id,binding_revision),
    FOREIGN KEY (tenant_id,task_id)
        REFERENCES anlan_v2.collaboration_applications(tenant_id,task_id)
);

CREATE TABLE IF NOT EXISTS anlan_v2.precheck_binding_heads (
    task_id text PRIMARY KEY REFERENCES anlan_v2.anlan_tasks(task_id),
    tenant_id text NOT NULL,
    binding_revision integer NOT NULL CHECK (binding_revision >= 1),
    FOREIGN KEY (tenant_id,task_id,binding_revision)
        REFERENCES anlan_v2.precheck_binding_versions(tenant_id,task_id,binding_revision)
);

CREATE TABLE IF NOT EXISTS anlan_v2.precheck_binding_commands (
    tenant_id text NOT NULL,
    actor_user_id text NOT NULL CHECK (char_length(actor_user_id) BETWEEN 1 AND 500
        AND char_length(btrim(actor_user_id)) >= 1),
    request_id text NOT NULL CHECK (char_length(request_id) BETWEEN 1 AND 500
        AND char_length(btrim(request_id)) >= 1),
    task_id text NOT NULL REFERENCES anlan_v2.anlan_tasks(task_id),
    expected_material_revision integer NOT NULL CHECK (expected_material_revision >= 1),
    expected_binding_revision integer NOT NULL CHECK (expected_binding_revision >= 0),
    binding_revision integer NOT NULL CHECK (binding_revision >= 1),
    payload jsonb NOT NULL
        CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 32768),
    result jsonb NOT NULL
        CHECK (jsonb_typeof(result) = 'object' AND octet_length(result::text) <= 32768),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,actor_user_id,request_id),
    FOREIGN KEY (tenant_id,task_id,binding_revision)
        REFERENCES anlan_v2.precheck_binding_versions(tenant_id,task_id,binding_revision)
);

-- The head can advance; confirmed versions and command receipts cannot be rewritten.
CREATE OR REPLACE FUNCTION anlan_v2.precheck_binding_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'precheck binding history is immutable';
END $$;
-- PG13-compatible replacement. PrecheckStore.initialize holds its advisory lock
-- and executes this whole migration in one transaction, including both pairs.
DROP TRIGGER IF EXISTS precheck_binding_versions_immutable
    ON anlan_v2.precheck_binding_versions;
CREATE TRIGGER precheck_binding_versions_immutable
    BEFORE UPDATE OR DELETE ON anlan_v2.precheck_binding_versions
    FOR EACH ROW EXECUTE FUNCTION anlan_v2.precheck_binding_immutable();
DROP TRIGGER IF EXISTS precheck_binding_commands_immutable
    ON anlan_v2.precheck_binding_commands;
CREATE TRIGGER precheck_binding_commands_immutable
    BEFORE UPDATE OR DELETE ON anlan_v2.precheck_binding_commands
    FOR EACH ROW EXECUTE FUNCTION anlan_v2.precheck_binding_immutable();

CREATE INDEX IF NOT EXISTS precheck_binding_commands_task
    ON anlan_v2.precheck_binding_commands(tenant_id,task_id,created_at);

INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (19) ON CONFLICT DO NOTHING;

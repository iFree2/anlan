-- Durable preflight execution state.  A check result is append-only evidence.
CREATE TABLE IF NOT EXISTS anlan_v2.precheck_jobs (
    job_id text PRIMARY KEY,
    ordinal bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    tenant_id text NOT NULL,
    task_id text NOT NULL REFERENCES anlan_v2.anlan_tasks(task_id),
    material_revision integer NOT NULL CHECK (material_revision >= 1),
    binding_revision integer NOT NULL CHECK (binding_revision >= 1),
    application_version integer NOT NULL CHECK (application_version >= 1),
    actor_user_id text NOT NULL CHECK (char_length(actor_user_id) BETWEEN 1 AND 500),
    cause text NOT NULL CHECK (char_length(cause) BETWEEN 1 AND 600),
    input_snapshot jsonb NOT NULL CHECK (octet_length(input_snapshot::text) <= 32768),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed')),
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id,task_id,material_revision,binding_revision,application_version,cause),
    FOREIGN KEY (tenant_id,task_id,binding_revision)
      REFERENCES anlan_v2.precheck_binding_versions(tenant_id,task_id,binding_revision)
);
CREATE TABLE IF NOT EXISTS anlan_v2.precheck_attempts (
    attempt_id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES anlan_v2.precheck_jobs(job_id),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running','completed','expired'))
);
CREATE TABLE IF NOT EXISTS anlan_v2.precheck_results (
    check_id text PRIMARY KEY,
    job_id text NOT NULL UNIQUE REFERENCES anlan_v2.precheck_jobs(job_id),
    attempt_id text NOT NULL UNIQUE REFERENCES anlan_v2.precheck_attempts(attempt_id),
    result jsonb NOT NULL CHECK (octet_length(result::text) <= 131072),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX IF NOT EXISTS precheck_attempt_job_identity
    ON anlan_v2.precheck_attempts(job_id,attempt_id);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='precheck_result_attempt_job') THEN
        ALTER TABLE anlan_v2.precheck_results ADD CONSTRAINT precheck_result_attempt_job
            FOREIGN KEY (job_id,attempt_id)
            REFERENCES anlan_v2.precheck_attempts(job_id,attempt_id);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS precheck_jobs_claim ON anlan_v2.precheck_jobs(status, lease_until, created_at);
CREATE TABLE IF NOT EXISTS anlan_v2.precheck_recheck_commands (
    tenant_id text NOT NULL, actor_user_id text NOT NULL, request_id text NOT NULL,
    task_id text NOT NULL, payload jsonb NOT NULL,
    job_id text NOT NULL REFERENCES anlan_v2.precheck_jobs(job_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,actor_user_id,request_id),
    FOREIGN KEY (tenant_id,task_id)
        REFERENCES anlan_v2.collaboration_applications(tenant_id,task_id)
);
CREATE TABLE IF NOT EXISTS anlan_v2.precheck_cycles (
    task_id text NOT NULL REFERENCES anlan_v2.anlan_tasks(task_id),
    application_version integer NOT NULL,
    binding_revision integer NOT NULL,
    baseline jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (task_id,application_version)
);
CREATE OR REPLACE FUNCTION anlan_v2.precheck_result_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'precheck evidence history is immutable'; END $$;
CREATE OR REPLACE FUNCTION anlan_v2.precheck_job_input_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    IF TG_OP='DELETE' OR (OLD.status='completed' AND NEW.status<>'completed')
        OR ROW(OLD.job_id,OLD.ordinal,OLD.tenant_id,OLD.task_id,
        OLD.material_revision,OLD.binding_revision,OLD.application_version,
        OLD.actor_user_id,OLD.cause,OLD.input_snapshot,OLD.created_at) IS DISTINCT FROM
        ROW(NEW.job_id,NEW.ordinal,NEW.tenant_id,NEW.task_id,NEW.material_revision,
        NEW.binding_revision,NEW.application_version,NEW.actor_user_id,NEW.cause,
        NEW.input_snapshot,NEW.created_at) THEN
        RAISE EXCEPTION 'precheck input history is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION anlan_v2.precheck_attempt_history() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    IF TG_OP='DELETE' OR OLD.status<>'running' OR
        ROW(OLD.attempt_id,OLD.job_id,OLD.started_at) IS DISTINCT FROM
        ROW(NEW.attempt_id,NEW.job_id,NEW.started_at) THEN
        RAISE EXCEPTION 'precheck attempt history is immutable';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS precheck_attempt_history ON anlan_v2.precheck_attempts;
CREATE TRIGGER precheck_attempt_history BEFORE UPDATE OR DELETE ON anlan_v2.precheck_attempts
    FOR EACH ROW EXECUTE FUNCTION anlan_v2.precheck_attempt_history();
DROP TRIGGER IF EXISTS precheck_job_input_immutable ON anlan_v2.precheck_jobs;
CREATE TRIGGER precheck_job_input_immutable BEFORE UPDATE OR DELETE ON anlan_v2.precheck_jobs
    FOR EACH ROW EXECUTE FUNCTION anlan_v2.precheck_job_input_immutable();
DROP TRIGGER IF EXISTS precheck_results_immutable ON anlan_v2.precheck_results;
CREATE TRIGGER precheck_results_immutable BEFORE UPDATE OR DELETE
    ON anlan_v2.precheck_results FOR EACH ROW EXECUTE FUNCTION anlan_v2.precheck_result_immutable();
DROP TRIGGER IF EXISTS precheck_recheck_commands_immutable ON anlan_v2.precheck_recheck_commands;
CREATE TRIGGER precheck_recheck_commands_immutable BEFORE UPDATE OR DELETE
    ON anlan_v2.precheck_recheck_commands FOR EACH ROW
    EXECUTE FUNCTION anlan_v2.precheck_result_immutable();
DROP TRIGGER IF EXISTS precheck_cycles_immutable ON anlan_v2.precheck_cycles;
CREATE TRIGGER precheck_cycles_immutable BEFORE UPDATE OR DELETE ON anlan_v2.precheck_cycles
    FOR EACH ROW EXECUTE FUNCTION anlan_v2.precheck_result_immutable();
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (20) ON CONFLICT DO NOTHING;

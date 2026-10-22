-- Additive collaboration metadata; original task owner/checkpoints are unchanged.
CREATE TABLE IF NOT EXISTS anlan_v2.collaboration_applications (
    task_id text PRIMARY KEY REFERENCES anlan_v2.anlan_tasks(task_id)
        CHECK (char_length(btrim(task_id)) BETWEEN 1 AND 500),
    tenant_id text NOT NULL CHECK (char_length(btrim(tenant_id)) BETWEEN 1 AND 500),
    applicant_user_id text NOT NULL
        CHECK (char_length(btrim(applicant_user_id)) BETWEEN 1 AND 500),
    reviewer_user_id text CHECK (char_length(btrim(reviewer_user_id)) BETWEEN 1 AND 500),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','under_review','changes_requested','review_completed')),
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    submitted_material_revision integer CHECK (submitted_material_revision >= 1),
    completed_material_revision integer CHECK (completed_material_revision >= 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id,task_id),
    CHECK (reviewer_user_id IS NULL OR reviewer_user_id <> applicant_user_id),
    CHECK (
        (status = 'draft' AND reviewer_user_id IS NULL AND submitted_material_revision IS NULL)
        OR (status <> 'draft' AND reviewer_user_id IS NOT NULL
            AND submitted_material_revision IS NOT NULL)
    ),
    CHECK (
        (status = 'review_completed' AND completed_material_revision IS NOT NULL
            AND completed_material_revision = submitted_material_revision)
        OR (status <> 'review_completed' AND completed_material_revision IS NULL)
    )
);

-- Insert receipt, application update, event and notifications in ONE transaction.
-- Request identity spans tasks: compare task/action/versions/full payload on replay.
CREATE TABLE IF NOT EXISTS anlan_v2.collaboration_commands (
    tenant_id text NOT NULL CHECK (char_length(btrim(tenant_id)) BETWEEN 1 AND 500),
    actor_user_id text NOT NULL CHECK (char_length(btrim(actor_user_id)) BETWEEN 1 AND 500),
    request_id text NOT NULL CHECK (char_length(btrim(request_id)) BETWEEN 1 AND 500),
    task_id text NOT NULL CHECK (char_length(btrim(task_id)) BETWEEN 1 AND 500),
    action text NOT NULL CHECK (action IN ('submit','request_changes','resubmit','complete_review')),
    actor_role text NOT NULL CHECK (actor_role IN ('applicant','safety_manager')),
    expected_application_version integer NOT NULL CHECK (expected_application_version >= 1),
    expected_material_revision integer NOT NULL CHECK (expected_material_revision >= 1),
    payload jsonb NOT NULL
        CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 32768),
    result jsonb NOT NULL
        CHECK (jsonb_typeof(result) = 'object' AND octet_length(result::text) <= 32768),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,actor_user_id,request_id),
    FOREIGN KEY (tenant_id,task_id)
        REFERENCES anlan_v2.collaboration_applications(tenant_id,task_id),
    CHECK (
        (actor_role = 'applicant' AND action IN ('submit','resubmit'))
        OR (actor_role = 'safety_manager' AND action IN ('request_changes','complete_review'))
    )
);

CREATE TABLE IF NOT EXISTS anlan_v2.collaboration_events (
    event_id text PRIMARY KEY CHECK (char_length(btrim(event_id)) BETWEEN 1 AND 500),
    tenant_id text NOT NULL CHECK (char_length(btrim(tenant_id)) BETWEEN 1 AND 500),
    task_id text NOT NULL CHECK (char_length(btrim(task_id)) BETWEEN 1 AND 500),
    actor_user_id text NOT NULL CHECK (char_length(btrim(actor_user_id)) BETWEEN 1 AND 500),
    actor_role text NOT NULL CHECK (actor_role IN ('applicant','safety_manager')),
    action text NOT NULL CHECK (action IN (
        'submit','request_changes','resubmit','complete_review',
        'run_event_review','record_event_feedback'
    )),
    material_revision integer NOT NULL CHECK (material_revision >= 1),
    application_version integer NOT NULL CHECK (application_version >= 1),
    payload jsonb NOT NULL
        CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 32768),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id,event_id),
    FOREIGN KEY (tenant_id,task_id)
        REFERENCES anlan_v2.collaboration_applications(tenant_id,task_id),
    CHECK (
        (actor_role = 'applicant' AND action IN ('submit','resubmit'))
        OR (actor_role = 'safety_manager' AND action IN (
            'request_changes','complete_review','run_event_review','record_event_feedback'
        ))
    )
);

-- The inbox references a business event; it contains no private conversation copy.
CREATE TABLE IF NOT EXISTS anlan_v2.collaboration_notifications (
    tenant_id text NOT NULL CHECK (char_length(btrim(tenant_id)) BETWEEN 1 AND 500),
    recipient_user_id text NOT NULL
        CHECK (char_length(btrim(recipient_user_id)) BETWEEN 1 AND 500),
    event_id text NOT NULL CHECK (char_length(btrim(event_id)) BETWEEN 1 AND 500),
    ordinal bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    read_at timestamptz,
    PRIMARY KEY (tenant_id,recipient_user_id,event_id),
    FOREIGN KEY (tenant_id,event_id) REFERENCES anlan_v2.collaboration_events(tenant_id,event_id)
);

-- Bound the stored text too: trimming alone must not admit arbitrary whitespace.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE
        conrelid = 'anlan_v2.collaboration_applications'::regclass
        AND conname = 'collaboration_applications_text_bounds') THEN
        ALTER TABLE anlan_v2.collaboration_applications
            ADD CONSTRAINT collaboration_applications_text_bounds CHECK (
                greatest(char_length(task_id),char_length(tenant_id),
                    char_length(applicant_user_id),char_length(reviewer_user_id)) <= 500);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE
        conrelid = 'anlan_v2.collaboration_commands'::regclass
        AND conname = 'collaboration_commands_text_bounds') THEN
        ALTER TABLE anlan_v2.collaboration_commands
            ADD CONSTRAINT collaboration_commands_text_bounds CHECK (
                greatest(char_length(tenant_id),char_length(actor_user_id),
                    char_length(request_id),char_length(task_id)) <= 500);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE
        conrelid = 'anlan_v2.collaboration_events'::regclass
        AND conname = 'collaboration_events_text_bounds') THEN
        ALTER TABLE anlan_v2.collaboration_events
            ADD CONSTRAINT collaboration_events_text_bounds CHECK (
                greatest(char_length(event_id),char_length(tenant_id),
                    char_length(task_id),char_length(actor_user_id)) <= 500);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE
        conrelid = 'anlan_v2.collaboration_notifications'::regclass
        AND conname = 'collaboration_notifications_text_bounds') THEN
        ALTER TABLE anlan_v2.collaboration_notifications
            ADD CONSTRAINT collaboration_notifications_text_bounds CHECK (
                greatest(char_length(tenant_id),char_length(recipient_user_id),
                    char_length(event_id)) <= 500);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS collaboration_applicant_updated
    ON anlan_v2.collaboration_applications(tenant_id,applicant_user_id,updated_at DESC,task_id);
CREATE INDEX IF NOT EXISTS collaboration_reviewer_updated
    ON anlan_v2.collaboration_applications(tenant_id,reviewer_user_id,updated_at DESC,task_id)
    WHERE reviewer_user_id IS NOT NULL AND status <> 'draft';
CREATE INDEX IF NOT EXISTS collaboration_commands_task
    ON anlan_v2.collaboration_commands(tenant_id,task_id,created_at);
CREATE INDEX IF NOT EXISTS collaboration_events_task
    ON anlan_v2.collaboration_events(tenant_id,task_id,created_at,event_id);
CREATE INDEX IF NOT EXISTS collaboration_notifications_recipient
    ON anlan_v2.collaboration_notifications(tenant_id,recipient_user_id,ordinal);

INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (17) ON CONFLICT DO NOTHING;

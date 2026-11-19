CREATE TABLE IF NOT EXISTS anlan_v2.business_query_receipts (
    tenant_id text NOT NULL CHECK (char_length(btrim(tenant_id)) BETWEEN 1 AND 500),
    actor_user_id text NOT NULL CHECK (char_length(btrim(actor_user_id)) BETWEEN 1 AND 500),
    source_message_id text NOT NULL CHECK (char_length(btrim(source_message_id)) BETWEEN 1 AND 500),
    actor_role text CHECK (actor_role IN ('applicant','safety_manager')),
    task_id text CHECK (char_length(btrim(task_id)) BETWEEN 1 AND 500),
    query_type text NOT NULL CHECK (query_type IN (
        'application_status','application_details','process_guidance','safety_knowledge'
    )),
    material_revision integer CHECK (material_revision >= 1),
    application_version integer CHECK (application_version >= 1),
    evidence_schema_version text NOT NULL CHECK (evidence_schema_version = 'business-evidence-v1'),
    citation_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(citation_ids) = 'array' AND jsonb_array_length(citation_ids) <= 3
    ),
    outcome text NOT NULL CHECK (outcome IN ('ok','unknown','selection_required','error')),
    queried_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,actor_user_id,source_message_id),
    CHECK ((task_id IS NULL AND material_revision IS NULL AND application_version IS NULL)
        OR (task_id IS NOT NULL AND material_revision IS NOT NULL AND application_version IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS business_query_receipts_task
    ON anlan_v2.business_query_receipts(tenant_id,task_id,queried_at);

INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (21) ON CONFLICT DO NOTHING;

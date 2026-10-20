CREATE TABLE IF NOT EXISTS anlan_v2.conversations (
    conversation_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    create_request_id text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('idle','pending_confirmation','active_hot_work','paused')
    ),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    active_task_id text,
    pending_intent_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id,user_id,create_request_id)
);

CREATE TABLE IF NOT EXISTS anlan_v2.conversation_messages (
    message_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES anlan_v2.conversations(conversation_id),
    request_id text NOT NULL,
    ordinal bigint GENERATED ALWAYS AS IDENTITY,
    role text NOT NULL CHECK (role IN ('user','assistant','system_event')),
    text text NOT NULL CHECK (octet_length(text) BETWEEN 1 AND 8192),
    status text NOT NULL CHECK (status IN ('pending','completed','failed')),
    request_payload jsonb,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (conversation_id,request_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS conversation_one_pending_message
    ON anlan_v2.conversation_messages(conversation_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS anlan_v2.pending_intents (
    intent_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES anlan_v2.conversations(conversation_id),
    source_message_id text NOT NULL REFERENCES anlan_v2.conversation_messages(message_id),
    revision integer NOT NULL CHECK (revision >= 1),
    status text NOT NULL CHECK (status IN ('pending','confirmed','rejected','superseded')),
    candidate jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX IF NOT EXISTS conversation_pending_intent_revision
    ON anlan_v2.pending_intents(conversation_id,revision);
CREATE UNIQUE INDEX IF NOT EXISTS conversation_one_pending_intent
    ON anlan_v2.pending_intents(conversation_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS anlan_v2.conversation_routes (
    message_id text PRIMARY KEY REFERENCES anlan_v2.conversation_messages(message_id),
    proposal jsonb NOT NULL,
    decision jsonb NOT NULL,
    classifier_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS conversation_owner_updated
    ON anlan_v2.conversations(tenant_id,user_id,updated_at DESC);

INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (13) ON CONFLICT DO NOTHING;

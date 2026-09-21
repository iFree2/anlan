CREATE TABLE IF NOT EXISTS anlan_v2.memory_feedback (
    tenant_id text NOT NULL, user_id text NOT NULL,
    source_ref text NOT NULL, version integer NOT NULL CHECK (version > 0),
    source_hash text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (tenant_id, user_id, source_ref, version)
);
CREATE TABLE IF NOT EXISTS anlan_v2.memories (
    memory_id uuid PRIMARY KEY,
    tenant_id text NOT NULL, user_id text NOT NULL, key text NOT NULL,
    snapshot jsonb NOT NULL,
    UNIQUE (tenant_id, user_id, key)
);
CREATE TABLE IF NOT EXISTS anlan_v2.memory_revisions (
    memory_id uuid NOT NULL REFERENCES anlan_v2.memories(memory_id),
    revision integer NOT NULL CHECK (revision > 0), snapshot jsonb NOT NULL,
    PRIMARY KEY (memory_id, revision)
);

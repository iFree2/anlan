CREATE TABLE IF NOT EXISTS anlan_v2.knowledge_documents (
    tenant_id text NOT NULL,
    doc_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    owner_id text NOT NULL,
    title text NOT NULL,
    source text NOT NULL,
    content_hash text NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_until timestamptz NOT NULL CHECK (valid_until > valid_from),
    allowed_users text[] NOT NULL,
    withdrawn boolean NOT NULL DEFAULT false,
    current boolean NOT NULL DEFAULT true,
    embedding_model text NOT NULL,
    PRIMARY KEY (tenant_id, doc_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_current_document
    ON anlan_v2.knowledge_documents (tenant_id, doc_id) WHERE current;
CREATE TABLE IF NOT EXISTS anlan_v2.knowledge_chunks (
    tenant_id text NOT NULL,
    doc_id text NOT NULL,
    version integer NOT NULL,
    chunk_id text NOT NULL,
    ordinal integer NOT NULL,
    body text NOT NULL,
    content_hash text NOT NULL,
    embedding public.vector(512) NOT NULL,
    PRIMARY KEY (tenant_id, doc_id, version, chunk_id),
    FOREIGN KEY (tenant_id, doc_id, version)
        REFERENCES anlan_v2.knowledge_documents (tenant_id, doc_id, version)
);

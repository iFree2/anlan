CREATE TABLE anlan_v2.dynamic_mcp_calls (
 tenant_id text NOT NULL,
 call_id text NOT NULL,
 user_id text NOT NULL,
 service_id text NOT NULL,
 generation bigint NOT NULL,
 config_revision bigint NOT NULL,
 discovery_id text NOT NULL,
 alias text NOT NULL,
 capability text NOT NULL,
 task_id text NOT NULL,
 run_id text NOT NULL,
 correlation_id text NOT NULL,
 elapsed_ms bigint NOT NULL CHECK(elapsed_ms>=0),
 receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object' AND octet_length(receipt_json::text)<=8192),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,call_id),
 FOREIGN KEY(tenant_id,service_id,config_revision) REFERENCES anlan_v2.dynamic_mcp_revisions,
 FOREIGN KEY(tenant_id,service_id,discovery_id) REFERENCES anlan_v2.dynamic_mcp_discoveries
);
CREATE TRIGGER dynamic_mcp_calls_immutable BEFORE UPDATE OR DELETE ON anlan_v2.dynamic_mcp_calls
 FOR EACH ROW EXECUTE FUNCTION anlan_v2.dynamic_mcp_immutable();
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (23);

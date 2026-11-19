CREATE TABLE anlan_v2.dynamic_mcp_revisions (
 tenant_id text NOT NULL, service_id text NOT NULL, config_revision bigint NOT NULL CHECK(config_revision>=1),
 registration_json jsonb NOT NULL CHECK(jsonb_typeof(registration_json)='object' AND octet_length(registration_json::text)<=65536),
 owner_subject text NOT NULL, reader_user_ids jsonb NOT NULL CHECK(jsonb_typeof(reader_user_ids)='array' AND jsonb_array_length(reader_user_ids)<=1000 AND octet_length(reader_user_ids::text)<=65536),
 config_hash text NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,service_id,config_revision)
);
CREATE TABLE anlan_v2.dynamic_mcp_discoveries (
 tenant_id text NOT NULL, service_id text NOT NULL, discovery_id text NOT NULL,
 config_revision bigint NOT NULL, captured_generation bigint NOT NULL,
 tools_json jsonb NOT NULL CHECK(jsonb_typeof(tools_json)='array' AND jsonb_array_length(tools_json)<=50 AND octet_length(tools_json::text)<=524288),
 protocol_version text NOT NULL, server_name text NOT NULL, server_version text NOT NULL,
 schema_profile text NOT NULL, snapshot_hash text NOT NULL, validation_json jsonb NOT NULL CHECK(jsonb_typeof(validation_json)='object' AND octet_length(validation_json::text)<=65536),
 status text NOT NULL CHECK(status IN ('discovered','validated')), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,service_id,discovery_id),
 FOREIGN KEY(tenant_id,service_id,config_revision) REFERENCES anlan_v2.dynamic_mcp_revisions
);
CREATE TABLE anlan_v2.dynamic_mcp_heads (
 tenant_id text NOT NULL, service_id text NOT NULL, generation bigint NOT NULL CHECK(generation>=1),
 config_revision bigint NOT NULL, state text NOT NULL CHECK(state IN ('registered','discovered','validated','enabled','disabled')),
 discovery_id text, validation_digest text, target_policy_version text NOT NULL, credential_generation text NOT NULL DEFAULT '',
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,service_id),
 FOREIGN KEY(tenant_id,service_id,config_revision) REFERENCES anlan_v2.dynamic_mcp_revisions,
 FOREIGN KEY(tenant_id,service_id,discovery_id) REFERENCES anlan_v2.dynamic_mcp_discoveries
);
CREATE TABLE anlan_v2.dynamic_mcp_operations (
 tenant_id text NOT NULL, admin_subject text NOT NULL, command_id text NOT NULL,
 service_id text NOT NULL, action text NOT NULL, payload_hash text NOT NULL,
 lease_json jsonb NOT NULL CHECK(jsonb_typeof(lease_json)='object' AND octet_length(lease_json::text)<=4096),
 status text NOT NULL CHECK(status IN ('reserved','completed','outcome_unknown')),
 started_at timestamptz NOT NULL DEFAULT now(), deadline_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,admin_subject,command_id)
);
CREATE TABLE anlan_v2.dynamic_mcp_commands (
 tenant_id text NOT NULL, admin_subject text NOT NULL, command_id text NOT NULL,
 service_id text NOT NULL, action text NOT NULL, payload_hash text NOT NULL, expected_generation bigint NOT NULL,
 result_json jsonb NOT NULL CHECK(jsonb_typeof(result_json)='object' AND octet_length(result_json::text)<=65536),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,admin_subject,command_id)
);
CREATE FUNCTION anlan_v2.dynamic_mcp_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable dynamic MCP history'; END $$;
CREATE TRIGGER dynamic_mcp_revisions_immutable BEFORE UPDATE OR DELETE ON anlan_v2.dynamic_mcp_revisions FOR EACH ROW EXECUTE FUNCTION anlan_v2.dynamic_mcp_immutable();
CREATE TRIGGER dynamic_mcp_discoveries_immutable BEFORE UPDATE OR DELETE ON anlan_v2.dynamic_mcp_discoveries FOR EACH ROW EXECUTE FUNCTION anlan_v2.dynamic_mcp_immutable();
CREATE TRIGGER dynamic_mcp_commands_immutable BEFORE UPDATE OR DELETE ON anlan_v2.dynamic_mcp_commands FOR EACH ROW EXECUTE FUNCTION anlan_v2.dynamic_mcp_immutable();
CREATE FUNCTION anlan_v2.dynamic_mcp_operation_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable operation'; END IF;
 IF OLD.status<>'reserved' OR NEW.status NOT IN ('completed','outcome_unknown') OR
 (to_jsonb(OLD)-'status')<>(to_jsonb(NEW)-'status') THEN RAISE EXCEPTION 'invalid operation transition'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER dynamic_mcp_operations_transition BEFORE UPDATE OR DELETE ON anlan_v2.dynamic_mcp_operations FOR EACH ROW EXECUTE FUNCTION anlan_v2.dynamic_mcp_operation_transition();
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (22);

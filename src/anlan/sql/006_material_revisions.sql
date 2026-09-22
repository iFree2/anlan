DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM anlan_schema_migrations WHERE version=6) THEN
        ALTER TABLE anlan_operations DROP CONSTRAINT anlan_operations_kind_check;
        ALTER TABLE anlan_operations ADD CONSTRAINT anlan_operations_kind_check
            CHECK (kind IN ('start', 'resume', 'revise'));
        INSERT INTO anlan_schema_migrations(version) VALUES (6);
    END IF;
END $$;

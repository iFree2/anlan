-- User authorization on 2026-10-22: P11-WP01 cap 30; all other caps and attempts stay intact.
CREATE TABLE IF NOT EXISTS anlan_v2.model_budget_package_limits (
    authorization_id text NOT NULL
        REFERENCES anlan_v2.model_budget_authorizations(authorization_id),
    work_package text NOT NULL CHECK (work_package = 'P11-WP01'),
    package_limit integer NOT NULL CHECK (package_limit BETWEEN 1 AND 100),
    PRIMARY KEY (authorization_id,work_package)
);
INSERT INTO anlan_v2.model_budget_package_limits
    (authorization_id,work_package,package_limit)
SELECT authorization_id,'P11-WP01',30
FROM anlan_v2.model_budget_authorizations
WHERE authorization_id='20260920-long-term-v1'
ON CONFLICT (authorization_id,work_package) DO NOTHING;
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (16) ON CONFLICT DO NOTHING;

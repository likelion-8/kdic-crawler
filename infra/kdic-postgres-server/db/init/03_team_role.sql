\set ON_ERROR_STOP on

-- Docker entrypoint initialization files run automatically only when the
-- PostgreSQL data volume is first created. For an existing volume, run
-- scripts/configure-team-access.ps1 to apply this idempotent configuration.
DO $configure_team_role$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kdic_team_admin') THEN
        ALTER ROLE kdic_team_admin
            NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    ELSE
        CREATE ROLE kdic_team_admin
            NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$configure_team_role$;

GRANT CONNECT, TEMPORARY ON DATABASE kdic TO kdic_team_admin;
GRANT USAGE, CREATE ON SCHEMA public TO kdic_team_admin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO kdic_team_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO kdic_team_admin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO kdic_team_admin;
GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA public TO kdic_team_admin;

ALTER DEFAULT PRIVILEGES FOR ROLE kdic_admin IN SCHEMA public
    GRANT ALL PRIVILEGES ON TABLES TO kdic_team_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE kdic_admin IN SCHEMA public
    GRANT ALL PRIVILEGES ON SEQUENCES TO kdic_team_admin;
-- PostgreSQL default FUNCTION privileges also apply to procedures.
ALTER DEFAULT PRIVILEGES FOR ROLE kdic_admin IN SCHEMA public
    GRANT ALL PRIVILEGES ON FUNCTIONS TO kdic_team_admin;

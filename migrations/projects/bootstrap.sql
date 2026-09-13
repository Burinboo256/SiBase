-- Executed by the local bootstrap administrator in each project database.
-- Placeholders are replaced only with validated names and generated hex secrets.
CREATE ROLE @PROJECT@_auth LOGIN PASSWORD '@AUTH_PASSWORD@';
CREATE ROLE @PROJECT@_rest LOGIN NOINHERIT PASSWORD '@REST_PASSWORD@';
CREATE ROLE @PROJECT@_storage LOGIN NOINHERIT BYPASSRLS PASSWORD '@STORAGE_PASSWORD@';
CREATE ROLE @PROJECT@_realtime LOGIN NOINHERIT REPLICATION BYPASSRLS PASSWORD '@REALTIME_PASSWORD@';
CREATE ROLE @PROJECT@_owner LOGIN PASSWORD '@OWNER_PASSWORD@';
GRANT anon, authenticated, service_role TO @PROJECT@_rest, @PROJECT@_storage, @PROJECT@_realtime;
GRANT supabase_realtime_admin TO @PROJECT@_realtime WITH ADMIN TRUE, INHERIT TRUE;
GRANT SET ON PARAMETER log_min_messages TO @PROJECT@_realtime;
GRANT CREATE ON DATABASE @PROJECT@ TO @PROJECT@_realtime, @PROJECT@_storage;
GRANT CONNECT ON DATABASE @PROJECT@ TO @PROJECT@_auth, @PROJECT@_rest, @PROJECT@_storage, @PROJECT@_realtime, @PROJECT@_owner;
CREATE SCHEMA auth AUTHORIZATION @PROJECT@_auth;
CREATE SCHEMA storage AUTHORIZATION @PROJECT@_storage;
CREATE SCHEMA _realtime AUTHORIZATION @PROJECT@_realtime;
CREATE SCHEMA realtime AUTHORIZATION @PROJECT@_realtime;
CREATE SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO @PROJECT@_auth, @PROJECT@_storage, @PROJECT@_realtime, authenticated;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role, @PROJECT@_storage, @PROJECT@_realtime, @PROJECT@_owner;
ALTER ROLE @PROJECT@_auth IN DATABASE @PROJECT@ SET search_path = auth, public, extensions;
ALTER ROLE @PROJECT@_storage IN DATABASE @PROJECT@ SET search_path = storage, public, extensions;
ALTER ROLE @PROJECT@_storage IN DATABASE @PROJECT@ SET storage.install_roles = 'false';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role, @PROJECT@_rest, @PROJECT@_realtime;
GRANT CREATE, USAGE ON SCHEMA public TO @PROJECT@_owner;
ALTER DEFAULT PRIVILEGES FOR ROLE @PROJECT@_storage IN SCHEMA storage GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE @PROJECT@_storage IN SCHEMA storage GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
GRANT ALL ON SCHEMA storage TO anon, authenticated, service_role;
REVOKE CREATE ON SCHEMA storage FROM anon, authenticated, service_role;
CREATE PUBLICATION supabase_realtime;

CREATE ROLE @PROJECT@_monitor LOGIN PASSWORD '@MONITOR_PASSWORD@';
GRANT CONNECT ON DATABASE @PROJECT@ TO @PROJECT@_monitor;

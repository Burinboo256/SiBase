-- Applied only after an Owner/Admin opts a project into Phase 3.
-- This never drops application data or replaces existing application policies.
CREATE SCHEMA IF NOT EXISTS sibase_internal;
REVOKE ALL ON SCHEMA sibase_internal FROM PUBLIC;
CREATE TABLE IF NOT EXISTS sibase_internal.migrations (version integer PRIMARY KEY);

CREATE OR REPLACE FUNCTION sibase_internal.enforce_public_rls()
RETURNS event_trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE item record;
BEGIN
    FOR item IN
        SELECT c.oid, n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_event_trigger_ddl_commands() d
        JOIN pg_class c ON d.classid = 'pg_class'::regclass AND c.oid = d.objid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    LOOP
        IF NOT item.relrowsecurity THEN
            EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', item.nspname, item.relname);
        END IF;
        IF NOT item.relforcerowsecurity THEN
            EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', item.nspname, item.relname);
        END IF;
    END LOOP;
END;
$$;
REVOKE ALL ON FUNCTION sibase_internal.enforce_public_rls() FROM PUBLIC;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'sibase_public_rls') THEN
        CREATE EVENT TRIGGER sibase_public_rls ON ddl_command_end
        WHEN TAG IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO', 'ALTER TABLE')
        EXECUTE FUNCTION sibase_internal.enforce_public_rls();
    END IF;
END $$;

DO $$ DECLARE item record; BEGIN
    FOR item IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p') LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', item.relname);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', item.relname);
    END LOOP;
END $$;

-- Collision checks protect application-owned tables with the same name.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM sibase_internal.migrations WHERE version=2) THEN
        IF to_regclass('public.phase3_tasks') IS NOT NULL THEN
            RAISE EXCEPTION 'Reserved Phase 3 template table already exists';
        END IF;
        CREATE TABLE public.phase3_tasks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
            title text NOT NULL CHECK (length(title) BETWEEN 1 AND 500)
        );
        ALTER TABLE public.phase3_tasks OWNER TO @PROJECT@_owner;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.phase3_tasks TO authenticated, service_role;
        CREATE POLICY own_tasks ON public.phase3_tasks FOR ALL TO authenticated
            USING (owner_id = (SELECT auth.uid()))
            WITH CHECK (owner_id = (SELECT auth.uid()));
        INSERT INTO sibase_internal.migrations VALUES (2);
    END IF;
END $$;
NOTIFY pgrst, 'reload schema';

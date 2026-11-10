-- =============================================================================
-- SI PhasePilot - Fix permissions for audit_records and related tables
-- =============================================================================
-- This script ensures audit_records, reports, commands, baselines,
-- document_versions have the same grants and RLS policies as phases.
-- Safe to run multiple times.
-- =============================================================================

-- 1. Ensure RLS is enabled on all target tables
alter table if exists public.audit_records enable row level security;
alter table if exists public.reports enable row level security;
alter table if exists public.commands enable row level security;
alter table if exists public.baselines enable row level security;
alter table if exists public.document_versions enable row level security;

-- 2. Drop and recreate RLS policies to match phases table
-- Phase 1: Tables with SELECT, INSERT, UPDATE (phases, audit_records, etc.)
do $$
declare t text;
begin
  foreach t in array array['audit_records']
  loop
    execute format('drop policy if exists pp_select on public.%I', t);
    execute format('drop policy if exists pp_insert on public.%I', t);
    execute format('drop policy if exists pp_update on public.%I', t);
    execute format('create policy pp_select on public.%I for select to authenticated
                    using (owner_id = auth.uid())', t);
    execute format('create policy pp_insert on public.%I for insert to authenticated
                    with check (owner_id = auth.uid())', t);
    execute format('create policy pp_update on public.%I for update to authenticated
                    using (owner_id = auth.uid()) with check (owner_id = auth.uid())', t);
  end loop;
end;
$$;

-- Phase 2: Append-only tables (reports, commands, baselines, document_versions)
do $$
declare t text;
begin
  foreach t in array array['reports', 'commands', 'baselines', 'document_versions']
  loop
    execute format('drop policy if exists pp_select on public.%I', t);
    execute format('drop policy if exists pp_insert on public.%I', t);
    execute format('create policy pp_select on public.%I for select to authenticated
                    using (owner_id = auth.uid())', t);
    execute format('create policy pp_insert on public.%I for insert to authenticated
                    with check (owner_id = auth.uid())', t);
  end loop;
end;
$$;

-- 3. Ensure table privileges match phases (revoke from anon, grant to authenticated)
revoke all on public.audit_records, public.reports, public.commands,
          public.baselines, public.document_versions
  from anon;

grant select, insert, update
  on public.audit_records
  to authenticated;

grant select, insert
  on public.reports, public.commands, public.baselines, public.document_versions
  to authenticated;

-- 4. Verify the version bump trigger exists on audit_records (for optimistic locking)
do $$
begin
  if not exists (
    select 1 from pg_trigger
    where tgname = 'pp_touch_audit_records'
      and tgrelid = 'public.audit_records'::regclass
  ) then
    create trigger pp_touch_audit_records
      before update on public.audit_records
      for each row execute function public.pp_touch_row();
  end if;
end;
$$;

-- 5. Verification queries (run separately after this script)
-- Should show all 5 tables with rowsecurity = true:
-- select tablename, rowsecurity from pg_tables
-- where schemaname = 'public'
--   and tablename in ('audit_records','reports','commands','baselines','document_versions')
-- order by tablename;
--
-- Should list the policies:
-- select tablename, policyname, cmd from pg_policies
-- where schemaname = 'public'
--   and tablename in ('audit_records','reports','commands','baselines','document_versions')
-- order by tablename, policyname;
--
-- Should show grants:
-- select grantee, table_name, privilege_type
-- from information_schema.table_privileges
-- where table_schema = 'public'
--   and table_name in ('audit_records','reports','commands','baselines','document_versions')
--   and grantee in ('anon','authenticated')
-- order by table_name, grantee, privilege_type;
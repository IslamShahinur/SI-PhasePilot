-- Secure Delete (F-13): install manually after review.
-- The app must use pp_secure_delete for application rows; it must not receive
-- direct DELETE privileges on those tables.

create or replace function public.pp_secure_delete(p_kind text, p_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_owner uuid := auth.uid();
  v_name text;
  v_phase_id uuid;
  v_project_id uuid;
  v_phase_no integer;
  v_attempt smallint;
  v_kind text;
  v_status text;
  v_body text;
  v_storage_paths text[] := array[]::text[];
begin
  if v_owner is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;

  if p_kind = 'project' then
    select p.name
      into v_name
      from public.projects p
     where p.id = p_id and p.owner_id = v_owner
     for update;
    if not found then
      raise exception 'Item not found or not accessible' using errcode = 'P0002';
    end if;

    perform 1
      from public.phases ph
     where ph.project_id = p_id and ph.owner_id = v_owner
     for update;
    if exists (
      select 1 from public.phases ph
       where ph.project_id = p_id
         and ph.owner_id = v_owner
         and ph.status = 'coding_in_progress'
    ) then
      return jsonb_build_object('deleted', false, 'blocked', true);
    end if;

    select coalesce(array_agg(files.storage_path), array[]::text[])
      into v_storage_paths
      from (
        select dv.storage_path
          from public.document_versions dv
         where dv.project_id = p_id and dv.owner_id = v_owner
        union
        select r.storage_path
          from public.reports r
         where r.project_id = p_id
           and r.owner_id = v_owner
           and r.storage_path is not null
      ) files;

    delete from public.projects p
     where p.id = p_id and p.owner_id = v_owner;

  elsif p_kind = 'phase' then
    select ph.project_id, ph.phase_no, ph.title, ph.status
      into v_project_id, v_phase_no, v_name, v_status
      from public.phases ph
     where ph.id = p_id and ph.owner_id = v_owner
     for update;
    if not found then
      raise exception 'Item not found or not accessible' using errcode = 'P0002';
    end if;
    if v_status = 'coding_in_progress' then
      return jsonb_build_object('deleted', false, 'blocked', true);
    end if;

    select coalesce(array_agg(r.storage_path), array[]::text[])
      into v_storage_paths
      from public.reports r
     where r.phase_id = p_id
       and r.owner_id = v_owner
       and r.storage_path is not null;

    update public.register_items
       set phase_id = null
     where phase_id = p_id and project_id = v_project_id and owner_id = v_owner;
    delete from public.phases ph
     where ph.id = p_id and ph.owner_id = v_owner;
    v_name := 'Phase ' || v_phase_no::text || ': ' || coalesce(v_name, '(untitled)');

  elsif p_kind = 'command' then
    select c.phase_id, c.project_id, c.attempt_no, c.kind, c.title, c.body,
           ph.status
      into v_phase_id, v_project_id, v_attempt, v_kind, v_name, v_body,
           v_status
      from public.commands c
      join public.phases ph on ph.id = c.phase_id and ph.project_id = c.project_id
     where c.id = p_id and c.owner_id = v_owner and ph.owner_id = v_owner
     for update of c, ph;
    if not found then
      raise exception 'Item not found or not accessible' using errcode = 'P0002';
    end if;
    if v_status = 'coding_in_progress' then
      return jsonb_build_object('deleted', false, 'blocked', true);
    end if;

    if v_kind = 'auditor' then
      select coalesce(array_agg(r.storage_path), array[]::text[])
        into v_storage_paths
        from public.reports r
       where r.owner_id = v_owner
         and r.phase_id = v_phase_id
         and r.attempt_no = v_attempt
         and r.kind in ('auditor_report', 'claude_review')
         and r.storage_path is not null;
    else
      select coalesce(array_agg(r.storage_path), array[]::text[])
        into v_storage_paths
        from public.reports r
       where r.owner_id = v_owner
         and r.phase_id = v_phase_id
         and r.attempt_no = v_attempt
         and r.kind = 'coder_report'
         and r.storage_path is not null;
    end if;

    select coalesce(
             nullif(btrim(v_name), ''),
             nullif(split_part(v_body, E'\n', 1), ''),
             'Command'
           )
      into v_name;

    if v_kind = 'auditor' then
      delete from public.reports r
       where r.owner_id = v_owner
         and r.phase_id = v_phase_id
         and r.attempt_no = v_attempt
         and r.kind in ('auditor_report', 'claude_review');
      delete from public.audit_records a
       where a.owner_id = v_owner
         and a.phase_id = v_phase_id
         and a.attempt_no = v_attempt;
    else
      delete from public.reports r
       where r.owner_id = v_owner
         and r.phase_id = v_phase_id
         and r.attempt_no = v_attempt
         and r.kind = 'coder_report';
    end if;

    delete from public.commands c
     where c.id = p_id and c.owner_id = v_owner;

  elsif p_kind = 'document' then
    select d.title
      into v_name
      from public.documents d
     where d.id = p_id and d.owner_id = v_owner
     for update;
    if not found then
      raise exception 'Item not found or not accessible' using errcode = 'P0002';
    end if;
    select coalesce(array_agg(dv.storage_path), array[]::text[])
      into v_storage_paths
      from public.document_versions dv
     where dv.document_id = p_id
       and dv.owner_id = v_owner;
    delete from public.documents d
     where d.id = p_id and d.owner_id = v_owner;

  elsif p_kind = 'baseline' then
    select b.phase_id, b.attempt_no, ph.phase_no, ph.status
      into v_phase_id, v_attempt, v_phase_no, v_status
      from public.baselines b
      join public.phases ph on ph.id = b.phase_id and ph.project_id = b.project_id
     where b.id = p_id and b.owner_id = v_owner and ph.owner_id = v_owner
     for update of b, ph;
    if not found then
      raise exception 'Item not found or not accessible' using errcode = 'P0002';
    end if;
    if v_status = 'coding_in_progress' then
      return jsonb_build_object('deleted', false, 'blocked', true);
    end if;
    delete from public.baselines b
     where b.id = p_id and b.owner_id = v_owner;
    v_name := 'Approved Baseline — Phase ' || v_phase_no::text
              || ', attempt ' || v_attempt::text;

  else
    raise exception 'Unsupported delete type' using errcode = '22023';
  end if;

  return jsonb_build_object(
    'deleted', true,
    'blocked', false,
    'kind', p_kind,
    'name', v_name,
    'storage_paths', to_jsonb(v_storage_paths)
  );
end;
$$;

revoke all on function public.pp_secure_delete(text, uuid) from public, anon;
grant execute on function public.pp_secure_delete(text, uuid) to authenticated;

grant delete on table storage.objects to authenticated;
drop policy if exists pp_files_delete on storage.objects;
create policy pp_files_delete on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'phasepilot-files'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

notify pgrst, 'reload schema';

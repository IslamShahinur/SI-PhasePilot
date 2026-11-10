-- =============================================================================
-- SI PhasePilot - Schema revision 4B, fix 1 (Phase 4B migration)
-- =============================================================================
-- One single DO block: everything runs or nothing runs (one statement, one
-- implicit transaction). Safe to re-run.
--
-- Steps (in this order on purpose):
--   1. Skip everything when the new phases.status rule already contains
--      'awaiting_task' (i.e. revision 4B was already applied).
--   2. Drop the old workflow triggers first, because the old
--      pp_phase_transition would reject remapping old statuses to new ones.
--      Both triggers are recreated at the end with the new definitions
--      (same as schema.sql).
--   3. Guard: if any old attempt_no is above 4, RAISE EXCEPTION so that
--      nothing changes (old values 1..4 are the only ones that can be
--      shifted into the new range 0..3). The same guard covers
--      phases.current_attempt.
--   4. phases.status: drop old rule -> UPDATE old values -> add new rule.
--   5. attempt_no and phases.current_attempt: drop old rules ->
--      type smallint (attempt_no columns) -> UPDATE value = value - 1
--      (old values start at 1, new values start at 0, minimum 0)
--      -> default 0 -> add 0..3 rule.
--   6. audit_records.audit_status: drop old rule -> UPDATE old values ->
--      add new rule. Old values found in the old schema:
--      'not_started', 'in_progress', 'passed', 'failed'. Mapping:
--        not_started -> not_reviewed
--        in_progress -> not_reviewed
--        passed      -> passed
--        failed      -> failed
--   7. Reinstall the rewritten pp_phase_transition and pp_baseline_guard
--      triggers (identical definitions as in schema.sql).
--   8. Recreate the audit_records index including attempt_no.
--
-- phases.status mapping:
--   not_started       -> awaiting_task
--   in_progress       -> coding_in_progress
--   coding_complete   -> coding_completed
--   awaiting_audit    -> coding_completed
--   audit_failed      -> coding_completed
--   audit_passed      -> cleared
--   baseline_approved -> cleared
--
-- NOTE: phases.current_attempt is shifted together with attempt_no
-- (1-based old -> 0-based new, minimum 0, default 0, range 0..3).
-- =============================================================================

BEGIN;

do $rev4b$
declare
  v_rule text;
begin
  -- Skip everything if revision 4B is already applied
  select coalesce(pg_get_constraintdef(oid), '') into v_rule
    from pg_constraint
   where conrelid = 'public.phases'::regclass
     and conname = 'phases_status_check';
  if position('awaiting_task' in v_rule) > 0 then
    raise notice 'Schema revision 4B already applied, nothing to do.';
    return;
  end if;

  -- The OLD trigger logic (not_started -> ... -> baseline_approved) would
  -- reject the status remapping, so drop both triggers first. They are
  -- re-created below with the new definitions.
  drop trigger if exists pp_phase_transition_trg on public.phases;
  drop trigger if exists pp_baseline_guard_trg on public.baselines;

  -- Guard: old attempt_no / current_attempt must be at most 4
  -- (only 1..4 can shift into 0..3)
  if exists (select 1 from public.commands         where attempt_no > 4)
     or exists (select 1 from public.reports       where attempt_no > 4)
     or exists (select 1 from public.audit_records where attempt_no > 4)
     or exists (select 1 from public.baselines     where attempt_no > 4)
     or exists (select 1 from public.phases        where current_attempt > 4) then
    raise exception 'Schema revision 4B: old attempt_no/current_attempt above 4 found, migration aborted, nothing changed';
  end if;

  -- 1. phases.status: drop old rule -> map old values -> add new rule
  alter table public.phases drop constraint if exists phases_status_check;
  update public.phases set status = 'awaiting_task'
   where status in ('not_started');
  update public.phases set status = 'coding_in_progress'
   where status = 'in_progress';
  update public.phases set status = 'coding_completed'
   where status in ('coding_complete','awaiting_audit','audit_failed');
  update public.phases set status = 'cleared'
   where status in ('audit_passed','baseline_approved');
  alter table public.phases add constraint phases_status_check
    check (status in ('awaiting_task','coding_in_progress','coding_completed','cleared'));
  alter table public.phases alter column status set default 'awaiting_task';

  -- phases.current_attempt: drop old rule -> shift 1-based to 0-based
  -- (minimum 0) -> default 0 -> 0..3 rule
  alter table public.phases drop constraint if exists phases_current_attempt_check;
  update public.phases set current_attempt = current_attempt - 1 where current_attempt >= 1;
  alter table public.phases alter column current_attempt set default 0;
  alter table public.phases add constraint phases_current_attempt_check
    check (current_attempt between 0 and 3);

  -- 2. attempt_no: drop old rule -> shift 1-based to 0-based -> 0..3 rule
  alter table public.commands drop constraint if exists commands_attempt_no_check;
  alter table public.commands alter column attempt_no type smallint using attempt_no::smallint;
  update public.commands set attempt_no = attempt_no - 1 where attempt_no >= 1;
  alter table public.commands alter column attempt_no set default 0;
  alter table public.commands add constraint commands_attempt_no_check
    check (attempt_no between 0 and 3);

  alter table public.reports drop constraint if exists reports_attempt_no_check;
  alter table public.reports alter column attempt_no type smallint using attempt_no::smallint;
  update public.reports set attempt_no = attempt_no - 1 where attempt_no >= 1;
  alter table public.reports alter column attempt_no set default 0;
  alter table public.reports add constraint reports_attempt_no_check
    check (attempt_no between 0 and 3);

  alter table public.audit_records drop constraint if exists audit_records_attempt_no_check;
  alter table public.audit_records alter column attempt_no type smallint using attempt_no::smallint;
  update public.audit_records set attempt_no = attempt_no - 1 where attempt_no >= 1;
  alter table public.audit_records alter column attempt_no set default 0;
  alter table public.audit_records add constraint audit_records_attempt_no_check
    check (attempt_no between 0 and 3);

  alter table public.baselines drop constraint if exists baselines_attempt_no_check;
  alter table public.baselines alter column attempt_no type smallint using attempt_no::smallint;
  update public.baselines set attempt_no = attempt_no - 1 where attempt_no >= 1;
  alter table public.baselines alter column attempt_no set default 0;
  alter table public.baselines add constraint baselines_attempt_no_check
    check (attempt_no between 0 and 3);

  -- 3. audit_records.audit_status: drop old rule -> map -> add new rule
  alter table public.audit_records drop constraint if exists audit_records_audit_status_check;
  update public.audit_records set audit_status = 'not_reviewed'
   where audit_status in ('not_started','in_progress');
  alter table public.audit_records add constraint audit_records_audit_status_check
    check (audit_status in ('not_reviewed','passed','failed'));
  alter table public.audit_records alter column audit_status set default 'not_reviewed';

  -- 4. Rewritten workflow triggers (same definitions as schema.sql).

  -- pp_phase_transition checks every phases.update that changes status:
  --   awaiting_task     -> coding_in_progress | coding_completed | awaiting_task
  --   coding_in_progress-> coding_completed | awaiting_task | coding_in_progress
  --   coding_completed  -> cleared | coding_in_progress | awaiting_task | coding_completed
  --   cleared           -> cleared only (read-only; set only by Mark Review Passed)
  -- Moving coding_completed -> coding_in_progress (Re-Fix) increments
  -- current_attempt. cleared requires a saved baseline for the current attempt;
  -- without a passed review for that attempt the baseline must be a documented
  -- override (override_used = true with a written reason).
  -- 'baseline_approved' no longer exists: there is no audit_passed ->
  -- baseline_approved step any more. Baseline approval now works like this:
  --   * pp_baseline_guard (below) decides whether a baseline row may be saved:
  --     freely when the attempt has a 'passed' review record, or as a
  --     documented override (with reason) when it does not.
  --   * When the owner marks the review passed, the phase goes straight from
  --     coding_completed to cleared; this trigger then only verifies that a
  --     baseline for the current attempt already exists.
  create or replace function public.pp_phase_transition()
  returns trigger
  language plpgsql
  set search_path = public
  as $fn$
  begin
    if new.status is distinct from old.status then
      if not (
           (old.status = 'awaiting_task'       and new.status in ('coding_in_progress','coding_completed','awaiting_task'))
         or (old.status = 'coding_in_progress' and new.status in ('coding_completed','awaiting_task','coding_in_progress'))
         or (old.status = 'coding_completed'   and new.status in ('cleared','coding_in_progress','awaiting_task','coding_completed'))
         or (old.status = 'cleared'            and new.status in ('cleared'))
      ) then
        raise exception 'Invalid phase status change: % -> %', old.status, new.status
          using errcode = 'check_violation';
      end if;

      -- Re-Fix: coding_completed -> coding_in_progress starts a new attempt
      if old.status = 'coding_completed' and new.status = 'coding_in_progress' then
        new.current_attempt := old.current_attempt + 1;
      end if;

      -- A baseline must exist before the phase can be marked cleared.
      -- Without a passed review, that baseline must be a documented override.
      if new.status = 'cleared' then
        -- Check if there's a passed review for the current attempt
        if exists (
             select 1 from public.audit_records a
              where a.phase_id = new.id and a.attempt_no = new.current_attempt
                and a.audit_status = 'passed'
          ) then
          if not exists (
               select 1 from public.baselines b
                where b.phase_id = new.id and b.attempt_no = new.current_attempt
             ) then
            raise exception 'Save a baseline for attempt % before clearing the phase', new.current_attempt
              using errcode = 'check_violation';
          end if;
        else
          if not exists (
               select 1 from public.baselines b
                where b.phase_id = new.id and b.attempt_no = new.current_attempt
                  and b.override_used = true
             ) then
            raise exception 'Without a passed review, save an override baseline (with reason) for attempt % first', new.current_attempt
              using errcode = 'check_violation';
          end if;
        end if;
      end if;
    end if;
    return new;
  end;
  $fn$;

  drop trigger if exists pp_phase_transition_trg on public.phases;
  create trigger pp_phase_transition_trg
    before update on public.phases
    for each row execute function public.pp_phase_transition();

  -- pp_baseline_guard checks every baselines INSERT:
  --   override_used = true  -> a non-blank override_reason is required.
  --   override_used = false -> a 'passed' audit_records row for the same
  --                            (phase_id, attempt_no) must exist.
  create or replace function public.pp_baseline_guard()
  returns trigger
  language plpgsql
  set search_path = public
  as $fn$
  begin
    if new.override_used then
      if coalesce(trim(new.override_reason), '') = '' then
        raise exception 'An override requires a written reason'
          using errcode = 'check_violation';
      end if;
      return new;
    end if;

    if not exists (
         select 1 from public.audit_records a
          where a.phase_id = new.phase_id
            and a.attempt_no = new.attempt_no
            and a.audit_status = 'passed'
       ) then
      raise exception 'Baseline needs a passed review for this attempt, or an override with a reason'
        using errcode = 'check_violation';
    end if;
    return new;
  end;
  $fn$;

  drop trigger if exists pp_baseline_guard_trg on public.baselines;
  create trigger pp_baseline_guard_trg
    before insert on public.baselines
    for each row execute function public.pp_baseline_guard();

  -- 5. Index updates (attempt_no type change is handled by the ALTER COLUMN);
  --    idx_audit_phase now includes attempt_no
  drop index if exists idx_audit_phase;
  create index if not exists idx_audit_phase on public.audit_records (phase_id, attempt_no);
end;
$rev4b$;

COMMIT;

-- =============================================================================
-- End of schema revision 4B (fix 1)
-- =============================================================================
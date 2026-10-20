-- Semaphore Lab: database schema for Supabase.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Safe to run again (it drops and recreates the policies and trigger).

create table if not exists public.saved_runs (
  id          bigint generated always as identity primary key,
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  demo        text not null check (demo in ('race', 'producer_consumer', 'readers_writers', 'dining_philosophers')),
  status      text not null check (status in ('PASS', 'FAIL', 'DEADLOCK', 'CANCELLED')),
  duration    real not null check (duration >= 0 and duration <= 3600),
  params      jsonb not null default '{}'::jsonb check (pg_column_size(params) <= 2000),
  summary     text not null default '' check (char_length(summary) <= 500),
  created_at  timestamptz not null default now()
);

create index if not exists saved_runs_user_created on public.saved_runs (user_id, created_at desc);

-- Row level security: every account sees and deletes only its own rows.
alter table public.saved_runs enable row level security;
alter table public.saved_runs force row level security;

drop policy if exists "own rows: read"   on public.saved_runs;
drop policy if exists "own rows: insert" on public.saved_runs;
drop policy if exists "own rows: delete" on public.saved_runs;

create policy "own rows: read"   on public.saved_runs for select to authenticated using ((select auth.uid()) = user_id);
create policy "own rows: insert" on public.saved_runs for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "own rows: delete" on public.saved_runs for delete to authenticated using ((select auth.uid()) = user_id);
-- No update policy: saved results cannot be edited, only deleted.

revoke all on public.saved_runs from anon, authenticated;
grant select, insert, delete on public.saved_runs to authenticated;

-- Database-level rate limit and quota per account.
create or replace function public.limit_saved_runs() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  perform pg_advisory_xact_lock(hashtext(new.user_id::text));
  if (select count(*) from public.saved_runs
      where user_id = new.user_id and created_at > now() - interval '1 hour') >= 30 then
    raise exception 'rate_limited: at most 30 saved results per hour';
  end if;
  if (select count(*) from public.saved_runs where user_id = new.user_id) >= 200 then
    raise exception 'quota: at most 200 saved results per account';
  end if;
  return new;
end $$;

revoke all on function public.limit_saved_runs() from public, anon, authenticated;

drop trigger if exists saved_runs_limit on public.saved_runs;
create trigger saved_runs_limit before insert on public.saved_runs
  for each row execute function public.limit_saved_runs();

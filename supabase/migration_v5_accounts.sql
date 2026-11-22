-- ===================== v5: חשבונות, רשימות לפי משתמש, ומיקום =====================
-- בטוח להרצה חוזרת. הכל חינם (Supabase Auth חינמי עד 50,000 משתמשים פעילים בחודש).

grant usage on schema public to anon, authenticated, service_role;

-- פרופיל: שורה לכל משתמש. נוצר אוטומטית בהרשמה (הטריגר למטה).
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  avatar_url text,
  home_label text,
  home_lat double precision,
  home_lng double precision,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table profiles enable row level security;
drop policy if exists "own profile select" on profiles;
drop policy if exists "own profile insert" on profiles;
drop policy if exists "own profile update" on profiles;
create policy "own profile select" on profiles for select using (auth.uid() = id);
create policy "own profile insert" on profiles for insert with check (auth.uid() = id);
create policy "own profile update" on profiles for update using (auth.uid() = id) with check (auth.uid() = id);
grant select, insert, update on profiles to authenticated;
grant select, insert, update, delete on profiles to service_role;

-- רשימות קניות של משתמש. כל משתמש רואה ומשנה רק את שלו (RLS), בלי שום קוד שרת.
create table if not exists user_lists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null,
  category text,
  items jsonb not null default '[]'::jsonb,
  local_id text,                      -- מזהה הרשימה במכשיר, למניעת כפילות בהעברה מהמכשיר לחשבון
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, local_id)
);
create index if not exists idx_user_lists_user on user_lists(user_id, updated_at desc);
alter table user_lists enable row level security;
drop policy if exists "own lists select" on user_lists;
drop policy if exists "own lists insert" on user_lists;
drop policy if exists "own lists update" on user_lists;
drop policy if exists "own lists delete" on user_lists;
create policy "own lists select" on user_lists for select using (auth.uid() = user_id);
create policy "own lists insert" on user_lists for insert with check (auth.uid() = user_id);
create policy "own lists update" on user_lists for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own lists delete" on user_lists for delete using (auth.uid() = user_id);
grant select, insert, update, delete on user_lists to authenticated;
grant select, insert, update, delete on user_lists to service_role;

-- יצירת פרופיל אוטומטית כשמשתמש נרשם (Google או קישור במייל)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, display_name, avatar_url)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name', split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data->>'avatar_url', new.raw_user_meta_data->>'picture')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- מיקום סניפים (נמלא ע"י ingest/geocode.py): קואורדינטות + האם הן מדויקות או רק של העיר
alter table stores add column if not exists geocoded_at timestamptz;
alter table stores add column if not exists geocode_failed boolean not null default false;
alter table stores add column if not exists geocode_approx boolean not null default false;
create index if not exists idx_stores_geocode on stores(geocode_failed, lat) where store_id_ext <> 'ALL';

-- הרשאות מפורשות לטבלאות שנוצרו קודם (בפרויקטים חדשים של Supabase אין הרשאות ברירת מחדל)
grant select, insert on feedback to anon, authenticated;
grant select on site_banner to anon, authenticated;
grant select on ingest_status to anon, authenticated;
grant select on stores to anon, authenticated;

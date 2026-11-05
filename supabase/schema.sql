-- تقویم شیفت و PM — اسکریپت دیتابیس Supabase
-- این فایل را یک‌بار در Supabase > SQL Editor اجرا کنید. اجرای دوباره بی‌خطر است.
--
-- مدل داده: دو نوع سند در جدول shift_kv
--   id = 'config'      → پرسنل، تیم‌ها، دستگاه‌ها، کارهای PM، چرخه شیفت (یک سند JSON)
--   id = 'm-1405-08'   → وضعیت یک ماه شمسی: کلیدهای تیک (d:...) و تغییر شیفت افراد (o:...)
-- دسترسی: همه‌ی کاربران واردشده می‌خوانند؛ فقط کاربران جدول shift_editors می‌نویسند.

create table if not exists public.shift_kv (
  id         text primary key
             check (id ~ '^(config|m-[0-9]{4}-[0-9]{2})$'),
  data       jsonb not null default '{}'::jsonb
             check (octet_length(data::text) < 500000),
  updated_at timestamptz not null default now(),
  updated_by uuid
);

create table if not exists public.shift_editors (
  user_id uuid primary key references auth.users (id) on delete cascade
);

alter table public.shift_kv      enable row level security;
alter table public.shift_editors enable row level security;

-- آیا کاربر جاری ویرایشگر است؟
create or replace function public.shift_is_editor()
returns boolean
language sql stable security invoker
set search_path = public
as $$
  select exists (select 1 from public.shift_editors e where e.user_id = auth.uid());
$$;

-- ثبت زمان و نویسنده‌ی آخرین تغییر
create or replace function public.shift_touch()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at := now();
  new.updated_by := auth.uid();
  return new;
end;
$$;

drop trigger if exists shift_kv_touch on public.shift_kv;
create trigger shift_kv_touch
  before insert or update on public.shift_kv
  for each row execute function public.shift_touch();

-- ادغام امن کلیدها: دو نفر هم‌زمان دو تیک متفاوت بزنند، هیچ‌کدام پاک نمی‌شود.
create or replace function public.shift_patch(
  p_id  text,
  p_set jsonb  default '{}'::jsonb,
  p_del text[] default '{}'::text[]
)
returns void
language sql security invoker
set search_path = public
as $$
  insert into public.shift_kv (id, data)
  values (p_id, coalesce(p_set, '{}'::jsonb) - coalesce(p_del, '{}'::text[]))
  on conflict (id) do update
    set data = (public.shift_kv.data || coalesce(p_set, '{}'::jsonb)) - coalesce(p_del, '{}'::text[]);
$$;

-- سیاست‌های دسترسی (RLS)
drop policy if exists shift_kv_read   on public.shift_kv;
drop policy if exists shift_kv_insert on public.shift_kv;
drop policy if exists shift_kv_update on public.shift_kv;
create policy shift_kv_read   on public.shift_kv for select to authenticated using (true);
create policy shift_kv_insert on public.shift_kv for insert to authenticated with check (public.shift_is_editor());
create policy shift_kv_update on public.shift_kv for update to authenticated
  using (public.shift_is_editor()) with check (public.shift_is_editor());

drop policy if exists shift_editors_self on public.shift_editors;
create policy shift_editors_self on public.shift_editors for select to authenticated
  using (user_id = auth.uid());

-- سطح دسترسی جداول و توابع: کاربر ناشناس (anon) هیچ دسترسی‌ای ندارد
revoke all on public.shift_kv, public.shift_editors from anon, public;
grant select, insert, update on public.shift_kv to authenticated;
grant select on public.shift_editors to authenticated;

revoke execute on function public.shift_is_editor() from public, anon;
revoke execute on function public.shift_patch(text, jsonb, text[]) from public, anon;
grant  execute on function public.shift_is_editor() to authenticated;
grant  execute on function public.shift_patch(text, jsonb, text[]) to authenticated;

-- همگام‌سازی زنده بین دستگاه‌ها
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables
                     where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'shift_kv') then
    alter publication supabase_realtime add table public.shift_kv;
  end if;
end $$;

-- بعد از ساخت کاربر در Authentication > Users، خودتان را ویرایشگر کنید (ایمیل را عوض کنید):
--   insert into public.shift_editors (user_id)
--   select id from auth.users where email = 'you@example.com'
--   on conflict do nothing;

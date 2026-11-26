-- صفحه‌ی «اکسل» سایت — جدول‌های نمایش شیت‌های فایل اکسل (فقط‌خواندنی در سایت)
-- این فایل را یک‌بار در Supabase > SQL Editor اجرا کنید. اجرای دوباره بی‌خطر است.
--
-- جریان داده: Excel ← (ذخیره) ← excel_sync/publish.py ← excel_sheets / excel_chunks ← صفحه‌ی «اکسل»
--   excel_sheets : یک ردیف برای هر شیت (عنوان، نوع، تعداد ردیف، هش محتوا، زمان انتشار)
--   excel_chunks : محتوای شیت به تکه‌های JSON (برای شیت‌های بزرگ چند تکه)
-- دسترسی:
--   خواندن: ویرایشگرها (shift_editors) + کاربران جدول excel_viewers + ناشر
--   نوشتن : فقط کاربران جدول excel_publishers (یک حساب اختصاصی برای برنامه‌ی ناشر)

create table if not exists public.excel_sheets (
  id         text primary key,
  title      text not null,
  kind       text not null check (kind in ('report', 'table')),
  ord        int  not null default 0,
  nrows      int  not null default 0,
  ncols      int  not null default 0,
  nchunks    int  not null default 1,
  hash       text not null default '',
  bytes      int  not null default 0,
  info       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.excel_chunks (
  sheet_id text  not null,
  part     int   not null,
  data     jsonb not null,
  primary key (sheet_id, part)
);

create table if not exists public.excel_viewers (
  user_id uuid primary key references auth.users (id) on delete cascade
);
create table if not exists public.excel_publishers (
  user_id uuid primary key references auth.users (id) on delete cascade
);

alter table public.excel_sheets     enable row level security;
alter table public.excel_chunks     enable row level security;
alter table public.excel_viewers    enable row level security;
alter table public.excel_publishers enable row level security;

create or replace function public.excel_can_read()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.shift_editors   where user_id = auth.uid())
      or exists (select 1 from public.excel_viewers   where user_id = auth.uid())
      or exists (select 1 from public.excel_publishers where user_id = auth.uid());
$$;

create or replace function public.excel_can_publish()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.excel_publishers where user_id = auth.uid());
$$;

-- زمان آخرین انتشار را سمت سرور ثبت کن
create or replace function public.excel_touch()
returns trigger language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists excel_sheets_touch on public.excel_sheets;
create trigger excel_sheets_touch before insert or update on public.excel_sheets
  for each row execute function public.excel_touch();

drop policy if exists excel_sheets_read   on public.excel_sheets;
drop policy if exists excel_sheets_ins    on public.excel_sheets;
drop policy if exists excel_sheets_upd    on public.excel_sheets;
drop policy if exists excel_sheets_del    on public.excel_sheets;
drop policy if exists excel_chunks_read   on public.excel_chunks;
drop policy if exists excel_chunks_ins    on public.excel_chunks;
drop policy if exists excel_chunks_upd    on public.excel_chunks;
drop policy if exists excel_chunks_del    on public.excel_chunks;
create policy excel_sheets_read on public.excel_sheets for select to authenticated using (public.excel_can_read());
create policy excel_sheets_ins  on public.excel_sheets for insert to authenticated with check (public.excel_can_publish());
create policy excel_sheets_upd  on public.excel_sheets for update to authenticated using (public.excel_can_publish()) with check (public.excel_can_publish());
create policy excel_sheets_del  on public.excel_sheets for delete to authenticated using (public.excel_can_publish());
create policy excel_chunks_read on public.excel_chunks for select to authenticated using (public.excel_can_read());
create policy excel_chunks_ins  on public.excel_chunks for insert to authenticated with check (public.excel_can_publish());
create policy excel_chunks_upd  on public.excel_chunks for update to authenticated using (public.excel_can_publish()) with check (public.excel_can_publish());
create policy excel_chunks_del  on public.excel_chunks for delete to authenticated using (public.excel_can_publish());

drop policy if exists excel_viewers_self    on public.excel_viewers;
drop policy if exists excel_publishers_self on public.excel_publishers;
create policy excel_viewers_self    on public.excel_viewers    for select to authenticated using (user_id = auth.uid());
create policy excel_publishers_self on public.excel_publishers for select to authenticated using (user_id = auth.uid());

-- کاربر ناشناس هیچ دسترسی‌ای ندارد
revoke all on public.excel_sheets, public.excel_chunks, public.excel_viewers, public.excel_publishers from anon, public;
grant select, insert, update, delete on public.excel_sheets, public.excel_chunks to authenticated;
grant select on public.excel_viewers, public.excel_publishers to authenticated;
revoke execute on function public.excel_can_read(), public.excel_can_publish() from public, anon;
grant  execute on function public.excel_can_read(), public.excel_can_publish() to authenticated;

-- به‌روزرسانی زنده‌ی صفحه (Realtime) هنگام انتشار جدید
do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'excel_sheets') then
    alter publication supabase_realtime add table public.excel_sheets;
  end if;
end $$;

-- ───────────────────────── بعد از اجرای این فایل ─────────────────────────
-- ۱) Authentication > Users > Add user: یک کاربر برای برنامه‌ی ناشر بسازید (مثلاً excel-publisher@example.com).
-- ۲) ID آن کاربر را کپی کنید و اجرا کنید:
--      insert into public.excel_publishers (user_id) values ('<ID کاربر ناشر>');
-- ۳) هر کسی که باید صفحه‌ی اکسل را ببیند (غیر از ویرایشگرها):
--      insert into public.excel_viewers (user_id) values ('<ID کاربر>');

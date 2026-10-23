-- לקנות בקטנה — סכימת מסד נתונים
-- מריצים את זה פעם אחת בפרויקט Supabase חדש (SQL editor -> New query -> Run)

create extension if not exists pgcrypto;

-- רשתות (שופרסל, רמי לוי, ויקטורי...)
create table if not exists chains (
  id text primary key,              -- מזהה פנימי קבוע, למשל 'shufersal', 'rami-levy'
  display_name text not null,
  portal_type text not null,        -- 'shufersal_direct' | 'cerberus' | 'carrefour_direct'
  portal_username text,             -- שם משתמש בפורטל (אם יש, נטען מ-secrets, לא נשמר כאן בפועל)
  active boolean not null default true
);

-- סניפים
create table if not exists stores (
  id uuid primary key default gen_random_uuid(),
  chain_id text not null references chains(id),
  store_id_ext text not null,       -- המזהה כפי שמופיע בקובץ של הרשת עצמה
  name text,
  city text,
  address text,
  lat double precision,
  lng double precision,
  last_seen_at timestamptz,
  unique (chain_id, store_id_ext)
);

-- מוצרים (קטלוג מאוחד — לא ספציפי לרשת)
create table if not exists products (
  id uuid primary key default gen_random_uuid(),
  gtin text unique,                 -- ברקוד אחיד, null למוצרי שקילה
  canonical_name text not null,
  is_weighted boolean not null default false,
  category text,                    -- ממולא בהיסקה, אין שדה כזה במקור
  image_url text,
  created_at timestamptz not null default now()
);

-- שם המוצר כפי שהרשת עצמה קוראת לו (לצורך matching טקסטואלי במוצרי שקילה)
create table if not exists product_aliases (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id),
  chain_id text not null references chains(id),
  chain_item_code text not null,    -- הקוד הפנימי של הרשת למוצר הזה
  raw_name text not null,
  unique (chain_id, chain_item_code)
);

-- מחירים נוכחיים (דורס בכל עדכון — לא היסטוריה)
create table if not exists prices (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id),
  store_id uuid not null references stores(id),
  price numeric(10,2) not null,
  unit_price numeric(10,2),         -- מחיר ליחידת מידה (למשל ק"ג) כשרלוונטי
  unit_of_measure text,             -- 'kg' | 'liter' | 'unit' ...
  in_stock boolean not null default true,
  updated_at timestamptz not null default now(),
  unique (product_id, store_id)
);

-- מבצעים
create table if not exists promos (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id),
  store_id uuid not null references stores(id),
  description text,
  promo_price numeric(10,2),
  club_required boolean not null default false,
  valid_from timestamptz,
  valid_until timestamptz,
  updated_at timestamptz not null default now(),
  unique (product_id, store_id)
);

-- אימות קהילתי במחיר (הפיצ'ר "אמת באתר החנות")
create table if not exists price_confirmations (
  id uuid primary key default gen_random_uuid(),
  price_id uuid not null references prices(id),
  matches boolean not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_prices_store on prices(store_id);
create index if not exists idx_prices_product on prices(product_id);
create index if not exists idx_stores_chain on stores(chain_id);

-- משוב מהעמוד "עזרו לנו להשתפר"
create table if not exists feedback (
  id uuid primary key default gen_random_uuid(),
  message text not null,
  created_at timestamptz not null default now()
);
alter table feedback enable row level security;
-- כל אחד יכול לשלוח משוב. הערה חשובה: כל אחד גם יכול *לקרוא* משוב דרך
-- ה-API הזה כרגע, כי אין עדיין מערכת הרשאות אמיתית (admin אמיתי) -
-- פאנל הניהול באתר פשוט קורא מאותה טבלה עם אותו מפתח anon. זה בסדר
-- לשלב הזה (אין בפניות מידע רגיש), אבל כדאי לדעת שזו לא הגנה אמיתית.
create policy "public insert feedback" on feedback for insert with check (true);
create policy "public read feedback" on feedback for select using (true);

-- הודעת מערכת שמוצגת לכולם בראש האתר
create table if not exists site_banner (
  id integer primary key,
  message text not null default '',
  active boolean not null default false,
  updated_at timestamptz not null default now()
);
insert into site_banner (id, message, active) values (1, '', false)
  on conflict (id) do nothing;
alter table site_banner enable row level security;
-- קריאה פתוחה לכולם (כדי שהבאנר יוצג), אבל *אין* policy לכתיבה דרך
-- anon בכוונה - עדכון הבאנר מהאתר דורש הדבקת מפתח service_role אמיתי
-- (עוקף RLS), כדי שלא כל מבקר יוכל לשנות את ההודעה לכל האתר.
create policy "public read banner" on site_banner for select using (true);

-- אינדקס חיפוש טקסט חופשי בעברית (פשוט, ILIKE-friendly)
create extension if not exists pg_trgm;
create index if not exists idx_products_name on products using gin (canonical_name gin_trgm_ops);

-- חיפוש "חכם" שסובל שגיאות כתיב, בלי שום AI - משתמש ב-pg_trgm שכבר הפעלנו
-- למעלה. דומה (similarity) למילה שחיפשת, גם אם היא לא זהה באות-באות.
create or replace function search_products_fuzzy(q text, match_limit int default 60)
returns setof products
language sql stable
as $$
  select *
  from products
  where canonical_name ilike '%' || q || '%'
     or similarity(canonical_name, q) > 0.25
  order by
    (canonical_name ilike '%' || q || '%') desc,  -- התאמה מדויקת תמיד קודם
    similarity(canonical_name, q) desc
  limit match_limit;
$$;
grant execute on function search_products_fuzzy(text, int) to anon, authenticated;

-- ===== הרשאות =====
-- ה-frontend בדפדפן משתמש במפתח "anon" הציבורי (בטוח לחשיפה, זה כל הרעיון
-- שלו ב-Supabase) - ולכן חייבים RLS שמגביל אותו לקריאה בלבד. הכתיבה
-- (ה-ingest) משתמשת במפתח "service_role" שעוקף RLS, ואותו לעולם לא חושפים
-- בדפדפן - הוא חי רק כ-secret ב-GitHub Actions.

alter table chains enable row level security;
alter table stores enable row level security;
alter table products enable row level security;
alter table product_aliases enable row level security;
alter table prices enable row level security;
alter table promos enable row level security;
alter table price_confirmations enable row level security;

create policy "public read chains" on chains for select using (true);
create policy "public read stores" on stores for select using (true);
create policy "public read products" on products for select using (true);
create policy "public read prices" on prices for select using (true);
create policy "public read promos" on promos for select using (true);

-- אימות מחיר בסניף: כל אחד יכול "לדווח", אף אחד לא יכול לקרוא דיווחים גולמיים
-- של אחרים דרך ה-anon key (רק את המצטבר, שנחשב דרך view נפרד בהמשך).
create policy "public insert confirmations" on price_confirmations for insert with check (true);

-- ===================== v3: קטלוג מלא ברמת רשת =====================
-- לכל (מוצר, רשת) שורה אחת ב-prices (מול "סניף" וירטואלי בשם ALL של אותה רשת):
--   price = המחיר הזול ביותר בין הסניפים, price_max = הגבוה ביותר,
--   stores_carrying = בכמה סניפים המוצר נמצא, in_stock = האם הופיע בעדכון האחרון.
-- ככה הקטלוג המלא נכנס ב-500MB החינמיים (מאות אלפי שורות, לא עשרות מיליונים).
alter table prices add column if not exists price_max numeric(10,2);
alter table prices add column if not exists stores_carrying integer;

-- סטטוס משיכה לכל רשת: מתי הסתיימה משיכה מלאה לאחרונה, וכמה סניפים/מוצרים.
create table if not exists ingest_status (
  chain_id text primary key references chains(id) on delete cascade,
  last_attempt_at timestamptz,
  last_complete_at timestamptz,
  stores_total integer,
  products_total integer,
  complete boolean not null default false,
  note text
);
alter table ingest_status enable row level security;
drop policy if exists "public read ingest_status" on ingest_status;
create policy "public read ingest_status" on ingest_status for select using (true);
grant select on ingest_status to anon, authenticated;
grant select, insert, update, delete on ingest_status to service_role;

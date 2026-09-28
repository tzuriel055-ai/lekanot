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
  updated_at timestamptz not null default now()
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

-- אינדקס חיפוש טקסט חופשי בעברית (פשוט, ILIKE-friendly)
create extension if not exists pg_trgm;
create index if not exists idx_products_name on products using gin (canonical_name gin_trgm_ops);

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

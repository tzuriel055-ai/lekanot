-- ניקוי חד-פעמי של נתוני מחיר/מבצע ישנים ברמת סניף בודד.
-- בטוח להרצה: מוחק רק אצל רשתות שכבר נמשכו אצלן בהצלחה במלואן (יש להן last_complete_at
-- בטבלת ingest_status). רשת שעוד לא נמשכה בשיטה החדשה (למשל אושר עד, עד שהמחירים שלה
-- יפורסמו) לא נפגעת, ואפשר להריץ שוב בכל פעם שרשת נוספת מסיימת משיכה ראשונה.
delete from prices where store_id in (
  select s.id from stores s
  join ingest_status i on i.chain_id = s.chain_id and i.last_complete_at is not null
  where s.store_id_ext <> 'ALL'
);
delete from promos where store_id in (
  select s.id from stores s
  join ingest_status i on i.chain_id = s.chain_id and i.last_complete_at is not null
  where s.store_id_ext <> 'ALL'
);

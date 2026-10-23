-- להריץ פעם אחת, *אחרי* שהמשיכה החדשה (ingest) רצה בהצלחה לפחות פעם אחת.
-- מוחק את שורות המחיר/מבצע הישנות ברמת סניף בודד (נשארות רק שורות הרשת "ALL").
-- בלי זה האתר ימשיך להציג גם את הנתונים הישנים והחלקיים לצד החדשים.
delete from prices where store_id in (select id from stores where store_id_ext <> 'ALL');
delete from promos where store_id in (select id from stores where store_id_ext <> 'ALL');

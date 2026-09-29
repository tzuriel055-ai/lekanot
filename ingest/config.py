"""
רישום הרשתות שהמערכת יודעת למשוך מהן.
זה קובץ שאתה תעדכן ותרחיב עם הזמן — אין הגבלה מובנית על כמות הרשתות.

שלושת סוגי הפורטלים שקיימים בפועל:
  - "shufersal_direct"  — לרשת שופרסל יש פורטל שקיפות עצמאי משלה.
  - "carrefour_direct"  — לקרפור יש פורטל עצמאי דומה.
  - "cerberus"           — פורטל משותף (publishedprices.co.il) שמארח עשרות
                            רשתות קטנות/בינוניות, כולל רמי לוי ואחרות.
                            כל רשת מקבלת שם משתמש משלה על אותו פורטל.

הערה חשובה: לא בדקתי בעצמי את המבנה המדויק העדכני של כל פורטל (אין לי
גישת רשת מה-sandbox), כתבתי לפי המבנה המתועד/הידוע של המערכת הזו. בהרצה
הראשונה אצלך תצטרך לוודא/לתקן פרטים קטנים (שם שדה, נתיב URL) מול הפורטל
בפועל — ה-log ידפיס בדיוק איפה זה נכשל אם משהו לא תואם.
"""

from dataclasses import dataclass, field


@dataclass
class ChainConfig:
    id: str
    display_name: str
    portal_type: str
    # לפורטל cerberus: שם המשתמש הספציפי של הרשת באותו פורטל משותף
    portal_username: str = ""
    active: bool = True
    extra: dict = field(default_factory=dict)


CHAINS: list[ChainConfig] = [
    ChainConfig(
        id="shufersal",
        display_name="שופרסל",
        portal_type="shufersal_direct",
    ),
    ChainConfig(
        id="carrefour",
        display_name="קרפור (יינות ביתן לשעבר) - מושבת זמנית",
        portal_type="carrefour_direct",
        active=False,  # הפורטל שלהם דורש אינטראקציה, לא רק href סטטי - עוד לא פתרנו
    ),
    ChainConfig(
        id="rami-levy",
        display_name="רמי לוי",
        portal_type="cerberus",
        portal_username="RamiLevi",
    ),
    ChainConfig(
        id="victory",
        display_name="ויקטורי - מושבת זמנית",
        portal_type="cerberus",
        portal_username="victory",
        active=False,  # שם המשתמש בפורטל לא אומת עדיין
    ),
    ChainConfig(
        id="osherad",
        display_name="אושר עד",
        portal_type="cerberus",
        portal_username="osherad",
    ),
    ChainConfig(
        id="yohananof",
        display_name="יוחננוף",
        portal_type="cerberus",
        portal_username="yohananof",
    ),
    # הוסף עוד רשתות כאן באותו תבנית. כל רשת נוספת = עוד כמה שורות, לא
    # ארכיטקטורה חדשה.
]

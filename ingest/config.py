"""
רישום הרשתות. הוספת רשת = שורה אחת כאן, בלי שינוי ארכיטקטורה.

verified=True  : אומת בהרצה אמיתית. כשל ברשת כזו מכשיל את הריצה (מייל התראה מ-GitHub).
verified=False : שם המשתמש בפורטל המשותף ידוע לי מפרויקטי קוד פתוח של שקיפות מחירים,
                 אבל לא נבדק אצלנו. אם הוא שגוי - הרשת פשוט מדולגת עם אזהרה בלוג,
                 והריצה ממשיכה. תראה בלוג איזו רשת הצליחה ואיזו לא, ונתקן.

הפורטל המשותף (cerberus) מארח כ-13 רשתות; לרשתות עם פורטל עצמאי אחר
(קרפור, סופר-פארם, ויקטורי, חצי חינם ועוד) צריך אדפטר נפרד - ראה README.
"""

from dataclasses import dataclass, field


@dataclass
class ChainConfig:
    id: str
    display_name: str
    portal_type: str
    portal_username: str = ""
    active: bool = True
    verified: bool = True
    alt_usernames: tuple = ()   # מנוסים לפי הסדר אם הראשי נכשל; הלוג יגיד איזה עבד
    extra: dict = field(default_factory=dict)


CHAINS: list[ChainConfig] = [
    # --- מאומתות ---
    ChainConfig("shufersal", "שופרסל", "shufersal_direct"),
    ChainConfig("rami-levy", "רמי לוי", "cerberus", "RamiLevi"),
    ChainConfig("osherad", "אושר עד", "cerberus", "osherad"),
    ChainConfig("yohananof", "יוחננוף", "cerberus", "yohananof"),
    # --- הפורטל המשותף, שמות משתמש לא מאומתים אצלנו ---
    ChainConfig("tiv-taam", "טיב טעם", "cerberus", "TivTaam", verified=False),
    ChainConfig("keshet-teamim", "קשת טעמים", "cerberus", "Keshet", verified=False),
    ChainConfig("politzer", "פוליצר", "cerberus", "politzer", verified=False),
    ChainConfig("stop-market", "סטופ מרקט", "cerberus", "Stop_Market", verified=False),
    ChainConfig("salach-dabach", "סלאח דבאח", "cerberus", "SalachD", verified=False),
    ChainConfig("super-yuda", "סופר יודה", "cerberus", "yuda_ho", verified=False),
    ChainConfig("fresh-market", "פרש מרקט", "cerberus", "freshmarket", verified=False),
    ChainConfig("dor-alon", "אלונית (דור אלון)", "cerberus", "doralon", verified=False),
    ChainConfig("super-cofix", "סופר קופיקס", "cerberus", "SuperCofixApp", verified=False),
    ChainConfig("yellow", "ילו", "cerberus", "Yellow", verified=False,
                alt_usernames=("yellow", "Yellow_Ho", "yellow_ho", "YellowHo")),
    # --- מושבתות ---
    ChainConfig("victory", "ויקטורי", "cerberus", "victory", active=False, verified=False),
    ChainConfig("carrefour", "קרפור", "carrefour_direct", active=False, verified=False),
]

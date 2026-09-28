"""
אדפטר לפורטל המשותף "Cerberus" (publishedprices.co.il), שמארח עשרות רשתות.

זרימת העבודה (כפי שמתועד ע"י מפתחים שעבדו מול המערכת הזו):
  1. GET לעמוד הבית -> מקבלים session cookie + CSRF token חבוי ב-HTML/form.
  2. POST login עם username (לרוב אין סיסמה אמיתית — משתמשים בשם הרשת בלבד
     או בסיסמה גנרית שהרשת מפרסמת) + ה-CSRF token.
  3. עם ה-session, GET לרשימת הקבצים הזמינים (JSON/HTML), סינון לפי סוג
     (Price / PriceFull / Promo / PromoFull / Stores) והכי עדכני מכל סוג.
  4. הורדת כל קובץ (gzip).

*** הערה: לא הרצתי את זה בפועל מול השרת האמיתי (אין לי גישת רשת מה-sandbox
כרגע), כך שייתכן שנקודת הקצה המדויקת (path, שם שדה ב-form) תזדקק לכיוונון
קטן בהרצה הראשונה אצלך. הקוד בנוי כך שקל לתקן שורה אחת אם זה קורה — ה-log
ידפיס את קוד הסטטוס ואת התגובה הגולמית. ***
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

from .base import FileRef

PORTAL_BASE = "https://url.publishedprices.co.il"


class CerberusAdapter:
    def __init__(self, username: str, password: str = ""):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._logged_in = False

    def _login(self) -> None:
        if self._logged_in:
            return
        home = self.session.get(f"{PORTAL_BASE}/login", timeout=30)
        home.raise_for_status()
        csrf_match = re.search(r'name="csrftoken"\s+value="([^"]+)"', home.text)
        csrf = csrf_match.group(1) if csrf_match else ""

        resp = self.session.post(
            f"{PORTAL_BASE}/login/user",
            data={
                "username": self.username,
                "password": self.password,
                "csrftoken": csrf,
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._logged_in = True

    def list_files(self) -> Iterable[FileRef]:
        self._login()
        resp = self.session.get(
            f"{PORTAL_BASE}/file/json/dir",
            params={"sort": "time", "date": ""},
            timeout=30,
        )
        resp.raise_for_status()
        entries = resp.json()
        # ה-JSON הוא בד"כ list של {"fname": "...", "size": ..., "time": "..."}
        for entry in entries if isinstance(entries, list) else entries.get("data", []):
            fname = entry.get("fname") or entry.get("name")
            if not fname:
                continue
            kind = _classify(fname)
            if kind is None:
                continue
            store_id = _extract_store_id(fname)
            yield FileRef(
                kind=kind,
                store_id_ext=store_id,
                url=f"{PORTAL_BASE}/file/d/{fname}",
                label=fname,
            )

    def download(self, ref: FileRef) -> bytes:
        self._login()
        resp = self.session.get(ref.url, timeout=120)
        resp.raise_for_status()
        return resp.content


def _classify(fname: str) -> str | None:
    lower = fname.lower()
    if lower.startswith("storesfull") or lower.startswith("stores"):
        return "stores"
    if lower.startswith("promofull") or lower.startswith("promo"):
        return "promos"
    if lower.startswith("pricefull") or lower.startswith("price"):
        return "prices"
    return None


def _extract_store_id(fname: str) -> str | None:
    # מוסכמת שם קובץ נפוצה: PriceFull<ChainId>-<StoreId>-<Timestamp>.gz
    m = re.search(r"-(\d{3,4})-\d{8,}", fname)
    return m.group(1) if m else None

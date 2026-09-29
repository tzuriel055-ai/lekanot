"""
אדפטר לפורטל המשותף "Cerberus" (url.publishedprices.co.il), שמארח עשרות
רשתות, ביניהן רמי לוי ויוחננוף.

הזרימה כאן מבוססת על יישום אמיתי שמצאתי ובדקתי (לא ניחוש):
  1. GET /login -> שומרים cookies, מוצאים csrftoken בתגית
     <meta name="csrftoken" content="...">.
  2. POST /login/user עם username, password ריקה (כן, ריקה - ככה הפורטל
     עובד בפועל לרשתות האלה), וה-csrftoken. בלי לעקוב אחרי redirect.
  3. GET /file -> מקבלים csrftoken *מעודכן* (שונה מזה של הלוגין).
  4. POST /file/json/dir עם csrftoken, iDisplayStart, iDisplayLength, cd=/
     -> מחזיר רשימת קבצים. מחלצים "fname":"..." ברגקס במקום לסמוך על
     JSON נקי, כי הפורמט לא תמיד עקבי.
  5. GET /file/d/<fname> להורדה בפועל.

חשוב: חלק מהרשתות (רמי לוי בפועל) דוחסות ב-ZIP רגיל ולא ב-gzip. הפענוח
עצמו (parser.decompress) כבר יודע לזהות ולטפל בשני הסוגים.
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

from .base import FileRef

PORTAL_BASE = "https://url.publishedprices.co.il"
_UA = "Mozilla/5.0 (compatible; lekanot-ingest/1.0)"


class CerberusAdapter:
    def __init__(self, username: str, password: str = ""):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _UA
        self._logged_in = False

    def _extract_csrf(self, html: str) -> str:
        m = re.search(r'name="csrftoken"\s+content="([^"]+)"', html)
        if not m:
            # חלק מהעמודים שמים את זה כ-cookie ולא ב-meta
            return self.session.cookies.get("csrftoken", "")
        return m.group(1)

    def _login(self) -> None:
        if self._logged_in:
            return
        home = self.session.get(f"{PORTAL_BASE}/login", timeout=30)
        home.raise_for_status()
        csrf = self._extract_csrf(home.text)

        self.session.post(
            f"{PORTAL_BASE}/login/user",
            data={"username": self.username, "password": self.password, "csrftoken": csrf},
            allow_redirects=False,
            timeout=30,
        )
        self._logged_in = True

    def list_files(self) -> Iterable[FileRef]:
        self._login()

        # אחרי הלוגין, מבקרים בעמוד הקבצים כדי לקבל csrftoken מעודכן -
        # זה שהתקבל בלוגין לא בהכרח תקף לבקשת רשימת הקבצים.
        file_page = self.session.get(f"{PORTAL_BASE}/file", timeout=30)
        csrf = self._extract_csrf(file_page.text) or self.session.cookies.get("csrftoken", "")

        resp = self.session.post(
            f"{PORTAL_BASE}/file/json/dir",
            data={"csrftoken": csrf, "iDisplayStart": "0", "iDisplayLength": "5000", "cd": "/"},
            timeout=30,
        )
        resp.raise_for_status()

        # רגקס במקום resp.json(): הפורמט לא תמיד JSON נקי, וזה מה שעבד בפועל.
        fnames = re.findall(r'"fname":"([^"]+)"', resp.text)
        if not fnames:
            raise RuntimeError(
                f"no files found in portal response (first 300 chars): {resp.text[:300]!r}"
            )

        for fname in fnames:
            kind = _classify(fname)
            if kind is None:
                continue
            yield FileRef(
                kind=kind,
                store_id_ext=_extract_store_id(fname),
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
    if "storesfull" in lower or lower.startswith("stores"):
        return "stores"
    if "promofull" in lower or lower.startswith("promo"):
        return "promos"
    if "pricefull" in lower or lower.startswith("price"):
        return "prices"
    return None


def _extract_store_id(fname: str) -> str | None:
    # מוסכמת שם קובץ נפוצה: PriceFull<ChainId>-<StoreId>-<Timestamp>...
    m = re.search(r"-(\d{3,4})-\d{6,}", fname)
    return m.group(1) if m else None

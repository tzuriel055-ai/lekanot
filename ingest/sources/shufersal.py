"""
אדפטר לפורטל השקיפות העצמאי של שופרסל.

מבוסס על URL אמיתי שנבדק בפועל, לא ניחוש:
  https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=<N>&storeId=0&page=1

כאשר catID=2 הוא קטגוריית קבצי המחירים (Price/PriceFull), ו-catID=5 הוא
קטגוריית קבצי החנויות (Stores). storeId=0 מחזיר קבצים מכל הסניפים.

זה מביא רק את page=1 - העמוד הראשון של הרשימה. יש עוד עמודים (בדומה למה
שראינו בפורטל המקביל של קרפור), אז זה כרגע מכסה חלק מהסניפים, לא את כולם.
זה מספיק כדי לוודא שהצינור עובד; הרחבת הדפדוף לכל העמודים היא שדרוג פשוט
בהמשך, לא שינוי מבני.
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

from .base import FileRef

PORTAL_BASE = "https://prices.shufersal.co.il"
_UA = "Mozilla/5.0 (compatible; lekanot-ingest/1.0)"

# catID לפי סוג קובץ - מאומת עבור prices ו-stores, לא מאומת עבור promos
_CAT_ID = {"prices": 2, "stores": 5}


class ShufersalAdapter:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _UA

    def list_files(self) -> Iterable[FileRef]:
        for kind, cat_id in _CAT_ID.items():
            resp = self.session.get(
                f"{PORTAL_BASE}/FileObject/UpdateCategory",
                params={"catID": cat_id, "storeId": 0, "page": 1},
                timeout=75,
            )
            resp.raise_for_status()
            for href in re.findall(r'href="([^"]+\.gz[^"]*)"', resp.text):
                url = (href if href.startswith("http") else f"{PORTAL_BASE}{href}").replace("&amp;", "&")
                fname = href.split("/")[-1].split("?")[0]
                yield FileRef(kind=kind, store_id_ext=_extract_store_id(fname), url=url, label=fname)

    def download(self, ref: FileRef) -> bytes:
        resp = self.session.get(ref.url, timeout=120)
        resp.raise_for_status()
        return resp.content


def _extract_store_id(fname: str) -> str | None:
    m = re.search(r"-(\d{3,4})-\d{6,}", fname)
    return m.group(1) if m else None

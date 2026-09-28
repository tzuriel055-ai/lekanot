"""
אדפטר לפורטל השקיפות העצמאי של שופרסל.

בשונה מ-Cerberus, לשופרסל יש אתר ייעודי משלה לפרסום הקבצים, בדרך כלל בלי
דרישת login לצפייה/הורדה (עמידה בחוק ע"י פרסום פתוח). מבנה העמוד עצמו
(רשימת קבצים כ-HTML/JSON) עשוי להשתנות — הפונקציה list_files סורקת את
עמוד האינדקס ומחלצת קישורי .gz.
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

from .base import FileRef

PORTAL_BASE = "https://prices.shufersal.co.il"


class ShufersalAdapter:
    def __init__(self) -> None:
        self.session = requests.Session()

    def list_files(self) -> Iterable[FileRef]:
        resp = self.session.get(f"{PORTAL_BASE}/FileObject/UpdateCategory", timeout=30)
        resp.raise_for_status()
        # מחלצים קישורי הורדה מתוך ה-HTML המוחזר
        for href in re.findall(r'href="([^"]+\.gz)"', resp.text):
            url = href if href.startswith("http") else f"{PORTAL_BASE}{href}"
            fname = href.rsplit("/", 1)[-1]
            kind = _classify(fname)
            if kind is None:
                continue
            yield FileRef(
                kind=kind,
                store_id_ext=_extract_store_id(fname),
                url=url,
                label=fname,
            )

    def download(self, ref: FileRef) -> bytes:
        resp = self.session.get(ref.url, timeout=120)
        resp.raise_for_status()
        return resp.content


def _classify(fname: str) -> str | None:
    lower = fname.lower()
    if "storesfull" in lower or "stores" in lower:
        return "stores"
    if "promofull" in lower or "promo" in lower:
        return "promos"
    if "pricefull" in lower or "price" in lower:
        return "prices"
    return None


def _extract_store_id(fname: str) -> str | None:
    m = re.search(r"-(\d{3,4})-\d{8,}", fname)
    return m.group(1) if m else None

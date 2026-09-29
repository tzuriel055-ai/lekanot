"""
אדפטר לפורטל השקיפות העצמאי של קרפור ישראל.

מושבת כרגע (config.py -> active=False): בדיקה ישירה של האתר הראתה שהוא
בנוי כך שרשימת הקבצים נטענת דרך JavaScript/ווידג'ט דפדוף, לא כקישורי
href סטטיים בתוך ה-HTML הראשוני - אז הגרסה הפשוטה הזו לא תמצא קבצים.
נשאר כאן כשלד למימוש עתידי, לא נמחק, כדי לא לאבד את המבנה כשנחזור לזה.
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

from .base import FileRef

PORTAL_BASE = "https://prices.carrefour.co.il"


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
    m = re.search(r"-(\d{3,4})-\d{6,}", fname)
    return m.group(1) if m else None


class CarrefourAdapter:
    def __init__(self) -> None:
        self.session = requests.Session()

    def list_files(self) -> Iterable[FileRef]:
        resp = self.session.get(f"{PORTAL_BASE}/", timeout=30)
        resp.raise_for_status()
        for href in re.findall(r'href="([^"]+\.gz)"', resp.text):
            url = href if href.startswith("http") else f"{PORTAL_BASE}{href}"
            fname = href.rsplit("/", 1)[-1]
            kind = _classify(fname)
            if kind is None:
                continue
            yield FileRef(kind=kind, store_id_ext=_extract_store_id(fname), url=url, label=fname)

    def download(self, ref: FileRef) -> bytes:
        resp = self.session.get(ref.url, timeout=120)
        resp.raise_for_status()
        return resp.content

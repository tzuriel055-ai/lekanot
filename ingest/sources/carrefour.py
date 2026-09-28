"""
אדפטר לפורטל השקיפות העצמאי של קרפור ישראל (מבנה דומה לזה של שופרסל —
פרסום פתוח, בלי login). כמו בשאר האדפטרים: כתוב מתוך ההבנה המתועדת של
מבנה הפורסום הכללי, ולא נבדק מול שרת אמיתי מתוך ה-sandbox.
"""

from __future__ import annotations

import re
from typing import Iterable

import requests

from .base import FileRef
from .shufersal import _classify, _extract_store_id  # אותה לוגיקת סיווג קבצים

PORTAL_BASE = "https://prices.carrefour.co.il"


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

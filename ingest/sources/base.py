"""
בסיס משותף לכל אדפטרי הפורטלים:
  - FileRef: קובץ בודד ברשימת הקבצים של פורטל.
  - parse_filename: מזהה סוג קובץ, סניף וחותמת זמן משם הקובץ.
  - select_latest: לכל (סוג, סניף) בוחר את הקובץ הכי חדש.
  - get_bytes: הורדה עם ניסיונות חוזרים.

הבחנה קריטית (זו הייתה הסיבה לנתונים החלקיים עד עכשיו): הרשתות מפרסמות
  PriceFull  - הקטלוג המלא של הסניף, פעם ביום (או כמה)
  Price      - עדכוני שינויים בלבד, כמה פעמים ביום (לפעמים 2-5 פריטים בקובץ)
אסור לבלבל ביניהם. רק PriceFull מייצג "מה יש בסניף".
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests


class PortalAccessError(Exception):
    """הפורטל לא החזיר קבצים (שם משתמש שגוי / התחברות נכשלה / פורטל שונה)."""


@dataclass
class FileRef:
    kind: str        # prices_full | prices_delta | promos_full | promos_delta | stores
    store_key: str   # מזהה סניף (כולל תת-רשת), למשל "001-012"
    ts: str          # חותמת זמן ספרתית מהשם, להשוואה לקסיקוגרפית
    url: str
    label: str
    meta: dict = field(default_factory=dict)


_KIND_MAP = {
    "pricefull": "prices_full",
    "price": "prices_delta",
    "promofull": "promos_full",
    "promo": "promos_delta",
    "storesfull": "stores",
    "stores": "stores",
}


def parse_filename(fname: str):
    """מחזיר (kind, store_key, ts) או None אם השם לא מוכר."""
    stem = fname.rsplit("/", 1)[-1].split("?")[0]
    for _ in range(3):
        stem = re.sub(r"\.(gz|xml|zip)$", "", stem, flags=re.I)
    m = re.match(r"^([A-Za-z]+)(\d+)-(.+)$", stem)
    if not m:
        return None
    kind = _KIND_MAP.get(m.group(1).lower())
    if not kind:
        return None
    tokens = m.group(3).split("-")
    ts_tokens: list[str] = []
    digits = 0
    while tokens and tokens[-1].isdigit():
        t = tokens.pop()
        ts_tokens.insert(0, t)
        digits += len(t)
        if digits >= 12 or (len(t) == 8 and t.startswith("20")):
            break
    if digits < 8:
        return None
    return kind, "-".join(tokens) or "0", "".join(ts_tokens)


def build_ref(fname: str, url: str, meta: dict | None = None) -> FileRef | None:
    parsed = parse_filename(fname)
    if not parsed:
        return None
    kind, store_key, ts = parsed
    return FileRef(kind=kind, store_key=store_key, ts=ts, url=url, label=fname, meta=meta or {})


def select_latest(refs: list[FileRef]) -> dict[tuple[str, str], FileRef]:
    latest: dict[tuple[str, str], FileRef] = {}
    for r in refs:
        key = (r.kind, r.store_key)
        cur = latest.get(key)
        if cur is None or r.ts > cur.ts:
            latest[key] = r
    return latest


def get_bytes(session: requests.Session, url: str, *, params=None, timeout: int = 180, retries: int = 3):
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"GET {url[:80]} -> {r.status_code}")
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (400, 401, 403, 404):
                raise
            time.sleep(3 * (attempt + 1))
    assert last is not None
    raise last

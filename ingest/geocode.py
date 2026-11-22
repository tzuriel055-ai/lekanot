"""
מציאת קואורדינטות לסניפים - חינם לגמרי (OpenStreetMap Nominatim), פעם אחת לכל סניף, ונשמר לתמיד.

  python -m ingest.geocode

מדיניות Nominatim: מקסימום בקשה אחת בשנייה + User-Agent שמזהה את היישום. לכן יש השהיה של
~1.1 שניות בין בקשות, ובכל ריצה מטפלים בעד GEOCODE_MAX_PER_RUN סניפים - הריצה הבאה ממשיכה
מאיפה שעצרנו (סניף שכבר טופל לא נשאל שוב). אם הכתובת המדויקת לא נמצאה, נופלים לעיר בלבד
ומסמנים geocode_approx=true - כדי שהאתר לא יציג מרחק מדויק כשהוא לא.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests

from . import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("geocode")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "lekanot-price-comparison/1.0 (+https://github.com/tzuriel055-ai/lekanot)"
DELAY = float(os.environ.get("GEOCODE_DELAY_SEC", "1.1"))
MAX_PER_RUN = int(os.environ.get("GEOCODE_MAX_PER_RUN", "1500"))
# תיבת גבולות גסה של ישראל והשטחים - דוחה תוצאות שגויות שנופלות הרחק מהמדינה
LAT_RANGE, LNG_RANGE = (29.3, 33.5), (34.1, 36.0)


class RateLimited(Exception):
    pass


def in_israel(lat: float, lng: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]


def query(session: requests.Session, q: str):
    r = session.get(NOMINATIM, params={"format": "jsonv2", "limit": "1", "countrycodes": "il",
                                       "accept-language": "he", "q": q}, timeout=30)
    if r.status_code == 429:
        raise RateLimited()
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    lat, lng = float(rows[0]["lat"]), float(rows[0]["lon"])
    return (lat, lng) if in_israel(lat, lng) else None


def clean(v) -> str:
    v = (v or "").strip()
    return "" if v in ("", "0", "-", "לא ידוע", "unknown", "null") else v


def candidates(store: dict) -> list[tuple[str, bool]]:
    """רשימת שאילתות לפי סדר: כתובת מדויקת, ואז העיר בלבד (מסומן כמקורב)."""
    addr, city = clean(store.get("address")), clean(store.get("city"))
    out: list[tuple[str, bool]] = []
    if addr and city:
        out.append((f"{addr}, {city}", False))
    elif addr:
        out.append((addr, False))
    if city:
        out.append((city, True))
    return out


def main() -> None:
    stores = db.select_all(
        "stores", "id,chain_id,name,city,address",
        {"lat": "is.null", "geocode_failed": "eq.false", "store_id_ext": "neq.ALL"}, order="id")
    todo = stores[:MAX_PER_RUN]
    log.info("%d stores need coordinates; handling %d this run", len(stores), len(todo))

    session = requests.Session()
    session.headers["User-Agent"] = UA
    cache: dict[str, tuple | None] = {}
    ok = approx = failed = 0
    for i, store in enumerate(todo, 1):
        now = datetime.now(timezone.utc).isoformat()
        found, is_approx = None, False
        for q, approx_flag in candidates(store):
            if q not in cache:
                try:
                    cache[q] = query(session, q)
                except RateLimited:
                    log.warning("rate limited by Nominatim, waiting 60s")
                    time.sleep(60)
                    try:
                        cache[q] = query(session, q)
                    except RateLimited:
                        log.error("still rate limited - stopping this run, the next run continues")
                        return
                except requests.RequestException as exc:
                    log.warning("request failed for %r: %s", q, exc)
                    cache[q] = None
                time.sleep(DELAY)
            if cache[q]:
                found, is_approx = cache[q], approx_flag
                break
        if found:
            db.update("stores", {"id": store["id"]}, {"lat": found[0], "lng": found[1], "geocoded_at": now,
                                                      "geocode_failed": False, "geocode_approx": is_approx})
            ok += 1
            approx += is_approx
        else:
            db.update("stores", {"id": store["id"]}, {"geocode_failed": True, "geocoded_at": now})
            failed += 1
        if i % 100 == 0:
            log.info("progress %d/%d (ok=%d approx=%d failed=%d)", i, len(todo), ok, approx, failed)
    log.info("DONE: ok=%d (of which approximate=%d) failed=%d remaining=%d", ok, approx, failed, len(stores) - len(todo))


if __name__ == "__main__":
    main()

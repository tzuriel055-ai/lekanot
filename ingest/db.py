"""
שכבת כתיבה ל-Supabase, דרך ה-REST API שלו (PostgREST) — כדי לא לדרוש
נהג psycopg מקומי ולהשאר פשוט על GitHub Actions.

דורש שני secrets בסביבה: SUPABASE_URL ו-SUPABASE_SERVICE_KEY
(ה-service key, לא ה-anon key — כי אנחנו כותבים, לא רק קוראים).
"""

from __future__ import annotations

import os
from typing import Any

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation",
}
if not SUPABASE_KEY.startswith("sb_"):
    # מפתחות ישנים (JWT) נשלחים גם ב-Authorization; מפתחות חדשים (sb_...) לא
    HEADERS["Authorization"] = f"Bearer {SUPABASE_KEY}"


def upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> list[dict]:
    if not rows:
        return []
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        params={"on_conflict": on_conflict},
        headers=HEADERS,
        json=rows,
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"Supabase upsert into {table} failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def select_one(table: str, filters: dict[str, str]) -> dict | None:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    params["limit"] = "1"
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def select_many(table: str, select: str = "*", limit: int = 100, **filters: str) -> list[dict]:
    params = {"select": select, "limit": str(limit)}
    params.update(filters)
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upload_image(bucket: str, path: str, content: bytes, content_type: str) -> str:
    """מעלה קובץ ל-Supabase Storage (bucket חייב להיות public, נוצר פעם אחת
    ידנית ב-Dashboard). מחזיר את ה-URL הציבורי הקבוע של הקובץ."""
    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",  # דורס אם כבר קיים, כדי שריצה חוזרת לא תיכשל
        },
        data=content,
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"Supabase storage upload failed ({resp.status_code}): {resp.text[:300]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"

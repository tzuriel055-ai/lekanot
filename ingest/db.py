"""
שכבת גישה ל-Supabase דרך REST (PostgREST), בלי נהג DB מקומי.

דורש secrets בסביבה: SUPABASE_URL ו-SUPABASE_SERVICE_KEY (מפתח service, לא anon).

עיקרון: כתיבה *בבאצ'ים* וקריאה *מדפדפת*. קריאה אחת לכל מוצר היא מה שהאט
את הריצות הקודמות (300 מוצרים לקחו כמעט שתי דקות).
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
if not SUPABASE_KEY.startswith("sb_"):
    # מפתחות ישנים (JWT) נשלחים גם ב-Authorization; מפתחות חדשים (sb_...) לא
    HEADERS["Authorization"] = f"Bearer {SUPABASE_KEY}"


def _req(method: str, path: str, *, params=None, headers=None, json_body=None, timeout: int = 90, retries: int = 3):
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.request(
                method, f"{SUPABASE_URL}{path}", params=params,
                headers={**HEADERS, **(headers or {})}, json=json_body, timeout=timeout,
            )
            if resp.status_code >= 500 or resp.status_code == 429:
                last = RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    assert last is not None
    raise last


def upsert(
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
    *,
    ignore_duplicates: bool = False,
    returning: bool = False,
    batch: int = 500,
) -> list[dict]:
    """הכנסה/עדכון בבאצ'ים. חשוב: כל השורות בקריאה חייבות לכלול אותם מפתחות
    (אחרת PostgREST ישים NULL בעמודות חסרות ויידרוס נתונים קיימים)."""
    out: list[dict] = []
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        prefer = "resolution=ignore-duplicates" if ignore_duplicates else "resolution=merge-duplicates"
        prefer += ",return=representation" if returning else ",return=minimal"
        resp = _req("POST", f"/rest/v1/{table}", params={"on_conflict": on_conflict},
                    headers={"Prefer": prefer}, json_body=chunk)
        if not resp.ok:
            raise RuntimeError(f"Supabase upsert into {table} failed ({resp.status_code}): {resp.text[:500]}")
        if returning:
            out.extend(resp.json())
    return out


def select_all(table: str, select: str, filters: dict[str, str] | None = None, order: str = "id", page: int = 1000) -> list[dict]:
    """קריאה של כל השורות המתאימות, בדפים (Supabase מגביל ל-1000 שורות בקריאה)."""
    out: list[dict] = []
    offset = 0
    while True:
        params = {"select": select, "order": order, "limit": str(page), "offset": str(offset), **(filters or {})}
        resp = _req("GET", f"/rest/v1/{table}", params=params)
        if not resp.ok:
            raise RuntimeError(f"Supabase select from {table} failed ({resp.status_code}): {resp.text[:500]}")
        rows = resp.json()
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


def delete(table: str, filters: dict[str, str]) -> None:
    if not filters:
        raise ValueError("refusing to delete without filters")
    resp = _req("DELETE", f"/rest/v1/{table}", params=filters, headers={"Prefer": "return=minimal"})
    if not resp.ok:
        raise RuntimeError(f"Supabase delete on {table} failed ({resp.status_code}): {resp.text[:500]}")


def select_one(table: str, filters: dict[str, str]) -> dict | None:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    params["limit"] = "1"
    resp = _req("GET", f"/rest/v1/{table}", params=params, timeout=30)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def select_many(table: str, select: str = "*", limit: int = 100, **filters: str) -> list[dict]:
    params = {"select": select, "limit": str(limit)}
    params.update(filters)
    resp = _req("GET", f"/rest/v1/{table}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def update(table: str, filters: dict[str, str], values: dict[str, Any]) -> list[dict]:
    """עדכון שורות קיימות בלבד (PATCH), לא INSERT."""
    params = {k: f"eq.{v}" for k, v in filters.items()}
    resp = _req("PATCH", f"/rest/v1/{table}", params=params,
                headers={"Prefer": "return=representation"}, json_body=values, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Supabase update on {table} failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def upload_image(bucket: str, path: str, content: bytes, content_type: str) -> str:
    """מעלה קובץ ל-Supabase Storage (bucket ציבורי). מחזיר URL ציבורי."""
    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": content_type, "x-upsert": "true"},
        data=content, timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"Supabase storage upload failed ({resp.status_code}): {resp.text[:300]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"

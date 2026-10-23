"""
אדפטר לפורטל המשותף "Cerberus" (url.publishedprices.co.il) - מארח כ-13 רשתות.
כל רשת = שם משתמש משלה, סיסמה ריקה. הזרימה אומתה בהרצה אמיתית (רמי לוי,
אושר עד, יוחננוף):
  1. GET /login -> csrftoken מתוך <meta name="csrftoken">
  2. POST /login/user (username, password ריקה, csrftoken)
  3. GET /file -> csrftoken מעודכן
  4. POST /file/json/dir -> רשימת קבצים (מדפדף עם iDisplayStart)
  5. GET /file/d/<fname> -> הורדה (gzip או zip)
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

import requests

from .base import FileRef, PortalAccessError, build_ref, get_bytes

log = logging.getLogger("cerberus")

PORTAL_BASE = "https://url.publishedprices.co.il"
_UA = "Mozilla/5.0 (compatible; lekanot-ingest/2.0)"
_PAGE = 2000


class CerberusAdapter:
    def __init__(self, username: str, password: str = ""):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _UA
        self._logged_in = False
        self.listing_complete = True  # יהפוך False אם הדפדוף נקטע באמצע

    def _csrf(self, html: str) -> str:
        m = re.search(r'name="csrftoken"\s+content="([^"]+)"', html)
        return m.group(1) if m else self.session.cookies.get("csrftoken", "")

    def _login(self) -> None:
        if self._logged_in:
            return
        home = get_bytes(self.session, f"{PORTAL_BASE}/login", timeout=30)
        self.session.post(
            f"{PORTAL_BASE}/login/user",
            data={"username": self.username, "password": self.password, "csrftoken": self._csrf(home.text)},
            allow_redirects=False, timeout=30,
        )
        self._logged_in = True

    def list_files(self) -> Iterable[FileRef]:
        self._login()
        csrf = self._csrf(get_bytes(self.session, f"{PORTAL_BASE}/file", timeout=30).text)
        seen: set[str] = set()
        out: list[FileRef] = []
        start = 0
        while True:
            try:
                resp = self.session.post(
                    f"{PORTAL_BASE}/file/json/dir",
                    data={"csrftoken": csrf, "iDisplayStart": str(start), "iDisplayLength": str(_PAGE), "cd": "/"},
                    timeout=60,
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                if start == 0:
                    raise
                log.warning("%s: listing cut at offset %d (%s)", self.username, start, exc)
                self.listing_complete = False
                break
            names = re.findall(r'"fname":"([^"]+)"', resp.text)
            if not names:
                if start == 0:
                    raise PortalAccessError(
                        f"no files for username '{self.username}' - wrong username, or login failed "
                        f"(first 120 chars: {resp.text[:120]!r})"
                    )
                break
            fresh = [n for n in names if n not in seen]
            if not fresh:
                break
            for n in fresh:
                seen.add(n)
                ref = build_ref(n, f"{PORTAL_BASE}/file/d/{n}")
                if ref:
                    out.append(ref)
            if len(names) < _PAGE:
                break
            start += _PAGE
            if start > 200_000:
                self.listing_complete = False
                break
        return out

    def download(self, ref: FileRef) -> bytes:
        self._login()
        return get_bytes(self.session, ref.url, timeout=180).content

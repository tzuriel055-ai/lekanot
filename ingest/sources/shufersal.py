"""
אדפטר לפורטל השקיפות העצמאי של שופרסל.

  https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=<N>&storeId=0&page=<P>
catID: 2=PriceFull, 5=Stores (אומתו בהרצה אמיתית), 4=PromoFull (לא אומת - סוג
הקובץ נקבע ממילא לפי שם הקובץ עצמו, כך שקטגוריה לא נכונה פשוט לא תניב כלום).

הקישורים לקבצים הם קישורי Azure Blob זמניים. אם קישור פג תוקף באמצע ריצה
ארוכה (403) - מרעננים אותו מאותו עמוד ברשימה, פעם אחת.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

import requests

from .base import FileRef, build_ref, get_bytes

log = logging.getLogger("shufersal")

PORTAL_BASE = "https://prices.shufersal.co.il"
_UA = "Mozilla/5.0 (compatible; lekanot-ingest/2.0)"
_CATS = (5, 2, 4)
_MAX_PAGES = 150
_LINK_RE = re.compile(r'href="([^"]+\.(?:gz|xml|zip)[^"]*)"', re.I)


def _url_and_name(href: str) -> tuple[str, str]:
    url = (href if href.startswith("http") else f"{PORTAL_BASE}{href}").replace("&amp;", "&")
    return url, url.split("?")[0].rsplit("/", 1)[-1]


class ShufersalAdapter:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _UA
        self.listing_complete = True
        self.unparsed: list[str] = []
        self.unparsed_count = 0

    def _page(self, cat: int, page: int) -> str:
        return get_bytes(
            self.session, f"{PORTAL_BASE}/FileObject/UpdateCategory",
            params={"catID": cat, "storeId": 0, "page": page}, timeout=90,
        ).text

    def list_files(self) -> Iterable[FileRef]:
        seen: set[str] = set()
        out: list[FileRef] = []
        for cat in _CATS:
            exhausted = False
            for page in range(1, _MAX_PAGES + 1):
                try:
                    html = self._page(cat, page)
                except requests.RequestException as exc:
                    if page == 1 and cat == 2:
                        raise
                    log.warning("shufersal: listing cat=%s page=%s failed (%s)", cat, page, exc)
                    if cat == 2:
                        self.listing_complete = False
                    exhausted = True
                    break
                hrefs = _LINK_RE.findall(html)
                fresh = 0
                for href in hrefs:
                    url, fname = _url_and_name(href)
                    if fname in seen:
                        continue
                    seen.add(fname)
                    fresh += 1
                    ref = build_ref(fname, url, meta={"cat": cat, "page": page})
                    if ref:
                        out.append(ref)
                    else:
                        self.unparsed_count += 1
                        if len(self.unparsed) < 8:
                            self.unparsed.append(fname)
                if not hrefs or fresh == 0:
                    exhausted = True
                    break
            if not exhausted and cat == 2:
                self.listing_complete = False  # הגענו לתקרת העמודים בלי לראות סוף
        return out

    def download(self, ref: FileRef) -> bytes:
        try:
            return get_bytes(self.session, ref.url, timeout=180).content
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) not in (400, 401, 403) or not ref.meta:
                raise
        # קישור שפג תוקפו: מושכים מחדש את אותו עמוד ומחפשים את אותו קובץ
        html = self._page(ref.meta["cat"], ref.meta["page"])
        for href in _LINK_RE.findall(html):
            url, fname = _url_and_name(href)
            if fname == ref.label:
                ref.url = url
                return get_bytes(self.session, url, timeout=180).content
        raise RuntimeError(f"could not refresh expired link for {ref.label}")

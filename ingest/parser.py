"""
פרסר זורם (iterparse) לקובצי XML של חוק שקיפות המחירים.

- קבצים יכולים להיות gzip, zip (רמי לוי) או XML גולמי; בקידוד UTF-8/16 וכו'.
- שמות תגיות משתנים בין רשתות (רישיות, namespace) - הכל מנורמל ל-lowercase.
- iterparse מונע טעינה של קובץ של עשרות מגה לזיכרון בבת אחת.
"""

from __future__ import annotations

import gzip
import io
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterator, NamedTuple
from xml.etree import ElementTree as ET


def decompress(payload: bytes) -> bytes:
    if payload[:2] == b"\x1f\x8b":
        return gzip.decompress(payload)
    if payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = zf.namelist()
            if not names:
                raise ValueError("zip archive is empty")
            return zf.read(names[0])
    return payload


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def _bool(value) -> bool:
    return value is not None and str(value).strip().lower() in ("1", "true")


# ------------------------------ ברקוד ------------------------------

def norm_gtin(code) -> str | None:
    """מנרמל ברקוד לצורה אחידה בין רשתות (EAN-13/GTIN-14, בלי תלות באפסים מובילים)."""
    c = (code or "").strip()
    if not c.isdigit():
        return None
    c = c.lstrip("0")
    if not (7 <= len(c) <= 14):
        return None
    return c.zfill(13) if len(c) <= 13 else c.zfill(14)


def to_gtin(code, itemtype, weighted) -> str | None:
    """האם הפריט הזה הוא מוצר עם ברקוד אמיתי? (ItemType=1 לפי הסכמה הרשמית)."""
    if weighted or itemtype == "0":
        return None
    c = (code or "").strip()
    min_len = 8 if itemtype == "1" else 12
    if not c.isdigit() or len(c) < min_len:
        return None
    return norm_gtin(c)


# ------------------------------ מחירים ------------------------------

class PriceRow(NamedTuple):
    code: str
    name: str
    price: Decimal
    unit_price: Decimal | None
    unit: str | None
    weighted: bool
    itemtype: str | None


def iter_price_rows(payload: bytes) -> Iterator[PriceRow]:
    for _ev, el in ET.iterparse(io.BytesIO(decompress(payload)), events=("end",)):
        if _local(el.tag) not in ("item", "product"):
            continue
        f = {_local(c.tag): (c.text or "").strip() for c in el}
        el.clear()
        code = f.get("itemcode")
        name = f.get("itemname") or f.get("manufactureritemdescription")
        price = _dec(f.get("itemprice"))
        if not code or not name or price is None or price <= 0:
            continue
        yield PriceRow(
            code=code,
            name=name,
            price=price,
            unit_price=_dec(f.get("unitofmeasureprice")),
            unit=f.get("unitofmeasure") or None,
            weighted=_bool(f.get("bisweighted") or f.get("isweighted")),
            itemtype=f.get("itemtype") or None,
        )


# ------------------------------ סניפים ------------------------------

class ParsedStore(NamedTuple):
    store_id_ext: str
    name: str | None
    city: str | None
    address: str | None


def parse_stores_file(payload: bytes) -> list[ParsedStore]:
    out: list[ParsedStore] = []
    for _ev, el in ET.iterparse(io.BytesIO(decompress(payload)), events=("end",)):
        if _local(el.tag) != "store":
            continue
        f = {_local(c.tag): (c.text or "").strip() for c in el}
        el.clear()
        sid = f.get("storeid")
        if sid:
            out.append(ParsedStore(sid, f.get("storename") or None, f.get("city") or None, f.get("address") or None))
    return out


# ------------------------------ מבצעים ------------------------------

class PromoRow(NamedTuple):
    code: str
    description: str | None
    price_each: Decimal   # מחיר ליחידה (במבצע "2 ב-10" -> 5)
    club: bool


def iter_promo_rows(payload: bytes, today: date | None = None) -> Iterator[PromoRow]:
    today = today or date.today()
    for _ev, el in ET.iterparse(io.BytesIO(decompress(payload)), events=("end",)):
        if _local(el.tag) != "promotion":
            continue
        f: dict[str, str] = {}
        codes: list[str] = []
        club = False
        for c in el:
            t = _local(c.tag)
            if t in ("promotionitems", "items"):
                for it in c:
                    for cc in it:
                        if _local(cc.tag) == "itemcode" and (cc.text or "").strip():
                            codes.append(cc.text.strip())
            elif t == "clubs":
                for cc in c:
                    if _local(cc.tag) == "clubid" and (cc.text or "").strip() not in ("", "0"):
                        club = True
            else:
                f[t] = (c.text or "").strip()
        el.clear()

        price = _dec(f.get("discountedprice"))
        if price is None or price <= 0 or not codes:
            continue  # מבצעי אחוזים ללא מחיר מפורש - לא מנחשים
        end = f.get("promotionenddate", "")[:10]
        try:
            if end and date.fromisoformat(end) < today:
                continue
        except ValueError:
            pass
        qty = _dec(f.get("minqty")) or Decimal(1)
        each = (price / qty).quantize(Decimal("0.01")) if qty > 1 else price
        if f.get("clubid", "") not in ("", "0"):
            club = True
        desc = f.get("promotiondescription") or None
        for code in codes:
            yield PromoRow(code, desc, each, club)

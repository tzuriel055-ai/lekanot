"""
פרסר גנרי לקבצי ה-XML של חוק שקיפות המחירים.

התקנות מגדירות מבנה קבוע (מסמך "פרסום נתוני מחירים לצרכן"): קובץ חנויות,
קובץ פריטים/מחירים וקובץ מבצעים, כל אחד ב-XML, לרוב דחוס ב-gzip.
השמות המדויקים של התגיות (tags) משתנים מעט בין רשת לרשת (יש כמה "דיאלקטים"
נפוצים) — לכן הפונקציות כאן מחפשות כמה שמות אפשריים לכל שדה במקום להניח
תג אחד קשיח, כדי שיעבדו על כמה שיותר רשתות בלי שינוי.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET


def ungzip_if_needed(payload: bytes) -> bytes:
    if payload[:2] == b"\x1f\x8b":
        return gzip.decompress(payload)
    return payload


def _first_text(item: ET.Element, *names: str) -> str | None:
    for name in names:
        el = item.find(name)
        if el is not None and el.text is not None and el.text.strip() != "":
            return el.text.strip()
    return None


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return None


def _to_bool(value: str | None) -> bool:
    return value is not None and value.strip() in ("1", "true", "True")


@dataclass
class ParsedStore:
    store_id_ext: str
    name: str | None
    city: str | None
    address: str | None


@dataclass
class ParsedPriceItem:
    chain_item_code: str
    item_name: str
    gtin: str | None
    price: Decimal
    unit_of_measure_price: Decimal | None
    unit_of_measure: str | None
    is_weighted: bool
    manufacturer: str | None
    store_id_ext: str | None  # לפעמים הקובץ הוא per-store, ואז זה קבוע מבחוץ


@dataclass
class ParsedPromoItem:
    chain_item_code: str
    description: str | None
    promo_price: Decimal | None
    club_required: bool


def parse_stores_file(payload: bytes) -> list[ParsedStore]:
    root = ET.fromstring(ungzip_if_needed(payload))
    out: list[ParsedStore] = []
    for store in root.iter():
        if store.tag not in ("Store", "STORE"):
            continue
        store_id = _first_text(store, "StoreId", "STOREID", "StoreID")
        if not store_id:
            continue
        out.append(
            ParsedStore(
                store_id_ext=store_id,
                name=_first_text(store, "StoreName", "STORENAME"),
                city=_first_text(store, "City", "CITY"),
                address=_first_text(store, "Address", "ADDRESS"),
            )
        )
    return out


def parse_price_file(payload: bytes, default_store_id: str | None = None) -> list[ParsedPriceItem]:
    root = ET.fromstring(ungzip_if_needed(payload))
    out: list[ParsedPriceItem] = []
    for item in root.iter():
        if item.tag not in ("Item", "ITEM", "Product"):
            continue
        code = _first_text(item, "ItemCode", "ITEMCODE")
        name = _first_text(item, "ItemName", "ITEMNAME")
        price = _to_decimal(_first_text(item, "ItemPrice", "ITEMPRICE"))
        if not code or not name or price is None:
            continue  # רשומה חסרה/פגומה — מדלגים ולא מפילים את כל הריצה

        gtin_raw = _first_text(item, "ItemCode") if _to_bool(_first_text(item, "ItemType")) else None
        is_weighted = _to_bool(_first_text(item, "bIsWeighted", "BIsWeighted", "ItemIsWeighted"))

        out.append(
            ParsedPriceItem(
                chain_item_code=code,
                item_name=name,
                gtin=code if (code and code.isdigit() and len(code) in (12, 13, 14) and not is_weighted) else None,
                price=price,
                unit_of_measure_price=_to_decimal(
                    _first_text(item, "UnitOfMeasurePrice", "UNITOFMEASUREPRICE")
                ),
                unit_of_measure=_first_text(item, "UnitOfMeasure", "UNITOFMEASURE"),
                is_weighted=is_weighted,
                manufacturer=_first_text(item, "ManufacturerName", "MANUFACTURERNAME"),
                store_id_ext=_first_text(item, "StoreId", "STOREID") or default_store_id,
            )
        )
    return out


def parse_promo_file(payload: bytes) -> list[ParsedPromoItem]:
    root = ET.fromstring(ungzip_if_needed(payload))
    out: list[ParsedPromoItem] = []
    for promo in root.iter():
        if promo.tag not in ("Promotion", "PROMOTION", "Sale"):
            continue
        for item in promo.iter():
            if item.tag not in ("Item", "ITEM", "PromotionItem"):
                continue
            code = _first_text(item, "ItemCode", "ITEMCODE")
            if not code:
                continue
            out.append(
                ParsedPromoItem(
                    chain_item_code=code,
                    description=_first_text(promo, "PromotionDescription", "PROMOTIONDESCRIPTION"),
                    promo_price=_to_decimal(
                        _first_text(promo, "DiscountedPrice", "DISCOUNTEDPRICE")
                    ),
                    club_required=_to_bool(
                        _first_text(promo, "ClubOnly", "IsClubMemberPrice")
                    ),
                )
            )
    return out

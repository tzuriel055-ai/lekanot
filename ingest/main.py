"""
הרצה: python -m ingest.main
(או שזה מה ש-GitHub Actions מריץ אוטומטית לפי .github/workflows/ingest.yml)

עובר על כל הרשתות המוגדרות ב-config.py, מושך את הקבצים העדכניים ביותר שלהן,
מפרק אותם, וכותב הכל ל-Supabase: חנויות, מוצרים (עם matching לפי ברקוד),
מחירים ומבצעים.

עיצוב מכוון: כל רשת רצה בבלוק try/except נפרד — רשת אחת שנופלת (שינוי
פורטל, תקלה זמנית) לא מפילה את כל הריצה של שאר הרשתות.
"""

from __future__ import annotations

import logging
import os
import sys
from decimal import Decimal

from . import db
from .config import CHAINS, ChainConfig
from .parser import parse_price_file, parse_promo_file, parse_stores_file
from .sources.carrefour import CarrefourAdapter
from .sources.cerberus import CerberusAdapter
from .sources.shufersal import ShufersalAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

# מגבלות לריצת ניסיון: בלי זה הריצה הראשונה תנסה למשוך מאות אלפי מוצרים.
# מעלים אותן בהמשך דרך env ב-workflow.
MAX_PRICE_FILES = int(os.environ.get("MAX_PRICE_FILES_PER_CHAIN", "2"))
MAX_ITEMS = int(os.environ.get("MAX_ITEMS_PER_FILE", "300"))


def build_adapter(chain: ChainConfig):
    if chain.portal_type == "cerberus":
        return CerberusAdapter(username=chain.portal_username)
    if chain.portal_type == "shufersal_direct":
        return ShufersalAdapter()
    if chain.portal_type == "carrefour_direct":
        return CarrefourAdapter()
    raise ValueError(f"unknown portal_type: {chain.portal_type}")


def run_chain(chain: ChainConfig) -> None:
    log.info("=== %s (%s) ===", chain.display_name, chain.id)
    db.upsert(
        "chains",
        [{"id": chain.id, "display_name": chain.display_name, "portal_type": chain.portal_type}],
        on_conflict="id",
    )

    adapter = build_adapter(chain)
    files = list(adapter.list_files())
    log.info("found %d files", len(files))

    # לוקחים רק את הקובץ העדכני ביותר מכל סוג/סניף (הרשימה כבר ממוינת time desc)
    latest: dict[tuple[str, str | None], object] = {}
    for ref in files:
        key = (ref.kind, ref.store_id_ext)
        if key not in latest:
            latest[key] = ref

    store_uuid_by_ext: dict[str, str] = {}

    # 1) חנויות
    for ref in [r for (kind, _), r in latest.items() if kind == "stores"]:
        payload = adapter.download(ref)
        stores = parse_stores_file(payload)
        rows = [
            {
                "chain_id": chain.id,
                "store_id_ext": s.store_id_ext,
                "name": s.name,
                "city": s.city,
                "address": s.address,
            }
            for s in stores
        ]
        saved = db.upsert("stores", rows, on_conflict="chain_id,store_id_ext")
        for row in saved:
            store_uuid_by_ext[row["store_id_ext"]] = row["id"]
        log.info("stores: upserted %d", len(saved))

    # 2) מחירים (ומוצרים כתוצר לוואי - upsert לפי gtin או alias)
    price_files_done = 0
    for (kind, store_ext), ref in latest.items():
        if kind != "prices":
            continue
        if price_files_done >= MAX_PRICE_FILES:
            break
        price_files_done += 1
        payload = adapter.download(ref)
        items = parse_price_file(payload, default_store_id=store_ext)[:MAX_ITEMS]
        log.info("prices file %s: %d items", ref.label, len(items))

        store_uuid = store_uuid_by_ext.get(items[0].store_id_ext) if items else None
        if store_uuid is None and items and items[0].store_id_ext:
            # החנות לא הופיעה בקובץ החנויות (או שעוד לא רץ) - יוצרים רשומת מינימום
            saved = db.upsert(
                "stores",
                [{"chain_id": chain.id, "store_id_ext": items[0].store_id_ext}],
                on_conflict="chain_id,store_id_ext",
            )
            if saved:
                store_uuid = saved[0]["id"]
                store_uuid_by_ext[items[0].store_id_ext] = store_uuid

        if store_uuid is None:
            log.warning("skipping price file %s - no store id resolved", ref.label)
            continue

        price_rows = []
        for it in items:
            product_id = _resolve_product(chain.id, it.chain_item_code, it.gtin, it.item_name, it.is_weighted)
            price_rows.append(
                {
                    "product_id": product_id,
                    "store_id": store_uuid,
                    "price": str(it.price),
                    "unit_price": str(it.unit_of_measure_price) if it.unit_of_measure_price else None,
                    "unit_of_measure": it.unit_of_measure,
                }
            )
        db.upsert("prices", price_rows, on_conflict="product_id,store_id")
        log.info("prices: upserted %d rows for store %s", len(price_rows), store_ext)


_product_cache: dict[str, str] = {}  # gtin/alias-key -> product uuid, per-run cache


def _resolve_product(chain_id: str, chain_item_code: str, gtin: str | None, name: str, is_weighted: bool) -> str:
    cache_key = f"gtin:{gtin}" if gtin else f"alias:{chain_id}:{chain_item_code}"
    if cache_key in _product_cache:
        return _product_cache[cache_key]

    if gtin:
        saved = db.upsert(
            "products",
            [{"gtin": gtin, "canonical_name": name, "is_weighted": is_weighted}],
            on_conflict="gtin",
        )
        product_id = saved[0]["id"]
    else:
        # אין ברקוד (מוצר שקילה) - יוצרים/מוצאים דרך alias פר-רשת
        existing = db.select_one("product_aliases", {"chain_id": chain_id, "chain_item_code": chain_item_code})
        if existing:
            product_id = existing["product_id"]
        else:
            saved = db.upsert(
                "products",
                [{"canonical_name": name, "is_weighted": True}],
                on_conflict="gtin",  # gtin is null so this always inserts a new row
            )
            product_id = saved[0]["id"]
            db.upsert(
                "product_aliases",
                [{"product_id": product_id, "chain_id": chain_id, "chain_item_code": chain_item_code, "raw_name": name}],
                on_conflict="chain_id,chain_item_code",
            )

    _product_cache[cache_key] = product_id
    return product_id


def main() -> None:
    failures = []
    for chain in CHAINS:
        if not chain.portal_username and chain.portal_type == "cerberus":
            log.warning("skipping %s - no portal_username configured", chain.id)
            continue
        try:
            run_chain(chain)
        except Exception as exc:  # רשת אחת נופלת, השאר ממשיכות
            log.exception("chain %s failed: %s", chain.id, exc)
            failures.append(chain.id)

    if failures:
        log.error("finished with failures: %s", failures)
        sys.exit(1)
    log.info("all chains completed successfully")


if __name__ == "__main__":
    main()

"""
משיכה יומית של *כל* הקטלוג מכל הרשתות, בלי עלות.

  python -m ingest.main

העקרונות (כולם נובעים מהמגבלה שאנחנו על שכבות חינמיות, לתמיד):

1. רק קובצי PriceFull / PromoFull (הקטלוג המלא). קובצי Price/Promo הם עדכוני
   שינויים בלבד - הם גרמו לנתונים החלקיים עד עכשיו.
2. הנתונים נשמרים *ברמת רשת*, לא ברמת סניף: לכל (מוצר, רשת) שורה אחת עם המחיר
   הזול ביותר בין הסניפים, המחיר הגבוה ביותר, ובכמה סניפים המוצר נמצא.
   הקטלוג המלא ברמת סניף היה מגיע לעשרות מיליוני שורות וחורג מ-500MB החינמיים
   של Supabase; ברמת רשת זה מאות אלפי שורות בלבד. וזה גם מה שההשוואה צריכה.
3. כתיבה בבאצ'ים, ורק של מה ששונה מאז הריצה הקודמת.
4. "אין במלאי" = המוצר לא הופיע באף קובץ PriceFull של הרשת בעדכון האחרון.
   מסמנים את זה *רק* אם כל הקבצים של הרשת נמשכו בהצלחה - אחרת לא נוגעים,
   כדי לא להציג "אין במלאי" שלא נובע באמת מהקבצים.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from . import db
from .config import CHAINS, ChainConfig
from .parser import iter_price_rows, iter_promo_rows, norm_gtin, parse_stores_file, to_gtin
from .sources.base import NoPriceFilesYet, PortalAccessError, describe_listing, select_latest
from .sources.carrefour import CarrefourAdapter
from .sources.cerberus import CerberusAdapter
from .sources.shufersal import ShufersalAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

WORKERS = int(os.environ.get("INGEST_WORKERS", "4"))
PRUNE_DAYS = 30           # מוצר שלא נראה 30 יום נמחק מהטבלה (שומר על הגודל חסום)
SUSPICIOUS_DROP = 0.5     # אם פחות מ-50% מהמוצרים הקיימים הופיעו - לא מסמנים "אין במלאי"
_Q = Decimal("0.01")


def build_adapter(chain: ChainConfig, username: str | None = None):
    if chain.portal_type == "cerberus":
        return CerberusAdapter(username=username or chain.portal_username)
    if chain.portal_type == "shufersal_direct":
        return ShufersalAdapter()
    if chain.portal_type == "carrefour_direct":
        return CarrefourAdapter()
    raise ValueError(f"unknown portal_type: {chain.portal_type}")


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()[:200]


def _q(x) -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(_Q)


# ------------------------------ אגרגציה ------------------------------

class ItemAgg:
    __slots__ = ("gtin", "code", "name", "weighted", "pmin", "pmax", "umin", "unit", "count")

    def __init__(self, gtin, code, name, weighted, price, unit_price, unit):
        self.gtin, self.code, self.name, self.weighted = gtin, code, name, weighted
        self.pmin = self.pmax = price
        self.umin, self.unit, self.count = unit_price, unit, 1

    def merge(self, price, unit_price):
        self.count += 1
        if price < self.pmin:
            self.pmin = price
        if price > self.pmax:
            self.pmax = price
        if unit_price is not None and (self.umin is None or unit_price < self.umin):
            self.umin = unit_price


def add_file(agg: dict[str, ItemAgg], rows) -> None:
    """מוסיף קובץ של סניף אחד לאגרגציה של הרשת (כל מוצר נספר פעם אחת לסניף)."""
    seen: set[str] = set()
    for r in rows:
        gtin = to_gtin(r.code, r.itemtype, r.weighted)
        key = gtin or "c:" + r.code
        if key in seen:
            continue
        seen.add(key)
        a = agg.get(key)
        if a is None:
            agg[key] = ItemAgg(gtin, r.code, _clean(r.name), r.weighted, r.price, r.unit_price, r.unit)
        else:
            a.merge(r.price, r.unit_price)


def process_files(adapter, refs, parse, consume, deadline):
    """מוריד ומפרסר קבצים במקביל (בבאצ'ים קטנים - זיכרון חסום). מחזיר (הצליחו, נכשלו, נעצר)."""
    ok = failed = 0
    stopped = False

    def fetch(ref):
        try:
            return ref, list(parse(adapter.download(ref))), None
        except Exception as exc:  # noqa: BLE001 - כל כשל בקובץ בודד נספר, לא מפיל את הרשת
            return ref, None, exc

    step = WORKERS * 2
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i in range(0, len(refs), step):
            if time.time() > deadline:
                stopped = True
                break
            for ref, rows, err in ex.map(fetch, refs[i:i + step]):
                if err is not None:
                    failed += 1
                    log.warning("file failed %s: %s", ref.label, err)
                else:
                    consume(rows)
                    ok += 1
    return ok, failed, stopped


# ------------------------------ אינדקסים ------------------------------

def load_gtin_index() -> dict[str, str]:
    rows = db.select_all("products", "id,gtin", {"gtin": "not.is.null"}, order="id")
    idx: dict[str, str] = {}
    for r in rows:
        idx.setdefault(norm_gtin(r["gtin"]) or r["gtin"], r["id"])
    return idx


def load_alias_index(chain_id: str) -> dict[str, str]:
    rows = db.select_all("product_aliases", "chain_item_code,product_id", {"chain_id": f"eq.{chain_id}"}, order="chain_item_code")
    return {r["chain_item_code"]: r["product_id"] for r in rows}


def map_code(code: str, gtin_index, alias_index) -> str | None:
    g = norm_gtin(code)
    if g and g in gtin_index:
        return gtin_index[g]
    return alias_index.get(code)


# ------------------------------ כתיבה ל-DB ------------------------------

def ensure_chain(chain: ChainConfig) -> str:
    db.upsert("chains", [{"id": chain.id, "display_name": chain.display_name, "portal_type": chain.portal_type}], "id")
    rows = db.upsert("stores", [{"chain_id": chain.id, "store_id_ext": "ALL", "name": "כל הסניפים"}],
                     "chain_id,store_id_ext", returning=True)
    return rows[0]["id"]


def sync_real_stores(adapter, latest, chain: ChainConfig) -> None:
    """רשימת הסניפים האמיתיים (שם/עיר/כתובת) - לשימוש עתידי במיקום. best-effort."""
    rows: dict[str, dict] = {}
    for (kind, _), ref in latest.items():
        if kind != "stores":
            continue
        try:
            for s in parse_stores_file(adapter.download(ref)):
                rows.setdefault(s.store_id_ext, {"chain_id": chain.id, "store_id_ext": s.store_id_ext,
                                                 "name": s.name, "city": s.city, "address": s.address})
        except Exception as exc:  # noqa: BLE001
            log.warning("stores file failed %s: %s", ref.label, exc)
    rows.pop("ALL", None)
    if rows:
        db.upsert("stores", list(rows.values()), "chain_id,store_id_ext")


def resolve_products(chain: ChainConfig, agg, gtin_index, alias_index) -> tuple[dict[str, str], int]:
    """לכל פריט באגרגציה - מוצא product_id קיים או יוצר חדש (בבאצ'ים, id נוצר אצלנו)."""
    pid_by_key: dict[str, str] = {}
    new_products: list[dict] = []
    new_aliases: list[dict] = []
    for key, a in agg.items():
        if a.gtin:
            pid = gtin_index.get(a.gtin)
            if pid is None:
                pid = str(uuid.uuid4())
                gtin_index[a.gtin] = pid
                new_products.append({"id": pid, "gtin": a.gtin, "canonical_name": a.name, "is_weighted": a.weighted})
        else:
            pid = alias_index.get(a.code)
            if pid is None:
                pid = str(uuid.uuid4())
                alias_index[a.code] = pid
                new_products.append({"id": pid, "gtin": None, "canonical_name": a.name, "is_weighted": a.weighted})
                new_aliases.append({"product_id": pid, "chain_id": chain.id, "chain_item_code": a.code, "raw_name": a.name})
        pid_by_key[key] = pid
    if new_products:
        inserted = db.upsert("products", new_products, "gtin", ignore_duplicates=True, returning=True)
        inserted_ids = {r["id"] for r in inserted}
        # הגנה: מוצר שכבר היה קיים ב-DB אבל חסר באינדקס שלנו נדחה בשקט (ignore-duplicates),
        # וה-id שיצרנו לא קיים. מזהים אותם ומתקנים ל-id האמיתי, אחרת נכתוב מחירים עם מזהה שגוי.
        lost = {p["id"]: p["gtin"] for p in new_products if p["gtin"] and p["id"] not in inserted_ids}
        if lost:
            gtins = list(lost.values())
            real: dict[str, str] = {}
            for i in range(0, len(gtins), 100):
                for r in db.select_all("products", "id,gtin", {"gtin": f"in.({','.join(gtins[i:i + 100])})"}, order="id"):
                    real[r["gtin"]] = r["id"]
            remap = {old_id: real[g] for old_id, g in lost.items() if g in real}
            for g, rid in real.items():
                gtin_index[g] = rid
            for k, v in pid_by_key.items():
                if v in remap:
                    pid_by_key[k] = remap[v]
            log.warning("%s: %d products already existed but were missing from the index (healed)", chain.id, len(lost))
    if new_aliases:
        db.upsert("product_aliases", new_aliases, "chain_id,chain_item_code", ignore_duplicates=True)
    return pid_by_key, len(new_products)


def _price_row(pid, store_id, pmin, pmax, umin, unit, carrying, in_stock, now_iso) -> dict:
    return {"product_id": pid, "store_id": store_id, "price": str(pmin), "price_max": str(pmax),
            "unit_price": None if umin is None else str(umin), "unit_of_measure": unit,
            "in_stock": in_stock, "stores_carrying": carrying, "updated_at": now_iso}


def sync_prices(agg, pid_by_key, pseudo_id: str, complete: bool, now_iso: str) -> dict:
    existing = {r["product_id"]: r for r in db.select_all(
        "prices", "product_id,price,price_max,unit_price,unit_of_measure,stores_carrying,in_stock",
        {"store_id": f"eq.{pseudo_id}"}, order="product_id")}

    changed: list[dict] = []
    seen: set[str] = set()
    for key, a in agg.items():
        pid = pid_by_key[key]
        seen.add(pid)
        new = (_q(a.pmin), _q(a.pmax), _q(a.umin), a.count)
        old = existing.get(pid)
        if old and old.get("in_stock") and (
            _q(old["price"]), _q(old.get("price_max") if old.get("price_max") is not None else old["price"]),
            _q(old.get("unit_price")), old.get("stores_carrying"),
        ) == new:
            continue  # לא השתנה - לא נוגעים (חוסך כתיבות ו-bloat)
        changed.append(_price_row(pid, pseudo_id, new[0], new[1], new[2], a.unit, a.count, True, now_iso))

    absent: list[dict] = []
    note = None
    if complete:
        live_before = sum(1 for r in existing.values() if r.get("in_stock"))
        if live_before and len(seen & {p for p, r in existing.items() if r.get("in_stock")}) < SUSPICIOUS_DROP * live_before:
            note = f"suspicious drop ({len(seen)} seen vs {live_before} live) - not marking absences"
            log.warning(note)
        else:
            for pid, old in existing.items():
                if pid in seen or not old.get("in_stock"):
                    continue
                pm = old.get("price_max") if old.get("price_max") is not None else old["price"]
                absent.append(_price_row(pid, pseudo_id, _q(old["price"]), _q(pm), _q(old.get("unit_price")),
                                         old.get("unit_of_measure"), 0, False, now_iso))

    db.upsert("prices", changed + absent, "product_id,store_id")

    if complete and note is None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=PRUNE_DAYS)).isoformat()
        db.delete("prices", {"store_id": f"eq.{pseudo_id}", "in_stock": "eq.false", "updated_at": f"lt.{cutoff}"})

    return {"changed": len(changed), "absent": len(absent), "unchanged": len(agg) - len(changed), "note": note}


def sync_promos(chain_id, adapter, latest, pseudo_id, gtin_index, alias_index, deadline, now_iso) -> int:
    refs = [r for (k, _), r in latest.items() if k == "promos_full"]
    if not refs:
        log.info("no PromoFull files for this chain")
        return 0
    best: dict[str, tuple] = {}

    def consume(rows):
        for p in rows:
            cur = best.get(p.code)
            if cur is None or p.price_each < cur[0]:
                best[p.code] = (p.price_each, p.description, p.club)

    stats: dict = {}
    ok, failed, stopped = process_files(adapter, refs, lambda b: iter_promo_rows(b, stats=stats), consume, deadline)
    rows: dict[str, dict] = {}
    for code, (price, desc, club) in best.items():
        pid = map_code(code, gtin_index, alias_index)
        if not pid:
            continue
        cur = rows.get(pid)
        if cur is None or price < Decimal(cur["promo_price"]):
            rows[pid] = {"product_id": pid, "store_id": pseudo_id, "description": desc,
                         "promo_price": str(price), "club_required": club, "updated_at": now_iso}
    db.upsert("promos", list(rows.values()), "product_id,store_id")
    # אבחון: אם רשת מניבה מעט/אפס מבצעים, השורות האלה אומרות למה (ואילו תגיות יש בקובץ)
    log.info("%s promos: files=%d promotions=%d usable=%d percent_only=%d no_price=%d no_items=%d expired=%d "
             "distinct_products=%d matched_to_catalog=%d", chain_id, ok, stats.get("promotions", 0), stats.get("ok", 0),
             stats.get("percent_only", 0), stats.get("no_price", 0), stats.get("no_items", 0), stats.get("expired", 0),
             len(best), len(rows))
    if not rows:
        top = sorted(stats.get("tags", {}).items(), key=lambda kv: -kv[1])[:14]
        log.info("%s promos: no usable rows. most common tags in the promo files: %s", chain_id, top)

    if ok > 0 and failed == 0 and not stopped:  # תמונה מלאה בלבד - רק אז מוחקים מבצעים שהסתיימו
        existing = db.select_all("promos", "product_id", {"store_id": f"eq.{pseudo_id}"}, order="product_id")
        stale = [r["product_id"] for r in existing if r["product_id"] not in rows]
        for i in range(0, len(stale), 80):
            db.delete("promos", {"store_id": f"eq.{pseudo_id}", "product_id": f"in.({','.join(stale[i:i + 80])})"})
    return len(rows)


def write_status(chain, *, stores_total, products_total, complete, note, now_iso) -> None:
    row = {"chain_id": chain.id, "last_attempt_at": now_iso, "stores_total": stores_total,
           "products_total": products_total, "complete": complete, "note": note}
    if complete:
        row["last_complete_at"] = now_iso
    db.upsert("ingest_status", [row], "chain_id")


# ------------------------------ רשת אחת ------------------------------

def run_chain(chain: ChainConfig, gtin_index: dict[str, str], deadline: float) -> dict:
    t0 = time.time()
    usernames = [chain.portal_username, *chain.alt_usernames] if chain.portal_type == "cerberus" else [None]
    adapter, refs, last_err = None, [], None
    for uname in usernames:
        adapter = build_adapter(chain, uname) if uname else build_adapter(chain)
        try:
            refs = list(adapter.list_files())
        except PortalAccessError as exc:
            last_err = exc
            continue  # שם משתמש שגוי - מנסים את הבא
        if uname and uname != chain.portal_username:
            log.warning("%s: logged in with alternate username '%s' - update config.py", chain.id, uname)
        last_err = None
        break
    if last_err is not None:
        raise last_err
    diag = describe_listing(refs, getattr(adapter, "unparsed", None), getattr(adapter, "unparsed_count", 0))
    if not refs:
        raise PortalAccessError(f"no recognised files in listing ({diag})")
    latest = select_latest(refs)

    price_refs = [r for (k, _), r in latest.items() if k == "prices_full"]
    complete = bool(getattr(adapter, "listing_complete", True))
    notes: list[str] = []
    if not complete:
        notes.append("file listing incomplete")
    if not price_refs:
        price_refs = [r for (k, _), r in latest.items() if k == "prices_delta"]
        complete = False
        notes.append("no PriceFull files - used delta files, absences not marked")
        if not price_refs:
            raise NoPriceFilesYet(f"no price files in listing ({diag})")
    log.info("%s: %d files listed, %d price files (stores)", chain.id, len(refs), len(price_refs))

    pseudo_id = ensure_chain(chain)
    sync_real_stores(adapter, latest, chain)

    agg: dict[str, ItemAgg] = {}
    ok, failed, stopped = process_files(adapter, price_refs, iter_price_rows, lambda rows: add_file(agg, rows), deadline)
    if ok == 0:
        raise PortalAccessError(f"all {failed} price files failed")
    if failed or stopped:
        complete = False
        notes.append(f"{failed} files failed, stopped={stopped} - absences not marked")
    log.info("%s: parsed %d/%d files -> %d distinct products", chain.id, ok, len(price_refs), len(agg))

    now_iso = datetime.now(timezone.utc).isoformat()
    alias_index = load_alias_index(chain.id)
    pid_by_key, new_products = resolve_products(chain, agg, gtin_index, alias_index)
    stats = sync_prices(agg, pid_by_key, pseudo_id, complete, now_iso)
    if stats["note"]:
        complete = False
        notes.append(stats["note"])
    promos = sync_promos(chain.id, adapter, latest, pseudo_id, gtin_index, alias_index, deadline, now_iso)

    write_status(chain, stores_total=len(price_refs), products_total=len(agg), complete=complete,
                 note="; ".join(notes) or None, now_iso=now_iso)
    res = {"chain": chain.id, "stores": len(price_refs), "products": len(agg), "new_products": new_products,
           "price_rows_written": stats["changed"], "marked_unavailable": stats["absent"],
           "promos": promos, "complete": complete, "seconds": round(time.time() - t0)}
    log.info("%s: DONE %s", chain.id, res)
    return res


def main() -> None:
    start = time.time()
    deadline = start + float(os.environ.get("INGEST_DEADLINE_MIN", "320")) * 60
    gtin_index = load_gtin_index()
    log.info("loaded %d known barcodes", len(gtin_index))

    summary: list[str] = []
    hard_failures: list[str] = []
    for chain in CHAINS:
        if not chain.active:
            continue
        if time.time() > deadline:
            summary.append(f"{chain.id}: SKIPPED (time budget)")
            continue
        try:
            r = run_chain(chain, gtin_index, deadline)
            summary.append(f"{chain.id}: OK products={r['products']} stores={r['stores']} "
                           f"complete={r['complete']} ({r['seconds']}s)")
        except NoPriceFilesYet as exc:
            # הרשת עונה ויש בה קבצים, אבל קובצי המחירים של היום עוד לא פורסמו - לא כשל.
            # הריצה הבאה (או המשך היום) תתפוס אותם; המחירים הקיימים נשארים כמו שהם.
            log.warning("%s: nothing to ingest right now - %s", chain.id, exc)
            summary.append(f"{chain.id}: NOT PUBLISHED YET ({exc})")
        except PortalAccessError as exc:
            log.warning("%s: skipped - %s", chain.id, exc)
            summary.append(f"{chain.id}: SKIPPED ({exc})")
            if chain.verified:
                hard_failures.append(chain.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s failed: %s", chain.id, exc)
            summary.append(f"{chain.id}: FAILED ({exc})")
            if chain.verified:
                hard_failures.append(chain.id)

    log.info("=========== SUMMARY (%.0f min) ===========", (time.time() - start) / 60)
    for line in summary:
        log.info(line)
    if hard_failures:
        log.error("verified chains failed: %s", hard_failures)
        sys.exit(1)


if __name__ == "__main__":
    main()

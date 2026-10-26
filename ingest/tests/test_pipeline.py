"""
בדיקות מקצה לקצה לצינור המשיכה, מול מסד נתונים מדומה בזיכרון ואדפטר מדומה.
הרצה:  SUPABASE_URL=https://x.supabase.co SUPABASE_SERVICE_KEY=x python -m unittest ingest.tests.test_pipeline -v
"""

import gzip
import os
import time
import unittest
import uuid

os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "sb_secret_test")

from ingest import db, main  # noqa: E402
from ingest.config import ChainConfig  # noqa: E402
from ingest.sources.base import PortalAccessError, build_ref  # noqa: E402


class FakeDB:
    """מדמה את PostgREST: מפתחות אחידים בבאצ', ואין שני שורות עם אותו מפתח קונפליקט באותה קריאה."""

    def __init__(self):
        self.t: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str, int]] = []

    def rows(self, table):
        return self.t.setdefault(table, [])

    def upsert(self, table, rows, on_conflict, *, ignore_duplicates=False, returning=False, batch=500):
        out = []
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            self.calls.append(("upsert", table, len(chunk)))
            assert len({tuple(sorted(r)) for r in chunk}) <= 1, f"non-uniform keys in {table} batch"
            cols = on_conflict.split(",")
            seen_keys = set()
            for r in chunk:
                key = tuple(r.get(c) for c in cols)
                if None not in key:
                    assert key not in seen_keys or ignore_duplicates, f"ON CONFLICT cannot affect row twice: {table} {key}"
                    seen_keys.add(key)
                existing = None if None in key else next((x for x in self.rows(table) if tuple(x.get(c) for c in cols) == key), None)
                if existing is not None:
                    if not ignore_duplicates:
                        existing.update(r)
                    out.append(existing)
                else:
                    new = dict(r)
                    if table in ("stores", "products", "product_aliases", "prices", "promos") and "id" not in new:
                        new["id"] = str(uuid.uuid4())
                    self.rows(table).append(new)
                    out.append(new)
        return out if returning else []

    def _match(self, row, filters):
        for col, cond in filters.items():
            v = row.get(col)
            if cond.startswith("eq."):
                if str(v).lower() != cond[3:].lower():
                    return False
            elif cond == "not.is.null":
                if v is None:
                    return False
            elif cond.startswith("in.("):
                if str(v) not in cond[4:-1].split(","):
                    return False
            elif cond.startswith("lt."):
                if not (v is not None and str(v) < cond[3:]):
                    return False
            else:
                raise AssertionError(f"unsupported filter {cond}")
        return True

    def select_all(self, table, select, filters=None, order="id", page=1000):
        cols = select.split(",")
        return [{c: r.get(c) for c in cols} for r in self.rows(table) if self._match(r, filters or {})]

    def delete(self, table, filters):
        self.calls.append(("delete", table, 0))
        self.t[table] = [r for r in self.rows(table) if not self._match(r, filters)]


def price_xml(items):
    out = ['<?xml version="1.0" encoding="utf-8"?><Root><Items>']
    for code, itemtype, name, price, weighted in items:
        out.append(f"<Item><ItemCode>{code}</ItemCode><ItemType>{itemtype}</ItemType><ItemName>{name}</ItemName>"
                   f"<ItemPrice>{price}</ItemPrice><UnitOfMeasurePrice>{price}</UnitOfMeasurePrice>"
                   f"<bIsWeighted>{1 if weighted else 0}</bIsWeighted></Item>")
    out.append("</Items></Root>")
    return gzip.compress("".join(out).encode())


def promo_xml(promos):
    out = ["<Root><Promotions>"]
    for desc, price, qty, end, codes in promos:
        items = "".join(f"<Item><ItemCode>{c}</ItemCode></Item>" for c in codes)
        out.append(f"<Promotion><PromotionDescription>{desc}</PromotionDescription><DiscountedPrice>{price}</DiscountedPrice>"
                   f"<MinQty>{qty}</MinQty><PromotionEndDate>{end}</PromotionEndDate><PromotionItems>{items}</PromotionItems></Promotion>")
    out.append("</Promotions></Root>")
    return gzip.compress("".join(out).encode())


def stores_xml(ids):
    body = "".join(f"<Store><StoreId>{i}</StoreId><StoreName>סניף {i}</StoreName><City>עיר</City><Address>רחוב {i}</Address></Store>" for i in ids)
    return gzip.compress(f"<Root><Stores>{body}</Stores></Root>".encode())


class FakeAdapter:
    def __init__(self, files, listing_complete=True):
        self.files = files
        self.listing_complete = listing_complete

    def list_files(self):
        return [build_ref(n, "u") for n in self.files]

    def download(self, ref):
        v = self.files[ref.label]
        if isinstance(v, Exception):
            raise v
        return v


_ORIG_LOAD = main.load_gtin_index
_ORIG_CHAINS = list(main.CHAINS)
CHAIN = ChainConfig("tc", "רשת בדיקה", "cerberus", "x")
A, B, C, E = "7290000000001", "7290000000002", "7290000000003", "7290000000005"
P = "7290000000000"


def day1_files():
    return {
        f"PriceFull{P}-001-001-20260929-0400.gz": price_xml([(A, 1, "OLD-SHOULD-BE-IGNORED", 99, False)]),
        f"PriceFull{P}-001-001-20260930-0400.gz": price_xml([(A, 1, "אלפא", "10.00", False), (B, 1, "בטא", "5.00", False), ("123", 0, "בננות", "20.00", True)]),
        f"PriceFull{P}-001-002-20260930-0400.gz": price_xml([(A, 1, "אלפא", "9.00", False), (C, 1, "גמא", "7.00", False)]),
        f"PriceFull{P}-001-003-20260930-0400.gz": price_xml([(A, 1, "אלפא", "11.00", False), (B, 1, "בטא", "6.00", False), (E, 1, "אפסילון", "3.00", False)]),
        f"Price{P}-001-001-20260930-1000.gz": price_xml([("7290000000099", 1, "DELTA-SHOULD-BE-IGNORED", "1.00", False)]),
        f"PromoFull{P}-001-001-20260930-0400.gz": promo_xml([("מבצע", "8.00", 1, "2099-01-01", [A]), ("2 ב-7", "7.00", 2, "2099-01-01", [B]), ("פג", "1.00", 1, "2020-01-01", [C])]),
        f"StoresFull{P}-000-20260930-0300.gz": stores_xml(["001", "002", "003"]),
    }


class PipelineTests(unittest.TestCase):
    def setUp(self):
        main.load_gtin_index = _ORIG_LOAD
        main.CHAINS[:] = _ORIG_CHAINS
        self.fdb = FakeDB()
        for fn in ("upsert", "select_all", "delete"):
            setattr(db, fn, getattr(self.fdb, fn))
        self.adapter = FakeAdapter(day1_files())
        main.build_adapter = lambda chain, username=None: self.adapter
        self.deadline = time.time() + 999

    def run_chain(self, gtin_index=None):
        return main.run_chain(CHAIN, gtin_index if gtin_index is not None else main.load_gtin_index(), self.deadline)

    def price_rows(self):
        pseudo = next(s["id"] for s in self.fdb.rows("stores") if s["store_id_ext"] == "ALL")
        by_gtin = {p["id"]: p.get("gtin") or p["canonical_name"] for p in self.fdb.rows("products")}
        return {by_gtin[r["product_id"]]: r for r in self.fdb.rows("prices") if r["store_id"] == pseudo}

    # ---------------------------------------------------------------
    def test_day1_full_catalog_aggregated_at_chain_level(self):
        res = self.run_chain()
        rows = self.price_rows()
        self.assertEqual(set(rows), {A, B, C, E, "בננות"}, "delta + old files must be ignored, full files only")
        self.assertEqual((rows[A]["price"], rows[A]["price_max"], rows[A]["stores_carrying"]), ("9.00", "11.00", 3))
        self.assertEqual((rows[B]["price"], rows[B]["price_max"], rows[B]["stores_carrying"]), ("5.00", "6.00", 2))
        self.assertEqual(rows[C]["stores_carrying"], 1)
        self.assertTrue(all(r["in_stock"] for r in rows.values()))
        self.assertEqual(res["stores"], 3)
        self.assertTrue(res["complete"])
        # מוצר שקילה בלי ברקוד = מוצר + alias, ולא ברקוד
        self.assertEqual(len(self.fdb.rows("product_aliases")), 1)
        # סניפים אמיתיים נשמרו, ובנוסף "סניף" הרשת
        self.assertEqual({s["store_id_ext"] for s in self.fdb.rows("stores")}, {"ALL", "001", "002", "003"})

    def test_promos_per_unit_price_and_expiry(self):
        self.run_chain()
        by_pid = {p["id"]: p["gtin"] for p in self.fdb.rows("products")}
        promos = {by_pid[r["product_id"]]: r for r in self.fdb.rows("promos")}
        self.assertEqual(set(promos), {A, B}, "expired promo must be skipped")
        self.assertEqual(promos[A]["promo_price"], "8.00")
        self.assertEqual(promos[B]["promo_price"], "3.50", "'2 for 7' must become 3.50 per unit")

    def test_status_row_written(self):
        self.run_chain()
        st = self.fdb.rows("ingest_status")[0]
        self.assertEqual((st["chain_id"], st["stores_total"], st["products_total"], st["complete"]), ("tc", 3, 5, True))
        self.assertIn("last_complete_at", st)

    def test_second_identical_run_writes_nothing(self):
        self.run_chain()
        res = self.run_chain()
        self.assertEqual(res["price_rows_written"], 0)
        self.assertEqual(res["marked_unavailable"], 0)
        self.assertEqual(res["new_products"], 0)

    def test_only_changes_are_written_and_missing_product_marked_unavailable(self):
        self.run_chain()
        f = day1_files()
        f[f"PriceFull{P}-001-001-20260930-0400.gz"] = price_xml([(A, 1, "אלפא", "10.00", False), (B, 1, "בטא", "4.50", False), ("123", 0, "בננות", "20.00", True)])
        f[f"PriceFull{P}-001-002-20260930-0400.gz"] = price_xml([(A, 1, "אלפא", "9.00", False)])  # C נעלם
        self.adapter.files = f
        res = self.run_chain()
        rows = self.price_rows()
        self.assertEqual(rows[B]["price"], "4.50")
        self.assertFalse(rows[C]["in_stock"])
        self.assertEqual(rows[C]["stores_carrying"], 0)
        self.assertTrue(rows[A]["in_stock"] and rows[E]["in_stock"])
        self.assertEqual((res["price_rows_written"], res["marked_unavailable"]), (1, 1), "only B changed, only C vanished")

    def test_failed_file_means_no_false_out_of_stock(self):
        self.run_chain()
        first_complete = self.fdb.rows("ingest_status")[0]["last_complete_at"]
        time.sleep(0.01)
        f = day1_files()
        f[f"PriceFull{P}-001-003-20260930-0400.gz"] = RuntimeError("boom")  # E קיים רק בסניף הזה
        self.adapter.files = f
        res = self.run_chain()
        self.assertFalse(res["complete"])
        self.assertTrue(self.price_rows()[E]["in_stock"], "E must NOT be marked unavailable when a file failed")
        self.assertEqual(res["marked_unavailable"], 0)
        st = self.fdb.rows("ingest_status")[0]
        self.assertFalse(st["complete"])
        self.assertEqual(st["last_complete_at"], first_complete, "a partial run must not claim a completed sync")

    def test_incomplete_listing_means_no_absences(self):
        self.run_chain()
        f = day1_files()
        del f[f"PriceFull{P}-001-002-20260930-0400.gz"]  # C נעלם, אבל הרשימה לא שלמה
        self.adapter = FakeAdapter(f, listing_complete=False)
        res = self.run_chain()
        self.assertEqual(res["marked_unavailable"], 0)
        self.assertFalse(res["complete"])

    def test_suspicious_drop_is_not_trusted(self):
        self.run_chain()
        f = day1_files()
        for k in list(f):
            if k.startswith("PriceFull") and "-20260930-" in k:
                f[k] = price_xml([(A, 1, "אלפא", "10.00", False)])  # רק מוצר אחד מתוך 5
        self.adapter.files = f
        res = self.run_chain()
        self.assertEqual(res["marked_unavailable"], 0)
        self.assertFalse(res["complete"])
        self.assertTrue(all(r["in_stock"] for r in self.price_rows().values()))

    def test_delta_only_chain_never_marks_absences(self):
        f = {k: v for k, v in day1_files().items() if not k.startswith("PriceFull")}
        self.adapter.files = f
        res = self.run_chain()
        self.assertFalse(res["complete"])
        self.assertEqual(res["marked_unavailable"], 0)

    def test_stale_promos_removed_only_on_complete_snapshot(self):
        self.run_chain()
        f = day1_files()
        f[f"PromoFull{P}-001-001-20260930-0400.gz"] = promo_xml([("מבצע", "8.00", 1, "2099-01-01", [A])])  # מבצע B הסתיים
        self.adapter.files = f
        self.run_chain()
        by_pid = {p["id"]: p["gtin"] for p in self.fdb.rows("products")}
        self.assertEqual({by_pid[r["product_id"]] for r in self.fdb.rows("promos")}, {A})

    def test_stale_index_is_self_healing(self):
        self.run_chain()
        before = {p["gtin"]: p["id"] for p in self.fdb.rows("products") if p.get("gtin")}
        self.fdb.t["prices"] = []                    # נמחקו המחירים, אבל המוצרים קיימים ב-DB
        res = self.run_chain(gtin_index={})          # ...והאינדקס בזיכרון ריק/מיושן
        after = {p["gtin"]: p["id"] for p in self.fdb.rows("products") if p.get("gtin")}
        self.assertEqual(before, after, "no duplicate products may be created")
        pids = {p["id"] for p in self.fdb.rows("products")}
        self.assertTrue(all(r["product_id"] in pids for r in self.fdb.rows("prices")), "every price must reference a real product")
        self.assertGreater(res["price_rows_written"], 0)


    # ---------------------- v4: לקחים מהריצה האמיתית הראשונה ----------------------
    def test_prices_not_published_yet_is_not_a_failure_even_for_verified_chain(self):
        """אושר עד בבוקר: יש קבצים ברשימה אבל עוד אין מחירים. זה לא כשל ולא מכשיל את הריצה."""
        only_promos = {k: v for k, v in day1_files().items() if k.startswith(("PromoFull", "StoresFull"))}
        main.build_adapter = lambda chain, username=None: FakeAdapter(only_promos)
        main.load_gtin_index = lambda: {}
        main.CHAINS[:] = [ChainConfig("early", "x", "cerberus", "x", verified=True)]
        main.main()  # לא אמור לזרוק SystemExit
        self.assertEqual(self.fdb.rows("prices"), [], "nothing written, existing data untouched")

    def test_unrecognised_file_names_are_reported_in_the_error(self):
        class Weird(FakeAdapter):
            unparsed = ["PRICES_2026.csv", "something.txt"]
            unparsed_count = 2
        main.build_adapter = lambda chain, username=None: Weird({})
        with self.assertRaises(PortalAccessError) as cm:
            self.run_chain()
        msg = str(cm.exception)
        self.assertIn("unrecognised names=2", msg)
        self.assertIn("PRICES_2026.csv", msg)

    def test_alternate_username_is_tried_when_first_fails(self):
        used = []
        class BadLogin:
            listing_complete = True
            def list_files(self): raise PortalAccessError("wrong username")
        def builder(chain, username=None):
            used.append(username)
            return BadLogin() if username == "Wrong" else self.adapter
        main.build_adapter = builder
        chain = ChainConfig("alt", "x", "cerberus", "Wrong", verified=False, alt_usernames=("right",))
        res = main.run_chain(chain, {}, self.deadline)
        self.assertEqual(used, ["Wrong", "right"])
        self.assertEqual(res["stores"], 3)

    def test_promo_diagnostics_explain_zero_promos(self):
        from ingest.parser import iter_promo_rows
        xml = gzip.compress("""<Root><Promotions>
          <Promotion><DiscountRate>20</DiscountRate><PromotionItems><Item><ItemCode>1</ItemCode></Item></PromotionItems></Promotion>
          <Promotion><DiscountedPrice>5</DiscountedPrice><MinQty>1</MinQty></Promotion>
          <Promotion><DiscountedPrice>5</DiscountedPrice><MinQty>1</MinQty><PromotionEndDate>2020-01-01</PromotionEndDate><PromotionItems><Item><ItemCode>2</ItemCode></Item></PromotionItems></Promotion>
          <Promotion><DiscountedPrice>5</DiscountedPrice><MinQty>1</MinQty><PromotionItems><Item><ItemCode>3</ItemCode></Item></PromotionItems></Promotion>
        </Promotions></Root>""".encode())
        stats = {}
        rows = list(iter_promo_rows(xml, stats=stats))
        self.assertEqual([r.code for r in rows], ["3"])
        self.assertEqual((stats["promotions"], stats["percent_only"], stats["no_items"], stats["expired"], stats["ok"]), (4, 1, 1, 1, 1))
        self.assertIn("promotion", stats["tags"])

    def test_access_error_policy(self):
        class Boom:
            listing_complete = True
            def list_files(self): raise PortalAccessError("no files")
        main.build_adapter = lambda chain, username=None: Boom()
        main.load_gtin_index = lambda: {}
        main.CHAINS[:] = [ChainConfig("unv", "x", "cerberus", "x", verified=False)]
        main.main()  # רשת לא מאומתת שנכשלה - לא מפילה את הריצה
        main.CHAINS[:] = [ChainConfig("ver", "x", "cerberus", "x", verified=True)]
        with self.assertRaises(SystemExit) as cm:
            main.main()
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()

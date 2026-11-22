"""Mock backend + helpers for the real-browser checks. Needs: pip install playwright && playwright install chromium"""
import json, re, sys, urllib.parse
from playwright.sync_api import sync_playwright

import os
WEB = "file://" + os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web", "index.html"))
SHOTS = os.environ.get("SHOTS", "/tmp/lekanot-shots")
os.makedirs(SHOTS, exist_ok=True)
SUPA = re.search(r'const SUPABASE_URL = "(https://[^"]+)"', open(WEB[len("file://"):], encoding="utf-8").read()).group(1)
CHAINS = [("A", "שופרסל"), ("B", "רמי לוי"), ("C", "יוחננוף")]
PRODUCTS = [{"id": f"p{i}", "canonical_name": n, "is_weighted": w, "image_url": None, "gtin": f"729000000000{i}", "created_at": "2026-01-01"}
            for i, (n, w) in enumerate([("חלב תנובה 3% 1 ליטר", False), ("לחם אחיד פרוס", False), ("קוטג' 250 גרם", False), ("בננות", True),
                                        ("שמן זית 750 מ״ל", False), ("אורז בסמטי 1 ק״ג", False), ("ביצים L 12 יח׳", False), ("עגבניות שרי", True)])]
BASE = {"p0": 6.9, "p1": 8.5, "p2": 5.9, "p3": 7.9, "p4": 32, "p5": 11.9, "p6": 14.5, "p7": 12.9}
STORE = {"A": "SA", "B": "SB", "C": "SC"}
def offers(pid):
    out = []
    for i, (cid, cname) in enumerate(CHAINS):
        if pid == "p4" and cid == "C": continue          # שמן זית לא נמצא ביוחננוף
        price = round(BASE[pid] * (1 + 0.04 * i - (0.06 if cid == "B" else 0)), 2)
        out.append({"id": f"{pid}{cid}", "price": price, "price_max": price + 0.5, "unit_price": price if pid in ("p3", "p7") else None,
                    "in_stock": not (pid == "p2" and cid == "A"), "stores_carrying": 10 + i, "store_id": STORE[cid], "product_id": pid,
                    "stores": {"name": "כל הסניפים", "city": None, "chain_id": cid, "chains": {"display_name": cname}}})
    return out

def handler(route):
    url = urllib.parse.urlparse(route.request.url); q = urllib.parse.parse_qs(url.query); path = url.path
    CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*"}
    if route.request.method == "OPTIONS": return route.fulfill(status=204, headers=CORS)
    def ok(body): route.fulfill(status=200, content_type="application/json", headers=CORS, body=json.dumps(body))
    if "/auth/v1/settings" in path: return ok({"external": {"google": False, "email": True}})
    if path.endswith("/rest/v1/products"): return ok(PRODUCTS)
    if path.endswith("/rest/v1/chains"): return ok([{"id": c, "display_name": n} for c, n in CHAINS])
    if path.endswith("/rest/v1/ingest_status"): return ok([{"chain_id": c, "stores_total": 20, "last_complete_at": "2026-11-09T10:00:00Z"} for c, _ in CHAINS])
    if path.endswith("/rest/v1/site_banner"): return ok([{"message": "", "active": False}])
    if path.endswith("/rest/v1/prices"):
        pf = (q.get("product_id") or [""])[0]
        ids = re.findall(r"p\d+", pf)
        rows = [o for pid in ids for o in offers(pid)]
        if (q.get("in_stock") or [""])[0] == "eq.true": rows = [r for r in rows if r["in_stock"]]
        if "stores(" not in (q.get("select") or [""])[0]:
            rows = [{k: r[k] for k in ("product_id", "price", "unit_price")} for r in rows]
        return ok(rows)
    return ok([])

def new_page(p, w, h):
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1); pg = ctx.new_page()
    pg.route(re.compile(re.escape(SUPA) + r"/.*", re.I), handler)
    pg.route(re.compile(r"https://unpkg\.com/.*"), lambda r: r.fulfill(status=200, content_type="text/css", body=".ti{display:inline-block;width:1em;height:1em;background:currentColor;opacity:.35;border-radius:3px;vertical-align:-.1em}"))
    pg.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda r: r.abort())
    pg.on("pageerror", lambda e: print("PAGE ERROR:", e))
    pg.on("console", lambda m: print("console.%s:" % m.type, m.text[:160]) if m.type in ("error",) else None)
    pg.goto(WEB); pg.wait_for_selector(".card", timeout=10000); pg.wait_for_timeout(500)
    return b, pg

def add_items(pg, n=4):
    for i in range(n):
        pg.locator(".card [data-add]").nth(i).click()
    pg.wait_for_timeout(200)

if __name__ == "__main__":
    with sync_playwright() as p:
        b, pg = new_page(p, 390, 844)
        pg.screenshot(path=SHOTS + "/m1_home.png")
        add_items(pg, 5)
        pg.locator('.navbar button[data-nav="cart"]').click(); pg.wait_for_timeout(500)
        pg.screenshot(path=SHOTS + "/m2_cart.png")
        pg.locator("#compareFab").click(); pg.wait_for_selector(".notebook", timeout=8000); pg.wait_for_timeout(700)
        pg.screenshot(path=SHOTS + "/m3_results.png")
        b.close()
    print("shots done")

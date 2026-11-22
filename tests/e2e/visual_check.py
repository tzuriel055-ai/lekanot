"""Real-browser layout checks (Chromium): run  python tests/e2e/visual_check.py  - prints PASS/FAIL per check and saves screenshots."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from mock_backend import new_page, add_items, SHOTS

OK, BAD = [], []
def check(name, cond, detail=""):
    (OK if cond else BAD).append(name); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
rect = lambda pg, sel: pg.evaluate("(s)=>{const e=document.querySelector(s); if(!e) return null; const r=e.getBoundingClientRect(); return {t:r.top,b:r.bottom,l:r.left,r:r.right,w:r.width,h:r.height}}", sel)

with sync_playwright() as p:
    # ===================== מובייל =====================
    b, pg = new_page(p, 390, 844)
    add_items(pg, 6)
    pg.locator('.navbar button[data-nav="cart"]').click(); pg.wait_for_timeout(500)
    fab, nav = rect(pg, "#compareFab"), rect(pg, ".navbar")
    check("FAB visible above the bottom bar (no overlap)", fab and fab["b"] <= nav["t"] - 4, f"fab={fab} nav={nav}")
    check("FAB horizontally centered", abs((fab["l"] + fab["r"]) / 2 - 195) < 3)
    pg.evaluate("document.getElementById('pageCart').scrollTop = 400"); pg.wait_for_timeout(200)
    fab2 = rect(pg, "#compareFab")
    check("FAB stays fixed while the cart list scrolls", abs(fab2["t"] - fab["t"]) < 1, f"{fab['t']} -> {fab2['t']}")

    MOBILE_NAV = rect(pg, ".navbar")
    pg.locator("#compareFab").click(); pg.wait_for_selector(".notebook", timeout=8000); pg.wait_for_timeout(600)
    nb = pg.locator(".notebook").first
    ov = pg.evaluate("(()=>{const n=document.querySelector('.notebook'); return {overflow:getComputedStyle(n).overflow, before:getComputedStyle(n,'::before').content}})()")
    check("notebook does not clip its spiral (overflow visible)", ov["overflow"] == "visible", ov)
    check("notebook has no ::before strip on the edge", ov["before"] in ("none", "normal"), ov)
    nbr, coil = rect(pg, ".notebook"), rect(pg, ".notebook .coil span")
    check("spiral rings protrude above the notebook edge", coil["t"] < nbr["t"] - 3, f"coil.top={coil['t']} nb.top={nbr['t']}")
    check("9 spiral rings drawn", pg.locator(".notebook").first.locator(".coil span").count() == 9)
    sub, nav = rect(pg, "#resultsSubnav"), rect(pg, ".navbar")
    check("results sub-bar sits above the main bottom bar", sub["b"] <= nav["t"] and sub["h"] > 20, f"sub={sub} nav={nav}")
    h = pg.evaluate("document.querySelector('#resultsSubnav button').scrollHeight")
    check("sub-bar labels stay on one line", h < 50, h)
    pg.screenshot(path=SHOTS + "/m4_results.png")

    nb.click(); pg.wait_for_selector(".shop-switcher", timeout=5000); pg.wait_for_timeout(500)
    sw, nav = rect(pg, ".shop-switcher"), rect(pg, ".navbar")
    check("chain switcher is ABOVE the bottom bar, not hidden under it", sw["b"] <= nav["t"], f"switcher={sw} nav={nav}")
    hit = pg.evaluate("(()=>{const s=document.querySelector('.shop-switcher').getBoundingClientRect(); const e=document.elementFromPoint((s.left+s.right)/2,(s.top+s.bottom)/2); return !!e.closest('.shop-switcher')})()")
    check("chain switcher is actually clickable (top-most element at its center)", hit)
    check("switcher lists every chain in the result", pg.locator(".shop-switcher button").count() >= 2, pg.locator(".shop-switcher button").count())
    cl, srch = rect(pg, ".shop-close"), rect(pg, ".search-row")
    check("shop mode: close button does not sit on top of the search bar", cl["t"] >= srch["b"] - 1, (cl, srch))
    title1 = pg.locator("#shopContent .nb-store").first.inner_text()
    pg.locator(".shop-switcher button").nth(1).click(); pg.wait_for_timeout(300)
    title2 = pg.locator("#shopContent .nb-store").first.inner_text()
    check("tapping another chain switches the list", title1 != title2, f"{title1} / {title2}")
    pg.locator("#shopContent .nb-line").first.click(); pg.wait_for_timeout(150)
    check("tapping an item strikes it through", pg.evaluate("document.querySelector('#shopContent .nb-line').classList.contains('done-line')"))
    pg.screenshot(path=SHOTS + "/m5_shop.png")
    pg.locator("#shopCloseBtn").click(); pg.wait_for_timeout(500)
    check("shop mode: close button returns to the comparison results", pg.evaluate("document.getElementById('pageResults').classList.contains('open')") and pg.evaluate("document.getElementById('resultsSubnav').classList.contains('show')"))

    # כותרת עליונה: אין פס זכוכית ריק אחרי הקריסה בגלילה
    pg.locator('.navbar button[data-nav="home"]').click(); pg.wait_for_timeout(300)
    pg.evaluate("window.scrollTo(0, 600)"); pg.wait_for_timeout(500)
    hd = pg.evaluate("(()=>{const h=document.getElementById('topHeader'); const c=getComputedStyle(h); return {collapsed:h.classList.contains('collapsed'), bg:c.backgroundColor, bf:c.backdropFilter, h:h.getBoundingClientRect().height}})()")
    check("mobile scroll: header collapses", hd["collapsed"], hd)
    check("mobile scroll: no leftover empty glass strip (transparent shell)", hd["bg"] in ("rgba(0, 0, 0, 0)", "transparent") and hd["bf"] in ("none", ""), hd)
    sr = rect(pg, ".search-row")
    check("mobile scroll: search stays pinned at the top", sr and sr["t"] < 30 and sr["h"] > 30, sr)
    pg.screenshot(path=SHOTS + "/m6_header_scrolled.png")

    # הגדרות
    pg.evaluate("window.scrollTo(0,0)"); pg.locator('.navbar button[data-nav="settings"]').click(); pg.wait_for_timeout(700)
    txt = pg.inner_text("#settingsContent")
    check("settings: account section + Google disabled until configured", "החשבון שלי" in txt and pg.locator("#googleBtn").is_disabled())
    check("settings: location section present", "המיקום שלי" in txt and pg.locator("#detectBtn").count() == 1)
    pg.screenshot(path=SHOTS + "/m7_settings.png")
    b.close()

    # ===================== מחשב =====================
    b, pg = new_page(p, 1280, 800)
    cols = pg.evaluate("(()=>{const g=document.getElementById('grid'); return getComputedStyle(g).gridTemplateColumns.split(' ').length})()")
    check("desktop: product grid spreads over many columns", cols >= 5, cols)
    add_items(pg, 5)
    pg.locator('.navbar button[data-nav="cart"]').click(); pg.wait_for_timeout(500)
    pg.locator("#compareFab").click(); pg.wait_for_selector(".notebook", timeout=8000); pg.wait_for_timeout(700)
    lefts = pg.evaluate("[...document.querySelectorAll('.results-grid > div')].map(e=>{const r=e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]})")
    check("desktop: results shown side by side (same row, different columns)", len(lefts) >= 3 and len({t for _, t in lefts[:3]}) == 1 and len({l for l, _ in lefts[:3]}) == 3, lefts)
    first_right = max(range(len(lefts)), key=lambda i: lefts[i][0])
    check("desktop: cheapest complete list is the right-most (RTL start)", first_right == 0, lefts)
    nav = rect(pg, ".navbar"); sub = rect(pg, "#resultsSubnav")
    check("desktop: results sub-bar is not covered by the (larger) bottom bar", sub["b"] <= nav["t"] and sub["h"] > 20, (sub, nav))
    pg.screenshot(path=SHOTS + "/d1_results.png")
    pg.locator(".results-grid > div").first.click(); pg.wait_for_selector(".shop-switcher", timeout=5000); pg.wait_for_timeout(400)
    sw = rect(pg, ".shop-switcher"); nav = rect(pg, ".navbar")
    check("desktop: chain switcher is above the bottom bar", sw["b"] <= nav["t"], (sw, nav))
    pg.screenshot(path=SHOTS + "/d2_shop.png")
    pg.locator('.navbar button[data-nav="cart"]').click(); pg.wait_for_timeout(400)
    fab = rect(pg, "#compareFab"); nav = rect(pg, ".navbar")
    check("desktop: compare button is above the bottom bar", fab["b"] <= nav["t"], (fab, nav))
    # בר תחתון גדול יותר במחשב
    nav = rect(pg, ".navbar")
    check("desktop: bottom bar is larger than on mobile", nav["h"] > MOBILE_NAV["h"] + 4 and nav["w"] > MOBILE_NAV["w"], (nav, MOBILE_NAV))
    b.close()

print(f"\n{len(OK)} passed, {len(BAD)} failed")
sys.exit(1 if BAD else 0)

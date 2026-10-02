"""
מושך תמונות מוצר רשמיות מ-Open Food Facts, לפי ברקוד (GTIN) - בדיוק המפתח
שכבר משמש להתאמת מוצרים בין רשתות בקוד הקיים.

Open Food Facts הוא מאגר עולמי חופשי ופתוח לשימוש חוזר (ODbL). הכיסוי שלו
למוצרים ישראליים חלקי - מוצרים בינלאומיים (קוקה-קולה, נוטלה וכו') כמעט
תמיד שם, מותגים מקומיים בלבד פחות. מוצר שלא נמצא נשאר בלי image_url, וזה
בסדר - ה-frontend כבר יודע להציג placeholder נקי במקום.

הרצה: python -m ingest.images
"""

from __future__ import annotations

import logging
import os
import time

import requests

from . import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("images")

OFF_API = "https://world.openfoodfacts.org/api/v2/product"
RAMI_LEVY_IMG = "https://img.rami-levy.co.il/product/{gtin}/small.jpg"
PRICEZ_IMG = "https://m.pricez.co.il/ProductPictures/{gtin}.jpg"
BUCKET = "product-images"
MAX_PRODUCTS = int(os.environ.get("MAX_IMAGES_PER_RUN", "5000"))
_UA = "lekanot-ingest/1.0 (+https://github.com/tzuriel055-ai/lekanot)"


class RateLimited(Exception):
    pass


# מקורות ישירים, לפי ברקוד, בסדר עדיפות - שניהם אומתו ידנית: ברקוד אמיתי
# מחזיר 200 עם תמונה אמיתית, ברקוד מומצא מחזיר שגיאה נקייה (403/404), לא
# placeholder מתחזה. כדי להוסיף מקור נוסף בעתיד - שורה אחת כאן, לא פונקציה חדשה.
DIRECT_IMAGE_SOURCES = [
    ("rami-levy", RAMI_LEVY_IMG),
    ("pricez", PRICEZ_IMG),
]


def fetch_direct_image(gtin: str) -> tuple[str, bytes] | None:
    for name, template in DIRECT_IMAGE_SOURCES:
        try:
            resp = requests.get(template.format(gtin=gtin), headers={"User-Agent": _UA}, timeout=15)
        except requests.RequestException:
            continue
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
            return name, resp.content
        time.sleep(0.1)  # לא מציפים את המקור הבא אם הראשון כבר ענה מהר
    return None


def fetch_off_image_url(gtin: str) -> str | None:
    try:
        resp = requests.get(
            f"{OFF_API}/{gtin}.json",
            params={"fields": "image_front_url,image_url"},
            headers={"User-Agent": _UA},
            timeout=20,
        )
    except requests.RequestException as exc:
        log.warning("OFF request failed for %s: %s", gtin, exc)
        return None
    if resp.status_code == 429:
        raise RateLimited()
    if not resp.ok:
        return None
    data = resp.json()
    if data.get("status") != 1:
        return None
    product = data.get("product", {})
    return product.get("image_front_url") or product.get("image_url")


def main() -> None:
    products = db.select_many(
        "products",
        select="id,gtin",
        limit=MAX_PRODUCTS,
        gtin="not.is.null",
        image_url="is.null",
    )
    log.info("checking %d products without an image", len(products))

    found_direct: dict[str, int] = {name: 0 for name, _ in DIRECT_IMAGE_SOURCES}
    found_off = 0
    rate_limit_hits = 0
    for i, p in enumerate(products):
        gtin = p["gtin"]
        saved = False

        # 1) מקורות ישירים, לפי סדר העדיפות ב-DIRECT_IMAGE_SOURCES
        direct = fetch_direct_image(gtin)
        if direct:
            source_name, content = direct
            try:
                stored_url = db.upload_image(BUCKET, f"{gtin}.jpg", content, "image/jpeg")
                db.update("products", {"gtin": gtin}, {"image_url": stored_url})
                found_direct[source_name] += 1
                saved = True
                log.info("image saved for gtin %s (%s)", gtin, source_name)
            except Exception as exc:
                log.warning("failed saving %s image for %s: %s", source_name, gtin, exc)
        time.sleep(0.15)

        # 2) גיבוי - Open Food Facts, רק אם אף מקור ישיר לא הכיר את הברקוד
        if not saved:
            try:
                image_url = fetch_off_image_url(gtin)
            except RateLimited:
                rate_limit_hits += 1
                log.warning("rate limited by Open Food Facts, backing off 10s (gtin %s)", gtin)
                time.sleep(10)
                image_url = None

            if image_url:
                try:
                    img_resp = requests.get(image_url, headers={"User-Agent": _UA}, timeout=30)
                    img_resp.raise_for_status()
                    content_type = img_resp.headers.get("Content-Type", "image/jpeg")
                    ext = "png" if "png" in content_type else "jpg"
                    stored_url = db.upload_image(BUCKET, f"{gtin}.{ext}", img_resp.content, content_type)
                    db.update("products", {"gtin": gtin}, {"image_url": stored_url})
                    found_off += 1
                    log.info("image saved for gtin %s (open food facts)", gtin)
                except requests.RequestException as exc:
                    log.warning("failed downloading OFF image for %s: %s", gtin, exc)
            # תמיד ממתינים אחרי קריאה ל-OFF, גם כשלא נמצא כלום - זה מה שהיה
            # חסר בפעם הקודמת וגרם לחסימה.
            time.sleep(0.4)

        total_found = sum(found_direct.values()) + found_off
        if (i + 1) % 200 == 0:
            breakdown = ", ".join(f"{k}={v}" for k, v in found_direct.items())
            log.info(
                "progress: %d/%d checked, %d found (%s, off=%d), %d rate-limit hits",
                i + 1, len(products), total_found, breakdown, found_off, rate_limit_hits,
            )

    total_found = sum(found_direct.values()) + found_off
    breakdown = ", ".join(f"{k}={v}" for k, v in found_direct.items())
    log.info(
        "done: %d/%d products got a real image (%s, open-food-facts=%d, %d rate-limit hits)",
        total_found, len(products), breakdown, found_off, rate_limit_hits,
    )


if __name__ == "__main__":
    main()

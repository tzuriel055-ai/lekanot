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
BUCKET = "product-images"
MAX_PRODUCTS = int(os.environ.get("MAX_IMAGES_PER_RUN", "5000"))
_UA = "lekanot-ingest/1.0 (+https://github.com/tzuriel055-ai/lekanot)"


class RateLimited(Exception):
    pass


def fetch_rami_levy_image(gtin: str) -> bytes | None:
    """מקור ראשי: ה-CDN הציבורי של רמי לוי, ישירות לפי ברקוד. אומת ידנית:
    ברקוד אמיתי -> 200 עם תמונה אמיתית; ברקוד מומצא -> 403 נקי, לא placeholder.
    בשונה מ-Open Food Facts, זה הקטלוג האמיתי של רשת ישראלית, אז הכיסוי
    למוצרים מקומיים צפוי להיות הרבה יותר גבוה."""
    try:
        resp = requests.get(RAMI_LEVY_IMG.format(gtin=gtin), headers={"User-Agent": _UA}, timeout=15)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    if not resp.headers.get("Content-Type", "").startswith("image/"):
        return None
    return resp.content


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

    found_rami = 0
    found_off = 0
    rate_limit_hits = 0
    for i, p in enumerate(products):
        gtin = p["gtin"]
        saved = False

        # 1) מקור ראשי - רמי לוי, ישירות, בלי צורך ב-API נפרד
        content = fetch_rami_levy_image(gtin)
        if content:
            try:
                stored_url = db.upload_image(BUCKET, f"{gtin}.jpg", content, "image/jpeg")
                db.update("products", {"gtin": gtin}, {"image_url": stored_url})
                found_rami += 1
                saved = True
                log.info("image saved for gtin %s (rami-levy)", gtin)
            except Exception as exc:
                log.warning("failed saving rami-levy image for %s: %s", gtin, exc)
        time.sleep(0.15)  # ה-CDN שלהם, פחות צריך להיזהר, אבל בכל זאת לא מציפים

        # 2) גיבוי - Open Food Facts, רק אם רמי לוי לא הכיר את הברקוד
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

        total_found = found_rami + found_off
        if (i + 1) % 200 == 0:
            log.info(
                "progress: %d/%d checked, %d found (%d rami-levy, %d off), %d rate-limit hits",
                i + 1, len(products), total_found, found_rami, found_off, rate_limit_hits,
            )

    total_found = found_rami + found_off
    log.info(
        "done: %d/%d products got a real image (%d rami-levy, %d open-food-facts, %d rate-limit hits)",
        total_found, len(products), found_rami, found_off, rate_limit_hits,
    )


if __name__ == "__main__":
    main()

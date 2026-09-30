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
BUCKET = "product-images"
MAX_PRODUCTS = int(os.environ.get("MAX_IMAGES_PER_RUN", "5000"))
_UA = "lekanot-ingest/1.0 (+https://github.com/tzuriel055-ai/lekanot)"


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

    found = 0
    for p in products:
        gtin = p["gtin"]
        image_url = fetch_off_image_url(gtin)
        if not image_url:
            continue
        try:
            img_resp = requests.get(image_url, headers={"User-Agent": _UA}, timeout=30)
            img_resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("failed downloading image for %s: %s", gtin, exc)
            continue

        content_type = img_resp.headers.get("Content-Type", "image/jpeg")
        ext = "png" if "png" in content_type else "jpg"
        stored_url = db.upload_image(BUCKET, f"{gtin}.{ext}", img_resp.content, content_type)
        db.update("products", {"gtin": gtin}, {"image_url": stored_url})
        found += 1
        log.info("image saved for gtin %s", gtin)
        time.sleep(0.3)  # שימוש הוגן מול השרת החיצוני, לא מציפים אותו

    log.info("done: %d/%d products got a real image this run", found, len(products))


if __name__ == "__main__":
    main()

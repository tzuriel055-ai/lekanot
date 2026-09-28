"""
כל אדפטר פורטל (cerberus / shufersal_direct / carrefour_direct) מממש את
הממשק הפשוט הזה: תן לי את הקבצים הכי עדכניים (חנויות, מחירים, מבצעים),
כ-bytes גולמיים. הפענוח עצמו (gzip+XML) קורה במקום אחד ב-parser.py, לא כאן.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass
class FileRef:
    kind: str          # "stores" | "prices" | "promos"
    store_id_ext: str | None  # None אם הקובץ הוא all-stores
    url: str
    label: str


class PortalAdapter(Protocol):
    def list_files(self) -> Iterable[FileRef]: ...
    def download(self, ref: FileRef) -> bytes: ...

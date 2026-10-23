"""
קרפור - מושבת (config.py -> active=False). האתר שלהם טוען את רשימת הקבצים
דרך JavaScript ולא כקישורים סטטיים, ולכן הגישה הפשוטה כאן לא תמצא קבצים.
נשאר כשלד, כדי לא לאבד את המבנה כשנחזור לזה.
"""

from __future__ import annotations

from typing import Iterable

import requests

from .base import FileRef, PortalAccessError


class CarrefourAdapter:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.listing_complete = False

    def list_files(self) -> Iterable[FileRef]:
        raise PortalAccessError("carrefour portal needs a JS-capable client; not implemented yet")

    def download(self, ref: FileRef) -> bytes:
        raise PortalAccessError("not implemented")

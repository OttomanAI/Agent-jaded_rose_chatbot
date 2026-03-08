"""Order tracker — auto-detects the carrier and fetches live tracking data.

Examines the tracking number format to identify the carrier, calls the
appropriate carrier tracker, and returns a normalised result dict.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from tracking.carriers.royal_mail import RoyalMailTracker
from tracking.carriers.dhl import DHLTracker
from tracking.carriers.evri import EvriTracker
from tracking.carriers.dpd import DPDTracker

logger = logging.getLogger(__name__)

# ── Carrier detection patterns ──────────────────────────────────────────
# Royal Mail: 2 letters + 9 digits + 2 letters (e.g. AB123456789GB)
_ROYAL_MAIL_RE = re.compile(r"^[A-Z]{2}\d{9}[A-Z]{2}$")

# DHL: starts with JD followed by digits, or a plain 10-digit number
_DHL_JD_RE = re.compile(r"^JD\d{10,18}$")
_DHL_10_RE = re.compile(r"^\d{10}$")

# Evri (formerly Hermes): 15–16 alphanumeric characters
_EVRI_RE = re.compile(r"^[A-Z0-9]{15,16}$")

# DPD: exactly 14 digits
_DPD_RE = re.compile(r"^\d{14}$")


class OrderTracker:
    """Detects the carrier from a tracking number and fetches tracking status."""

    def __init__(self) -> None:
        """Initialise individual carrier trackers."""
        self._royal_mail = RoyalMailTracker()
        self._dhl = DHLTracker()
        self._evri = EvriTracker()
        self._dpd = DPDTracker()

    def _detect_carrier(self, tracking_number: str) -> Optional[str]:
        """Identify the carrier from the tracking number format.

        Args:
            tracking_number: The tracking number (already uppercased).

        Returns:
            A carrier key string, or None if the format is unrecognised.
        """
        tn = tracking_number.strip().upper()

        if _ROYAL_MAIL_RE.match(tn):
            return "royal_mail"
        if _DHL_JD_RE.match(tn) or _DHL_10_RE.match(tn):
            return "dhl"
        if _DPD_RE.match(tn):
            return "dpd"
        if _EVRI_RE.match(tn):
            return "evri"

        return None

    async def _try_all_carriers(self, tracking_number: str) -> dict:
        """Attempt tracking with every carrier as a fallback.

        Args:
            tracking_number: The tracking number.

        Returns:
            The first successful tracking result, or an error dict.
        """
        carriers = [
            ("Royal Mail", self._royal_mail),
            ("DHL", self._dhl),
            ("Evri", self._evri),
            ("DPD", self._dpd),
        ]

        for name, tracker in carriers:
            try:
                result = await tracker.track(tracking_number)
                if result.get("status") and result["status"] != "not_found":
                    logger.info("Fallback match: %s for %s", name, tracking_number)
                    return result
            except Exception:
                continue

        return {
            "carrier": "Unknown",
            "status": "not_found",
            "estimated_delivery": "",
            "last_event": "",
            "tracking_url": "",
            "events": [],
        }

    async def track(self, tracking_number: str) -> dict:
        """Track a parcel by its tracking number.

        Auto-detects the carrier, queries it, and returns a normalised dict.
        If the carrier cannot be determined, falls back to trying each one.

        Args:
            tracking_number: The parcel tracking number.

        Returns:
            A dict with keys: carrier, status, estimated_delivery,
            last_event, tracking_url, events.
        """
        tn = tracking_number.strip().upper()
        carrier = self._detect_carrier(tn)

        logger.info("Tracking %s — detected carrier: %s", tn, carrier or "unknown")

        tracker_map = {
            "royal_mail": self._royal_mail,
            "dhl": self._dhl,
            "evri": self._evri,
            "dpd": self._dpd,
        }

        if carrier and carrier in tracker_map:
            try:
                return await tracker_map[carrier].track(tn)
            except Exception:
                logger.exception("Primary carrier %s failed for %s — trying fallback", carrier, tn)

        return await self._try_all_carriers(tn)

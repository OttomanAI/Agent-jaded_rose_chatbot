"""Royal Mail parcel tracking.

Uses the Royal Mail Tracking API (v2) to fetch shipment events and
normalises them into the standard tracking result format.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

ROYAL_MAIL_API_KEY: str = os.getenv("ROYAL_MAIL_API_KEY", "")
ROYAL_MAIL_API_URL: str = "https://api.royalmail.net/mailpieces/v2"


class RoyalMailTracker:
    """Track parcels via the Royal Mail Tracking API."""

    def __init__(self) -> None:
        """Initialise the Royal Mail tracker."""
        self._api_key = ROYAL_MAIL_API_KEY

    def _normalise_status(self, status_code: str) -> str:
        """Map Royal Mail status codes to a human-readable status.

        Args:
            status_code: The raw status code from the API.

        Returns:
            A normalised status string.
        """
        mapping = {
            "EVNMI": "In Transit",
            "EVNNA": "In Transit",
            "EVNDL": "Delivered",
            "EVNRT": "Returned",
            "EVNOD": "Out for Delivery",
            "EVNCP": "Collected",
            "EVNDD": "Delivered",
            "EVNAF": "In Transit",
        }
        return mapping.get(status_code.upper(), "In Transit")

    def _normalise_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Convert raw API events into a standard format.

        Args:
            events: A list of event dicts from the Royal Mail API.

        Returns:
            Normalised event dicts with ``timestamp``, ``status``, ``location``.
        """
        normalised: List[Dict[str, str]] = []
        for event in events:
            normalised.append({
                "timestamp": event.get("eventDateTime", ""),
                "status": self._normalise_status(event.get("eventCode", "")),
                "location": event.get("locationName", ""),
            })
        return normalised

    async def track(self, tracking_number: str) -> Dict[str, Any]:
        """Fetch tracking information from Royal Mail.

        Args:
            tracking_number: The Royal Mail tracking number.

        Returns:
            A normalised tracking result dict.
        """
        headers = {
            "X-IBM-Client-Id": self._api_key,
            "X-IBM-Client-Secret": self._api_key,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{ROYAL_MAIL_API_URL}/{tracking_number}/events",
                headers=headers,
            )

        if response.status_code == 404:
            return {
                "carrier": "Royal Mail",
                "status": "not_found",
                "estimated_delivery": "",
                "last_event": "Tracking number not found",
                "tracking_url": f"https://www.royalmail.com/track-your-item#/tracking-results/{tracking_number}",
                "events": [],
            }

        response.raise_for_status()
        data = response.json()

        mailpieces = data.get("mailPieces", [{}])
        mailpiece = mailpieces[0] if mailpieces else {}
        raw_events = mailpiece.get("events", [])
        events = self._normalise_events(raw_events)

        # Latest event
        latest = events[0] if events else {}
        status = latest.get("status", "In Transit")
        last_event_text = f"{latest.get('status', '')} — {latest.get('location', '')}".strip(" — ")
        estimated = mailpiece.get("estimatedDelivery", {}).get("date", "")

        return {
            "carrier": "Royal Mail",
            "status": status,
            "estimated_delivery": estimated,
            "last_event": last_event_text,
            "tracking_url": f"https://www.royalmail.com/track-your-item#/tracking-results/{tracking_number}",
            "events": events,
        }

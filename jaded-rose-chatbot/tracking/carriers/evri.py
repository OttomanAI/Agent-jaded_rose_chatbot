"""Evri (formerly Hermes) parcel tracking.

Queries the Evri public tracking endpoint and normalises the response
into the standard tracking format.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

EVRI_TRACKING_URL: str = "https://api.evri.com/tracking/v1/parcels"


class EvriTracker:
    """Track parcels via the Evri tracking API."""

    def __init__(self) -> None:
        """Initialise the Evri tracker."""
        pass

    def _normalise_status(self, status: str) -> str:
        """Map Evri status descriptions to a standard status.

        Args:
            status: The raw status string from Evri.

        Returns:
            A normalised status string.
        """
        lower = status.lower()
        if "delivered" in lower:
            return "Delivered"
        if "out for delivery" in lower or "with courier" in lower:
            return "Out for Delivery"
        if "hub" in lower or "depot" in lower or "transit" in lower:
            return "In Transit"
        if "collected" in lower or "received" in lower:
            return "Collected"
        if "return" in lower:
            return "Returned"
        return "In Transit"

    def _normalise_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Convert raw Evri events into the standard format.

        Args:
            events: A list of event dicts from the Evri API.

        Returns:
            Normalised event dicts.
        """
        normalised: List[Dict[str, str]] = []
        for event in events:
            normalised.append({
                "timestamp": event.get("dateTime", event.get("timestamp", "")),
                "status": event.get("description", event.get("status", "")),
                "location": event.get("location", ""),
            })
        return normalised

    async def track(self, tracking_number: str) -> Dict[str, Any]:
        """Fetch tracking information from Evri.

        Args:
            tracking_number: The Evri tracking number (15-16 chars).

        Returns:
            A normalised tracking result dict.
        """
        url = f"{EVRI_TRACKING_URL}/{tracking_number}"
        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)

        tracking_page = f"https://www.evri.com/track/parcel/{tracking_number}"

        if response.status_code == 404:
            return {
                "carrier": "Evri",
                "status": "not_found",
                "estimated_delivery": "",
                "last_event": "Tracking number not found",
                "tracking_url": tracking_page,
                "events": [],
            }

        response.raise_for_status()
        data = response.json()

        parcel = data if isinstance(data, dict) else {}
        raw_events = parcel.get("trackingEvents", parcel.get("events", []))
        events = self._normalise_events(raw_events)

        latest = events[0] if events else {}
        status = self._normalise_status(latest.get("status", ""))
        last_event_text = latest.get("status", "")

        estimated = parcel.get("estimatedDeliveryDate", "")

        return {
            "carrier": "Evri",
            "status": status,
            "estimated_delivery": estimated,
            "last_event": last_event_text,
            "tracking_url": tracking_page,
            "events": events,
        }

"""DPD parcel tracking.

Queries the DPD tracking API and normalises the response into the
standard tracking format.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

DPD_API_KEY: str = os.getenv("DPD_API_KEY", "")
DPD_API_URL: str = "https://apis.track.dpd.co.uk/v1"


class DPDTracker:
    """Track parcels via the DPD tracking API."""

    def __init__(self) -> None:
        """Initialise the DPD tracker."""
        self._api_key = DPD_API_KEY

    def _normalise_status(self, status: str) -> str:
        """Map DPD status descriptions to a standard status.

        Args:
            status: The raw status string from DPD.

        Returns:
            A normalised status string.
        """
        lower = status.lower()
        if "delivered" in lower:
            return "Delivered"
        if "out for delivery" in lower or "on vehicle" in lower:
            return "Out for Delivery"
        if "depot" in lower or "hub" in lower or "transit" in lower:
            return "In Transit"
        if "collected" in lower or "received" in lower:
            return "Collected"
        if "exception" in lower or "failed" in lower:
            return "Exception"
        if "return" in lower:
            return "Returned"
        return "In Transit"

    def _normalise_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Convert raw DPD events into the standard format.

        Args:
            events: A list of event dicts from the DPD API.

        Returns:
            Normalised event dicts.
        """
        normalised: List[Dict[str, str]] = []
        for event in events:
            normalised.append({
                "timestamp": event.get("date", event.get("eventDateTime", "")),
                "status": event.get("statusDescription", event.get("description", "")),
                "location": event.get("depot", event.get("location", "")),
            })
        return normalised

    async def track(self, tracking_number: str) -> Dict[str, Any]:
        """Fetch tracking information from DPD.

        Args:
            tracking_number: The DPD 14-digit tracking number.

        Returns:
            A normalised tracking result dict.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        url = f"{DPD_API_URL}/parcels/{tracking_number}"

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)

        tracking_page = f"https://track.dpd.co.uk/parcels/{tracking_number}"

        if response.status_code == 404:
            return {
                "carrier": "DPD",
                "status": "not_found",
                "estimated_delivery": "",
                "last_event": "Tracking number not found",
                "tracking_url": tracking_page,
                "events": [],
            }

        response.raise_for_status()
        data = response.json()

        parcel = data.get("data", data)
        raw_events = parcel.get("events", parcel.get("trackingEvents", []))
        events = self._normalise_events(raw_events)

        latest = events[0] if events else {}
        status = self._normalise_status(latest.get("status", ""))
        last_event_text = latest.get("status", "")

        estimated = parcel.get("estimatedDeliveryDate", parcel.get("deliveryDate", ""))

        return {
            "carrier": "DPD",
            "status": status,
            "estimated_delivery": estimated,
            "last_event": last_event_text,
            "tracking_url": tracking_page,
            "events": events,
        }

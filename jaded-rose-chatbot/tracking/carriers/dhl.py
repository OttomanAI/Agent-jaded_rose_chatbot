"""DHL parcel tracking.

Uses the DHL Shipment Tracking API v2 to fetch delivery status and
normalises the response into the standard tracking format.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

DHL_API_KEY: str = os.getenv("DHL_API_KEY", "")
DHL_API_URL: str = "https://api-eu.dhl.com/track/shipments"


class DHLTracker:
    """Track parcels via the DHL Tracking API v2."""

    def __init__(self) -> None:
        """Initialise the DHL tracker."""
        self._api_key = DHL_API_KEY

    def _normalise_status(self, status_code: str) -> str:
        """Map DHL status codes to a human-readable status.

        Args:
            status_code: The raw status from the DHL API.

        Returns:
            A normalised status string.
        """
        code = status_code.lower()
        if "delivered" in code:
            return "Delivered"
        if "transit" in code:
            return "In Transit"
        if "out for delivery" in code:
            return "Out for Delivery"
        if "customs" in code:
            return "In Customs"
        if "pre-transit" in code or "information received" in code:
            return "Processing"
        if "failure" in code or "exception" in code:
            return "Exception"
        return "In Transit"

    def _normalise_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Convert raw DHL events into the standard format.

        Args:
            events: A list of event dicts from the DHL API.

        Returns:
            Normalised event dicts.
        """
        normalised: List[Dict[str, str]] = []
        for event in events:
            location_parts = []
            loc = event.get("location", {}).get("address", {})
            if loc.get("addressLocality"):
                location_parts.append(loc["addressLocality"])
            if loc.get("countryCode"):
                location_parts.append(loc["countryCode"])

            normalised.append({
                "timestamp": event.get("timestamp", ""),
                "status": event.get("description", ""),
                "location": ", ".join(location_parts),
            })
        return normalised

    async def track(self, tracking_number: str) -> Dict[str, Any]:
        """Fetch tracking information from DHL.

        Args:
            tracking_number: The DHL tracking number.

        Returns:
            A normalised tracking result dict.
        """
        headers = {
            "DHL-API-Key": self._api_key,
            "Accept": "application/json",
        }
        params = {"trackingNumber": tracking_number}

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(DHL_API_URL, headers=headers, params=params)

        if response.status_code == 404:
            return {
                "carrier": "DHL",
                "status": "not_found",
                "estimated_delivery": "",
                "last_event": "Tracking number not found",
                "tracking_url": f"https://www.dhl.com/gb-en/home/tracking.html?tracking-id={tracking_number}",
                "events": [],
            }

        response.raise_for_status()
        data = response.json()

        shipments = data.get("shipments", [])
        if not shipments:
            return {
                "carrier": "DHL",
                "status": "not_found",
                "estimated_delivery": "",
                "last_event": "No shipment data available",
                "tracking_url": f"https://www.dhl.com/gb-en/home/tracking.html?tracking-id={tracking_number}",
                "events": [],
            }

        shipment = shipments[0]
        raw_events = shipment.get("events", [])
        events = self._normalise_events(raw_events)

        status_obj = shipment.get("status", {})
        status = self._normalise_status(status_obj.get("statusCode", ""))
        latest_event = events[0] if events else {}
        last_event_text = latest_event.get("status", "")

        estimated = ""
        eta = shipment.get("estimatedTimeOfDelivery")
        if eta:
            estimated = eta if isinstance(eta, str) else str(eta)

        return {
            "carrier": "DHL",
            "status": status,
            "estimated_delivery": estimated,
            "last_event": last_event_text,
            "tracking_url": f"https://www.dhl.com/gb-en/home/tracking.html?tracking-id={tracking_number}",
            "events": events,
        }

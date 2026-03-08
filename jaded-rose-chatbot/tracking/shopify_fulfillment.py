"""Shopify fulfillment tracker — extracts tracking info from Shopify orders.

Looks up an order by its Jaded Rose order reference (e.g. ``#JR-4821``),
pulls the fulfillment record, and returns the tracking number, carrier
and fulfillment status.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

SHOPIFY_STORE_URL: str = os.getenv("SHOPIFY_STORE_URL", "")
SHOPIFY_ADMIN_API_KEY: str = os.getenv("SHOPIFY_ADMIN_API_KEY", "")


class ShopifyFulfillmentTracker:
    """Extract tracking details from Shopify order fulfillments."""

    def __init__(self) -> None:
        """Initialise the Shopify fulfillment tracker."""
        self._base_url = f"{SHOPIFY_STORE_URL.rstrip('/')}/admin/api/2024-01"
        self._headers = {
            "X-Shopify-Access-Token": SHOPIFY_ADMIN_API_KEY,
            "Content-Type": "application/json",
        }

    async def _search_order_by_name(self, order_name: str) -> Optional[Dict[str, Any]]:
        """Search for an order by its display name (e.g. #JR-4821).

        Args:
            order_name: The customer-facing order reference.

        Returns:
            The order dict from Shopify, or None if not found.
        """
        # Normalise: ensure the name starts with #
        if not order_name.startswith("#"):
            order_name = f"#{order_name}"

        url = f"{self._base_url}/orders.json"
        params = {"name": order_name, "status": "any", "limit": 1}

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self._headers, params=params)
            response.raise_for_status()

        orders = response.json().get("orders", [])
        return orders[0] if orders else None

    async def _get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch an order directly by its Shopify numeric ID.

        Args:
            order_id: The Shopify order ID.

        Returns:
            The order dict, or None.
        """
        url = f"{self._base_url}/orders/{order_id}.json"

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=self._headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()

        return response.json().get("order")

    async def get_tracking_from_order(
        self, order_id_or_name: str
    ) -> Optional[Dict[str, Any]]:
        """Look up an order and extract fulfillment tracking information.

        Accepts either a Shopify numeric order ID or a display name like
        ``JR-4821`` / ``#JR-4821``.

        Args:
            order_id_or_name: The order identifier.

        Returns:
            A dict with ``tracking_number``, ``carrier``, and
            ``fulfillment_status``, or None if the order is not found.
        """
        # Determine whether this is a numeric ID or a display name
        if re.match(r"^\d+$", order_id_or_name):
            order = await self._get_order_by_id(order_id_or_name)
        else:
            order = await self._search_order_by_name(order_id_or_name)

        if not order:
            logger.warning("Order not found: %s", order_id_or_name)
            return None

        fulfillment_status = order.get("fulfillment_status") or "unfulfilled"
        fulfillments = order.get("fulfillments", [])

        if not fulfillments:
            return {
                "tracking_number": "",
                "carrier": "",
                "fulfillment_status": fulfillment_status,
            }

        # Use the most recent fulfillment
        latest = fulfillments[-1]
        tracking_number = latest.get("tracking_number", "")
        carrier = latest.get("tracking_company", "")

        logger.info(
            "Order %s — fulfillment: %s, carrier: %s, tracking: %s",
            order_id_or_name,
            fulfillment_status,
            carrier,
            tracking_number,
        )

        return {
            "tracking_number": tracking_number,
            "carrier": carrier,
            "fulfillment_status": fulfillment_status,
        }

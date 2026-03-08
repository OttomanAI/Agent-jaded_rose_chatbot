"""Order Agent — handles order status and tracking queries.

Extracts the order number from the customer message, looks up the order
in Shopify, fetches tracking information from the relevant carrier, and
returns a clearly formatted status update.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional

import openai

from tracking.tracker import OrderTracker
from tracking.shopify_fulfillment import ShopifyFulfillmentTracker

logger = logging.getLogger(__name__)

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# Regex patterns to extract order numbers from customer messages
_ORDER_PATTERNS = [
    re.compile(r"#?(JR-\d{3,6})", re.IGNORECASE),          # #JR-4821 or JR-4821
    re.compile(r"order\s*(?:number|num|no\.?|#)?\s*(\d{3,6})", re.IGNORECASE),  # order number 4821
    re.compile(r"(?:^|\s)(\d{4,6})(?:\s|$)"),                # bare 4-6 digit number
]


class OrderAgent:
    """Specialist agent for order tracking and status queries."""

    def __init__(self) -> None:
        """Initialise the order agent with tracking dependencies."""
        self._tracker = OrderTracker()
        self._fulfillment = ShopifyFulfillmentTracker()
        self._openai = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    def _extract_order_number(self, text: str) -> Optional[str]:
        """Extract an order number from the customer message.

        Tries multiple regex patterns from most specific to least specific.

        Args:
            text: The customer message text.

        Returns:
            A normalised order reference (e.g. ``"JR-4821"``) or None.
        """
        for pattern in _ORDER_PATTERNS:
            match = pattern.search(text)
            if match:
                raw = match.group(1)
                # Normalise to JR-XXXX format if it's just digits
                if raw.isdigit():
                    return f"JR-{raw}"
                return raw.upper()
        return None

    def _format_tracking(self, tracking_info: dict) -> str:
        """Format tracking data into a customer-friendly message.

        Args:
            tracking_info: Dict with carrier, status, estimated_delivery, etc.

        Returns:
            A formatted status string with emoji indicators.
        """
        status = tracking_info.get("status", "Unknown")
        carrier = tracking_info.get("carrier", "Unknown carrier")
        eta = tracking_info.get("estimated_delivery", "")
        last_event = tracking_info.get("last_event", "")
        tracking_url = tracking_info.get("tracking_url", "")

        # Status emoji mapping
        emoji_map = {
            "delivered": "✅",
            "out_for_delivery": "🚚",
            "in_transit": "📦",
            "collected": "📬",
            "processing": "⏳",
            "shipped": "🚀",
            "exception": "⚠️",
            "returned": "↩️",
        }
        status_lower = status.lower().replace(" ", "_")
        emoji = emoji_map.get(status_lower, "📋")

        lines = [f"{emoji} **Status:** {status}"]
        if carrier:
            lines.append(f"🏷️ **Carrier:** {carrier}")
        if eta:
            lines.append(f"📅 **Estimated delivery:** {eta}")
        if last_event:
            lines.append(f"📍 **Last update:** {last_event}")
        if tracking_url:
            lines.append(f"🔗 **Track your parcel:** {tracking_url}")

        return "\n".join(lines)

    async def handle(self, message: str, history: List[Dict[str, str]]) -> str:
        """Handle an order-tracking customer query.

        Args:
            message: The customer's message.
            history: Recent conversation history.

        Returns:
            A formatted response with order and tracking status.
        """
        order_number = self._extract_order_number(message)

        # Also check conversation history for previously mentioned order numbers
        if not order_number:
            for msg in reversed(history):
                order_number = self._extract_order_number(msg.get("content", ""))
                if order_number:
                    break

        if not order_number:
            return (
                "I'd love to help track your order! 📦\n\n"
                "Could you share your order number? It looks like **#JR-XXXX** "
                "and you'll find it in your confirmation email."
            )

        logger.info("Looking up order %s", order_number)

        # Step 1 — Get fulfillment info from Shopify
        try:
            fulfillment = await self._fulfillment.get_tracking_from_order(order_number)
        except Exception:
            logger.exception("Shopify fulfillment lookup failed for %s", order_number)
            return (
                f"I found order **{order_number}** but I'm having trouble "
                "pulling up the tracking details right now. "
                "Please try again in a moment, or email support@jadedrose.com "
                "and we'll send you an update! 💌"
            )

        if not fulfillment:
            return (
                f"I couldn't find order **{order_number}** in our system. 🤔\n\n"
                "Double-check the number and try again, or share the email "
                "address you used at checkout and I'll look it up that way."
            )

        # Not yet shipped
        if fulfillment.get("fulfillment_status") == "unfulfilled":
            return (
                f"Your order **{order_number}** is confirmed and being prepared! ⏳\n\n"
                "It hasn't shipped yet — we usually dispatch within 1-2 business days. "
                "I'll have tracking info for you once it's on its way!"
            )

        tracking_number = fulfillment.get("tracking_number", "")
        if not tracking_number:
            return (
                f"Your order **{order_number}** has been fulfilled, but I don't "
                "have a tracking number on file yet. It should appear within "
                "a few hours — check back soon! 📬"
            )

        # Step 2 — Get live tracking from the carrier
        try:
            tracking_info = await self._tracker.track(tracking_number)
            formatted = self._format_tracking(tracking_info)
            return f"Here's the latest on order **{order_number}**:\n\n{formatted}"
        except Exception:
            logger.exception("Carrier tracking failed for %s", tracking_number)
            return (
                f"Your order **{order_number}** shipped with tracking number "
                f"**{tracking_number}**, but I'm unable to pull live tracking "
                "right now. You can track it directly with the carrier, or "
                "try again in a few minutes! 📦"
            )

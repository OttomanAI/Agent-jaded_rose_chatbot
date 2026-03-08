"""WhatsApp message handler using Twilio.

Processes inbound WhatsApp messages, routes them through the Supervisor,
and sends replies back via the Twilio Messages API.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from twilio.rest import Client as TwilioClient

from core.supervisor import Supervisor

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
WHATSAPP_FROM_NUMBER: str = os.getenv("WHATSAPP_FROM_NUMBER", "")

# Regex to detect tracking numbers in messages
TRACKING_NUMBER_RE = re.compile(
    r"""
    (?:
        [A-Z]{2}\d{9}[A-Z]{2}              # Royal Mail (e.g. AB123456789GB)
      | (?:JD\d{10,18})                     # DHL JD format
      | \d{10}                               # DHL 10-digit
      | [A-Z0-9]{15,16}                     # Evri 15-16 alphanumeric
      | \d{14}                               # DPD 14-digit
    )
    """,
    re.VERBOSE,
)

_supervisor = Supervisor()


def _get_twilio_client() -> TwilioClient:
    """Return an authenticated Twilio client."""
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _detect_tracking_number(text: str) -> Optional[str]:
    """Extract the first tracking-number-shaped string from a message.

    Args:
        text: The raw message text.

    Returns:
        A tracking number string or None.
    """
    match = TRACKING_NUMBER_RE.search(text.upper())
    return match.group(0) if match else None


async def handle_inbound_message(
    from_number: str,
    body: str,
    media_url: Optional[str] = None,
) -> str:
    """Process an inbound WhatsApp message and return a reply.

    Args:
        from_number: The sender's WhatsApp number (e.g. whatsapp:+447...).
        body: The message text.
        media_url: Optional URL of an attached media file.

    Returns:
        The reply text to send back.
    """
    session_id = f"whatsapp:{from_number}"
    logger.info("WhatsApp message from %s: %s", from_number, body[:120])

    # If a tracking number is found, prepend context for the supervisor
    tracking = _detect_tracking_number(body)
    enriched_message = body
    if tracking:
        enriched_message = f"[Tracking number detected: {tracking}] {body}"

    try:
        response = await _supervisor.process(
            message=enriched_message,
            session_id=session_id,
            channel="whatsapp",
        )
    except Exception:
        logger.exception("Supervisor error for session %s", session_id)
        response = (
            "Sorry, something went wrong on our end. "
            "Please try again shortly or email support@jadedrose.com 💌"
        )

    return response


def send_reply(to_number: str, body: str) -> None:
    """Send a WhatsApp reply via Twilio.

    Args:
        to_number: Recipient number in whatsapp:+44... format.
        body: The message body to send.
    """
    client = _get_twilio_client()
    client.messages.create(
        from_=f"whatsapp:{WHATSAPP_FROM_NUMBER}",
        to=to_number,
        body=body,
    )
    logger.info("WhatsApp reply sent to %s", to_number)

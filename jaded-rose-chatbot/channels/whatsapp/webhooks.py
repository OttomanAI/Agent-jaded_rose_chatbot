"""FastAPI router for the Twilio WhatsApp webhook.

Verifies the Twilio request signature, parses the inbound message and
delegates to the WhatsApp bot handler.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Form, Request, Response
from twilio.request_validator import RequestValidator

from channels.whatsapp.bot import handle_inbound_message, send_reply

logger = logging.getLogger(__name__)

router = APIRouter()

TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")


def _verify_twilio_signature(request: Request, form_data: dict) -> bool:
    """Validate that the request genuinely originated from Twilio.

    Args:
        request: The incoming FastAPI request.
        form_data: The parsed form fields.

    Returns:
        True if the signature is valid, False otherwise.
    """
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(url, form_data, signature)


@router.post("")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(""),
    From: str = Form(""),
    NumMedia: str = Form("0"),
    MediaUrl0: str | None = Form(None),
) -> Response:
    """Receive an inbound WhatsApp message from Twilio.

    Args:
        request: The raw FastAPI request (used for signature verification).
        Body: Message body text.
        From: Sender number in whatsapp:+44... format.
        NumMedia: Number of media attachments.
        MediaUrl0: URL of the first media attachment, if any.

    Returns:
        An empty 200 response (Twilio ignores the body).
    """
    form_data = {
        "Body": Body,
        "From": From,
        "NumMedia": NumMedia,
    }
    if MediaUrl0:
        form_data["MediaUrl0"] = MediaUrl0

    if TWILIO_AUTH_TOKEN and not _verify_twilio_signature(request, form_data):
        logger.warning("Invalid Twilio signature from %s", From)
        return Response(status_code=403)

    media_url = MediaUrl0 if int(NumMedia) > 0 else None
    reply_text = await handle_inbound_message(
        from_number=From,
        body=Body,
        media_url=media_url,
    )
    send_reply(to_number=From, body=reply_text)

    return Response(status_code=200)

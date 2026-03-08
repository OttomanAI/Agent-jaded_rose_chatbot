"""FastAPI router that receives Telegram webhook updates.

When the bot is configured in webhook mode (instead of polling) Telegram
POSTs JSON updates to this endpoint.  The update is validated and forwarded
to the python-telegram-bot Application for processing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from telegram import Update

from channels.telegram.bot import get_application

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("")
async def telegram_webhook(request: Request) -> Response:
    """Receive an update from Telegram and hand it to the bot application.

    Args:
        request: The incoming FastAPI request containing the Telegram update JSON.

    Returns:
        An empty 200 response to acknowledge receipt.
    """
    try:
        payload = await request.json()
        application = get_application()
        update = Update.de_json(data=payload, bot=application.bot)
        await application.process_update(update)
    except Exception:
        logger.exception("Failed to process Telegram webhook update")

    return Response(status_code=200)

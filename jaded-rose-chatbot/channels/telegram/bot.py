"""Telegram bot built with python-telegram-bot v20+.

Handles /start, /help, text messages and document uploads.  Every inbound
message is routed through the Supervisor for intent detection and response
generation.
"""

from __future__ import annotations

import logging
import os
from typing import List

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.supervisor import Supervisor

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Module-level reference so we can stop polling gracefully
_application = None
_supervisor = Supervisor()


def _split_message(text: str, max_length: int = 4000) -> List[str]:
    """Split a long message into chunks that fit within Telegram's limit.

    Args:
        text: The message text to split.
        max_length: Maximum characters per chunk (Telegram allows 4096).

    Returns:
        A list of message chunks.
    """
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Try to split at the last newline within the limit
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command with a welcome message."""
    welcome = (
        "✨ *Welcome to Jaded Rose!* ✨\n\n"
        "I'm your personal shopping assistant. I can help you with:\n\n"
        "🛍️ Product questions & sizing\n"
        "📦 Order tracking\n"
        "🔄 Returns & exchanges\n"
        "❓ Frequently asked questions\n\n"
        "Just type your question and I'll get right on it!"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")  # type: ignore[union-attr]


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_text = (
        "*Here's how I can help:*\n\n"
        "• Ask about any product — sizes, colours, availability\n"
        "• Send your order number (e.g. #JR-4821) to track it\n"
        "• Ask about our returns or exchange policy\n"
        "• Any other question — I'll do my best!\n\n"
        "If I can't resolve something I'll connect you with our team 💬"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")  # type: ignore[union-attr]


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every text message through the Supervisor."""
    if not update.message or not update.message.text:
        return

    session_id = f"telegram:{update.effective_chat.id}"  # type: ignore[union-attr]
    user_message = update.message.text

    logger.info("Telegram message from %s: %s", session_id, user_message[:120])

    try:
        response = await _supervisor.process(
            message=user_message,
            session_id=session_id,
            channel="telegram",
        )
    except Exception:
        logger.exception("Supervisor error for session %s", session_id)
        response = (
            "Sorry, something went wrong on our end. "
            "Please try again in a moment or email us at support@jadedrose.com 💌"
        )

    for chunk in _split_message(response):
        await update.message.reply_text(chunk, parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge document uploads (e.g. return photos)."""
    await update.message.reply_text(  # type: ignore[union-attr]
        "Thanks for sending that! 📎 I've noted the attachment. "
        "If this is for a return, please also share your order number so I can pull up the details.",
        parse_mode="Markdown",
    )


def _build_application():
    """Build and configure the Telegram Application."""
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    return application


async def start_telegram_polling() -> None:
    """Start the Telegram bot in polling mode (called from FastAPI lifespan)."""
    global _application
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram polling skipped.")
        return

    _application = _build_application()
    await _application.initialize()
    await _application.start()
    logger.info("Telegram bot polling started.")
    await _application.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]


async def stop_telegram_polling() -> None:
    """Stop the Telegram bot polling gracefully."""
    global _application
    if _application is None:
        return
    await _application.updater.stop()  # type: ignore[union-attr]
    await _application.stop()
    await _application.shutdown()
    logger.info("Telegram bot polling stopped.")


def get_application():
    """Return the current Application instance (used by the webhook handler)."""
    global _application
    if _application is None:
        _application = _build_application()
    return _application

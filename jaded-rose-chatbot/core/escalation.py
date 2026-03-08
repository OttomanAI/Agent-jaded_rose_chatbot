"""Escalation manager — hands conversations off to human support.

When the Supervisor decides it cannot handle a query (low confidence,
explicit escalation request, or complaint), this module:

1. Sends an email alert to the human support team with the full transcript.
2. Returns a reassuring message to the customer.
3. Logs the escalation for reporting.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from channels.gmail.responder import GmailResponder

logger = logging.getLogger(__name__)

ESCALATION_EMAIL: str = os.getenv("ESCALATION_EMAIL", "team@jadedrose.com")


class EscalationManager:
    """Handles graceful handoff from the AI chatbot to a human agent."""

    def __init__(self) -> None:
        """Initialise the escalation manager."""
        self._responder = GmailResponder()

    def _format_transcript(self, history: List[Dict[str, str]]) -> str:
        """Format conversation history into a readable transcript.

        Args:
            history: List of message dicts with ``role`` and ``content``.

        Returns:
            A plain-text transcript string.
        """
        lines: list[str] = []
        for msg in history:
            role_label = "Customer" if msg["role"] == "user" else "Bot"
            lines.append(f"{role_label}: {msg['content']}")
        return "\n\n".join(lines)

    async def escalate(
        self,
        session_id: str,
        channel: str,
        reason: str,
        conversation_history: List[Dict[str, str]],
    ) -> str:
        """Escalate a conversation to the human support team.

        Sends an email with the full transcript to the escalation inbox
        and returns a customer-facing acknowledgement.

        Args:
            session_id: The session identifier.
            channel: Originating channel (telegram, whatsapp, gmail, web).
            reason: Why the bot is escalating (for internal logging).
            conversation_history: The full conversation so far.

        Returns:
            A message to send back to the customer.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        transcript = self._format_transcript(conversation_history)

        email_body = (
            f"🚨 Escalation Alert — Jaded Rose Chatbot\n"
            f"{'=' * 50}\n\n"
            f"Session ID: {session_id}\n"
            f"Channel:    {channel}\n"
            f"Reason:     {reason}\n"
            f"Time:       {timestamp}\n\n"
            f"{'─' * 50}\n"
            f"CONVERSATION TRANSCRIPT\n"
            f"{'─' * 50}\n\n"
            f"{transcript}\n\n"
            f"{'─' * 50}\n"
            f"Please follow up within 2 hours.\n"
        )

        try:
            self._responder.send_reply(
                to_address=ESCALATION_EMAIL,
                subject=f"[Escalation] {channel.upper()} — {session_id}",
                body_text=email_body,
                thread_id=None,
            )
            logger.info(
                "Escalation email sent for session %s (reason: %s)", session_id, reason
            )
        except Exception:
            logger.exception("Failed to send escalation email for %s", session_id)

        customer_response = (
            "I'm connecting you with our customer experience team — "
            "they'll be in touch within 2 hours. 💬\n\n"
            "If it's urgent, you can also email us directly at "
            "support@jadedrose.com and we'll prioritise your request."
        )
        return customer_response

"""Gmail push-notification listener.

Uses the Gmail API with GCP Pub/Sub push notifications to detect new emails
arriving at the Jaded Rose support inbox.  Each new customer email is routed
through the Supervisor, and a threaded reply is sent via the Responder.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from email.utils import parseaddr
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, Response
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from channels.gmail.responder import GmailResponder
from core.supervisor import Supervisor

logger = logging.getLogger(__name__)

router = APIRouter()

GMAIL_CREDENTIALS_JSON: str = os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")
GMAIL_SUPPORT_ADDRESS: str = os.getenv("GMAIL_SUPPORT_ADDRESS", "support@jadedrose.com")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Simple patterns to detect automated / non-customer emails
_AUTOMATED_PATTERNS = re.compile(
    r"(noreply|no-reply|mailer-daemon|postmaster|notifications?@|newsletter)",
    re.IGNORECASE,
)

_supervisor = Supervisor()
_responder = GmailResponder()


def _get_gmail_service():
    """Build and return an authenticated Gmail API service.

    Returns:
        A Gmail API service resource.
    """
    creds = Credentials.from_authorized_user_file(GMAIL_CREDENTIALS_JSON, SCOPES)
    return build("gmail", "v1", credentials=creds)


def _is_customer_email(sender: str, subject: str) -> bool:
    """Heuristically determine whether an email is a real customer query.

    Args:
        sender: The From address.
        subject: The email subject line.

    Returns:
        True if the email looks like a genuine customer query.
    """
    _, email_addr = parseaddr(sender)
    if _AUTOMATED_PATTERNS.search(email_addr):
        return False
    if _AUTOMATED_PATTERNS.search(subject):
        return False
    return True


def _extract_body(payload: Dict[str, Any]) -> str:
    """Recursively extract the plain-text body from a Gmail message payload.

    Args:
        payload: The Gmail message payload dict.

    Returns:
        The decoded plain-text body, or an empty string.
    """
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""


def _get_header(headers: list, name: str) -> str:
    """Get a specific header value from a Gmail message header list.

    Args:
        headers: List of header dicts with 'name' and 'value' keys.
        name: The header name to look for (case-insensitive).

    Returns:
        The header value, or an empty string if not found.
    """
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


async def _process_message(message_id: str) -> None:
    """Fetch a Gmail message by ID, run it through the Supervisor, and reply.

    Args:
        message_id: The Gmail message ID.
    """
    service = _get_gmail_service()
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers = msg.get("payload", {}).get("headers", [])
    sender = _get_header(headers, "From")
    subject = _get_header(headers, "Subject")
    thread_id = msg.get("threadId", "")

    if not _is_customer_email(sender, subject):
        logger.info("Skipping automated email from %s — %s", sender, subject)
        return

    body = _extract_body(msg.get("payload", {}))
    if not body.strip():
        logger.info("Empty email body from %s — skipping", sender)
        return

    _, email_addr = parseaddr(sender)
    session_id = f"gmail:{email_addr}"
    logger.info("Processing email from %s — subject: %s", email_addr, subject)

    try:
        response = await _supervisor.process(
            message=f"Subject: {subject}\n\n{body}",
            session_id=session_id,
            channel="gmail",
        )
    except Exception:
        logger.exception("Supervisor error for email session %s", session_id)
        response = (
            "Thank you for reaching out! We're experiencing a temporary issue "
            "but our team has been notified and will get back to you shortly."
        )

    _responder.send_reply(
        to_address=email_addr,
        subject=subject,
        body_text=response,
        thread_id=thread_id,
    )

    # Mark as read
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


@router.post("")
async def gmail_push_notification(request: Request) -> Response:
    """Receive a Gmail push notification via GCP Pub/Sub.

    Google Pub/Sub sends a POST with a base64-encoded message containing
    the email address and history ID of the mailbox that changed.

    Args:
        request: The incoming FastAPI request.

    Returns:
        A 200 response to acknowledge the notification.
    """
    try:
        envelope = await request.json()
        pubsub_message = envelope.get("message", {})
        data = base64.urlsafe_b64decode(pubsub_message.get("data", "")).decode("utf-8")
        notification = json.loads(data)

        history_id = notification.get("historyId")
        if not history_id:
            return Response(status_code=200)

        # Fetch recent history to find new messages
        service = _get_gmail_service()
        history = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=history_id, historyTypes=["messageAdded"])
            .execute()
        )

        for record in history.get("history", []):
            for added in record.get("messagesAdded", []):
                msg_id = added["message"]["id"]
                await _process_message(msg_id)

    except Exception:
        logger.exception("Error processing Gmail push notification")

    return Response(status_code=200)

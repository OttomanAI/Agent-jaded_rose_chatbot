"""Gmail responder — sends threaded email replies via the Gmail API.

Replies maintain the original thread so the conversation stays grouped in
the customer's inbox.  Emails use a branded HTML template with the Jaded
Rose signature.
"""

from __future__ import annotations

import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_CREDENTIALS_JSON: str = os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")
GMAIL_SUPPORT_ADDRESS: str = os.getenv("GMAIL_SUPPORT_ADDRESS", "support@jadedrose.com")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #333; line-height: 1.6; }}
    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
    .body-text {{ font-size: 15px; white-space: pre-wrap; }}
    .signature {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; font-size: 13px; color: #888; }}
    .brand {{ font-weight: bold; color: #1a1a1a; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="body-text">{body}</div>
    <div class="signature">
      <p class="brand">Jaded Rose</p>
      <p>Customer Experience Team</p>
      <p>
        <a href="https://jadedrose.com" style="color: #888;">jadedrose.com</a> ·
        <a href="https://instagram.com/jadedrose" style="color: #888;">@jadedrose</a>
      </p>
      <p style="font-size: 11px; color: #aaa;">
        This email was sent by our AI assistant. If you need further help,
        just reply to this email and a member of our team will follow up.
      </p>
    </div>
  </div>
</body>
</html>
"""


class GmailResponder:
    """Sends branded email replies through the Gmail API."""

    def __init__(self) -> None:
        """Initialise the responder (service is created lazily)."""
        self._service = None

    def _get_service(self):
        """Return the Gmail API service, creating it if necessary."""
        if self._service is None:
            creds = Credentials.from_authorized_user_file(GMAIL_CREDENTIALS_JSON, SCOPES)
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def send_reply(
        self,
        to_address: str,
        subject: str,
        body_text: str,
        thread_id: str | None = None,
    ) -> None:
        """Send a branded HTML reply, optionally within an existing thread.

        Args:
            to_address: Recipient email address.
            subject: Email subject (will be prefixed with 'Re:' if needed).
            body_text: Plain-text body that gets inserted into the HTML template.
            thread_id: Gmail thread ID to keep the reply in the same conversation.
        """
        # Ensure subject has "Re:" prefix for replies
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

        message = MIMEMultipart("alternative")
        message["To"] = to_address
        message["From"] = GMAIL_SUPPORT_ADDRESS
        message["Subject"] = reply_subject

        # Plain text fallback
        plain_part = MIMEText(body_text, "plain")
        message.attach(plain_part)

        # HTML version with branding
        html_content = _HTML_TEMPLATE.format(body=body_text.replace("\n", "<br>"))
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        send_body: dict = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        try:
            service = self._get_service()
            service.users().messages().send(userId="me", body=send_body).execute()
            logger.info("Email reply sent to %s (thread: %s)", to_address, thread_id)
        except Exception:
            logger.exception("Failed to send email reply to %s", to_address)
            raise

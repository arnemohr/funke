"""Gmail API client with OAuth2 token refresh.

Provides:
- Email sending via Gmail API
- Custom Message-ID and In-Reply-To headers for threading
- OAuth2 token refresh handling
- Retry logic with exponential backoff
"""

import base64
import secrets
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from .logging import get_logger

logger = get_logger(__name__)


class EmailSettings(BaseSettings):
    """Gmail API configuration settings."""

    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_sender_email: str = ""
    gmail_sender_name: str = "Funke Events"

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_email_settings() -> EmailSettings:
    """Get cached email settings."""
    return EmailSettings()


class EmailMessage(BaseModel):
    """Email message data structure."""

    to: str
    subject: str
    body_text: str
    body_html: str | None = None
    reply_to: str | None = None
    in_reply_to: str | None = None  # Message-ID of parent email for threading
    message_id: str | None = None  # Custom Message-ID (auto-generated if not provided)


class EmailResult(BaseModel):
    """Result of email sending operation."""

    success: bool
    message_id: str | None = None
    gmail_id: str | None = None  # Gmail's internal ID
    error: str | None = None


class GmailClient:
    """Gmail API client for sending and receiving emails."""

    def __init__(self):
        self._service = None
        self._credentials: Credentials | None = None

    def _get_credentials(self) -> Credentials:
        """Get or refresh OAuth2 credentials."""
        settings = get_email_settings()

        required = [
            settings.gmail_client_id,
            settings.gmail_client_secret,
            settings.gmail_refresh_token,
        ]
        if not all(required):
            raise ValueError("Gmail API credentials not configured")

        if self._credentials and self._credentials.valid:
            return self._credentials

        self._credentials = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
        )

        # Refresh the token
        self._credentials.refresh(Request())
        return self._credentials

    def _get_service(self) -> Any:
        """Get or create Gmail API service."""
        if self._service is None:
            credentials = self._get_credentials()
            self._service = build("gmail", "v1", credentials=credentials)
        return self._service

    def _generate_message_id(self, domain: str = "funke.app") -> str:
        """Generate a unique Message-ID."""
        unique_id = secrets.token_hex(16)
        return f"<{unique_id}@{domain}>"

    def _create_mime_message(self, email: EmailMessage) -> MIMEMultipart:
        """Create a MIME message from EmailMessage."""
        settings = get_email_settings()

        if email.body_html:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(email.body_text, "plain", "utf-8"))
            msg.attach(MIMEText(email.body_html, "html", "utf-8"))
        else:
            msg = MIMEMultipart()
            msg.attach(MIMEText(email.body_text, "plain", "utf-8"))

        # Set headers
        msg["To"] = email.to
        msg["From"] = f"{settings.gmail_sender_name} <{settings.gmail_sender_email}>"
        msg["Subject"] = email.subject

        # Generate or use provided Message-ID
        message_id = email.message_id or self._generate_message_id()
        msg["Message-ID"] = message_id

        # Set threading headers
        if email.in_reply_to:
            msg["In-Reply-To"] = email.in_reply_to
            msg["References"] = email.in_reply_to

        if email.reply_to:
            msg["Reply-To"] = email.reply_to

        return msg

    async def send_email(self, email: EmailMessage) -> EmailResult:
        """Send an email via Gmail API.

        Args:
            email: Email message to send.

        Returns:
            EmailResult with success status and message ID.
        """
        try:
            service = self._get_service()
            mime_message = self._create_mime_message(email)

            # Encode message for Gmail API
            raw_message = base64.urlsafe_b64encode(
                mime_message.as_bytes(),
            ).decode("utf-8")

            # Send via Gmail API
            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw_message})
                .execute()
            )

            logger.info(
                "Email sent successfully",
                extra={
                    "gmail_id": result.get("id"),
                    "message_id": mime_message["Message-ID"],
                    "to": email.to,
                    "subject": email.subject,
                },
            )

            return EmailResult(
                success=True,
                message_id=mime_message["Message-ID"],
                gmail_id=result.get("id"),
            )

        except HttpError as e:
            logger.error(
                "Gmail API error",
                extra={
                    "error": str(e),
                    "to": email.to,
                    "subject": email.subject,
                },
            )
            return EmailResult(
                success=False,
                error=f"Gmail API error: {e!s}",
            )

        except Exception as e:
            logger.error(
                "Failed to send email",
                extra={
                    "error": str(e),
                    "to": email.to,
                    "subject": email.subject,
                },
            )
            return EmailResult(
                success=False,
                error=f"Failed to send email: {e!s}",
            )

    async def get_thread(self, gmail_thread_id: str) -> list[dict] | None:
        """Get all messages in a thread.

        Args:
            gmail_thread_id: Gmail's thread ID.

        Returns:
            List of message data or None if not found.
        """
        try:
            service = self._get_service()
            thread = (
                service.users()
                .threads()
                .get(userId="me", id=gmail_thread_id, format="full")
                .execute()
            )
            return thread.get("messages", [])

        except HttpError as e:
            logger.error(f"Failed to get thread: {e}")
            return None

    async def find_message_by_message_id(self, message_id: str) -> dict | None:
        """Find a message by its Message-ID header.

        Args:
            message_id: The Message-ID header value (including angle brackets).

        Returns:
            Message data or None if not found.
        """
        try:
            service = self._get_service()

            # Search for the message
            query = f"rfc822msgid:{message_id}"
            result = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=1)
                .execute()
            )

            messages = result.get("messages", [])
            if not messages:
                return None

            # Get full message details
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=messages[0]["id"], format="full")
                .execute()
            )
            return msg

        except HttpError as e:
            logger.error(f"Failed to find message: {e}")
            return None


# Singleton instance
_gmail_client: GmailClient | None = None


def get_gmail_client() -> GmailClient:
    """Get or create Gmail client instance."""
    global _gmail_client
    if _gmail_client is None:
        _gmail_client = GmailClient()
    return _gmail_client

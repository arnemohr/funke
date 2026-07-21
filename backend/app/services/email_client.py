"""SMTP email client for Strato webmailer.

Provides:
- Email sending via SMTP (Strato)
- Custom Message-ID and In-Reply-To headers for threading
- SSL/STARTTLS support
"""

import secrets
import smtplib
from datetime import datetime, timezone
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import format_datetime, formataddr
from functools import lru_cache

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings

from .logging import get_logger

logger = get_logger(__name__)


class EmailSettings(BaseSettings):
    """SMTP email configuration settings."""

    smtp_host: str = "smtp.strato.de"
    smtp_port: int = 465
    smtp_use_ssl: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender_email: str = ""
    smtp_sender_name: str = "Schaluppe"

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_email_settings() -> EmailSettings:
    """Get cached email settings."""
    return EmailSettings()


class Attachment(BaseModel):
    """Binary email attachment (spec 013 — PDF Fahrberichte)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    filename: str
    content: bytes
    content_type: str = "application/pdf"


class InlineImage(BaseModel):
    """Inline (Content-ID referenced) email image, e.g. a QR code in the body."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    content_id: str  # referenced from HTML as `cid:{content_id}`
    content: bytes
    content_type: str = "image/png"


class EmailMessage(BaseModel):
    """Email message data structure."""

    to: str
    subject: str
    body_text: str
    body_html: str | None = None
    reply_to: str | None = None
    in_reply_to: str | None = None  # Message-ID of parent email for threading
    message_id: str | None = None  # Custom Message-ID (auto-generated if not provided)
    list_unsubscribe: str | None = None  # RFC 2369 List-Unsubscribe header value (bulk mail)
    attachments: list[Attachment] = []
    inline_images: list[InlineImage] = []


class EmailResult(BaseModel):
    """Result of email sending operation."""

    success: bool
    message_id: str | None = None
    error: str | None = None


class SmtpClient:
    """SMTP client for sending emails via Strato."""

    def _generate_message_id(self, domain: str) -> str:
        """Generate a unique Message-ID scoped to the sender's own domain.

        Aligning the Message-ID host with the From/DKIM domain avoids the
        classic "unrelated mailer" spam signal (previously hardcoded to
        funke.app, which the org does not control).
        """
        unique_id = secrets.token_hex(16)
        return f"<{unique_id}@{domain}>"

    def _create_mime_message(self, email: EmailMessage) -> MIMEMultipart:
        """Create a MIME message from EmailMessage."""
        settings = get_email_settings()

        # Build the text/alternative body first.
        if email.body_html:
            body = MIMEMultipart("alternative")
            body.attach(MIMEText(email.body_text, "plain", "utf-8"))
            body.attach(MIMEText(email.body_html, "html", "utf-8"))
        else:
            body = MIMEMultipart()
            body.attach(MIMEText(email.body_text, "plain", "utf-8"))

        if email.inline_images:
            # Wrap the alternative body + inline images in `related` so mail
            # clients resolve the HTML's `cid:` references to these parts.
            related = MIMEMultipart("related")
            related.attach(body)
            for img in email.inline_images:
                subtype = img.content_type.split("/", 1)[-1] or "png"
                image_part = MIMEImage(img.content, _subtype=subtype)
                image_part.add_header("Content-ID", f"<{img.content_id}>")
                image_part.add_header(
                    "Content-Disposition", "inline", filename=f"{img.content_id}.{subtype}",
                )
                related.attach(image_part)
            body = related

        if email.attachments:
            # Wrap the body + attachments in a `mixed` multipart so clients
            # render the body and surface attachments as discrete files.
            msg: MIMEMultipart = MIMEMultipart("mixed")
            msg.attach(body)
            for att in email.attachments:
                subtype = att.content_type.split("/", 1)[-1] or "octet-stream"
                part = MIMEApplication(att.content, _subtype=subtype, name=att.filename)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=att.filename,
                )
                msg.attach(part)
        else:
            msg = body

        # Set headers
        msg["To"] = email.to
        msg["From"] = formataddr(
            (str(Header(settings.smtp_sender_name, "utf-8")), settings.smtp_sender_email)
        )
        msg["Subject"] = email.subject

        # RFC 5322 Date: set an accurate send-time header ourselves — mail is
        # queued and sent later, and a missing Date is a classic spam signal
        # (we don't rely on the MSA to backfill it).
        msg["Date"] = format_datetime(datetime.now(timezone.utc))

        # Generate or use provided Message-ID, scoped to the sender's domain.
        sender_domain = (
            settings.smtp_sender_email.split("@", 1)[-1]
            if "@" in settings.smtp_sender_email
            else "funke.app"
        )
        message_id = email.message_id or self._generate_message_id(sender_domain)
        msg["Message-ID"] = message_id

        # Set threading headers
        if email.in_reply_to:
            msg["In-Reply-To"] = email.in_reply_to
            msg["References"] = email.in_reply_to

        if email.reply_to:
            msg["Reply-To"] = email.reply_to

        # List-Unsubscribe (RFC 2369) — set only for bulk-style mail; a
        # positive complaint-friction / reputation signal at Gmail/GMX/Web.de.
        if email.list_unsubscribe:
            msg["List-Unsubscribe"] = email.list_unsubscribe

        return msg

    async def send_email(self, email: EmailMessage) -> EmailResult:
        """Send an email via SMTP.

        Args:
            email: Email message to send.

        Returns:
            EmailResult with success status and message ID.
        """
        settings = get_email_settings()

        required = [settings.smtp_username, settings.smtp_password, settings.smtp_sender_email]
        if not all(required):
            raise ValueError("SMTP credentials not configured")

        try:
            mime_message = self._create_mime_message(email)

            if settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as server:
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(mime_message)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                    server.starttls()
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(mime_message)

            logger.info(
                "Email sent successfully",
                extra={
                    "message_id": mime_message["Message-ID"],
                    "to": email.to,
                    "subject": email.subject,
                },
            )

            return EmailResult(
                success=True,
                message_id=mime_message["Message-ID"],
            )

        except smtplib.SMTPAuthenticationError as e:
            logger.error(
                "SMTP authentication failed",
                extra={"error": str(e), "to": email.to},
            )
            return EmailResult(
                success=False,
                error=f"SMTP authentication failed: {e!s}",
            )

        except smtplib.SMTPException as e:
            logger.error(
                "SMTP error",
                extra={
                    "error": str(e),
                    "to": email.to,
                    "subject": email.subject,
                },
            )
            return EmailResult(
                success=False,
                error=f"SMTP error: {e!s}",
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



# Singleton instance
_smtp_client: SmtpClient | None = None


def get_gmail_client() -> SmtpClient:
    """Get or create SMTP client instance.

    Note: Function name kept as get_gmail_client for backward compatibility
    with existing imports in email_service.py.
    """
    global _smtp_client
    if _smtp_client is None:
        _smtp_client = SmtpClient()
    return _smtp_client

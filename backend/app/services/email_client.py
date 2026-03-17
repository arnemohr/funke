"""SMTP email client for Strato webmailer.

Provides:
- Email sending via SMTP (Strato)
- Custom Message-ID and In-Reply-To headers for threading
- SSL/STARTTLS support
"""

import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache

from pydantic import BaseModel
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
    smtp_sender_name: str = "Verein für mobile Machenschaften e.V."

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
    error: str | None = None


class SmtpClient:
    """SMTP client for sending emails via Strato."""

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
        msg["From"] = f"{settings.smtp_sender_name} <{settings.smtp_sender_email}>"
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

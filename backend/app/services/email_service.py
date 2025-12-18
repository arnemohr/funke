"""Email service for registration notifications.

Provides:
- Registration confirmation emails
- Waitlist notification emails
- Cancellation confirmation emails
- Promotion from waitlist emails
- Email templating with event/registration context
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from ..models import Event, Message, MessageDirection, MessageStatus, MessageType, Registration
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


class EmailServiceSettings(BaseSettings):
    """Email service configuration."""

    base_url: str = "http://localhost:5173"  # Frontend base URL
    dynamodb_table_prefix: str = "funke-dev"
    aws_region: str = "eu-central-1"
    dynamodb_endpoint_url: str | None = None

    class Config:
        env_prefix = ""
        case_sensitive = False


_settings: EmailServiceSettings | None = None


def get_email_service_settings() -> EmailServiceSettings:
    """Get email service settings (cached)."""
    global _settings
    if _settings is None:
        _settings = EmailServiceSettings()
    return _settings


def get_dynamodb_resource():
    """Get DynamoDB resource."""
    settings = get_email_service_settings()
    kwargs = {"region_name": settings.aws_region}
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def get_messages_table() -> "Table":
    """Get the messages DynamoDB table."""
    settings = get_email_service_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-messages")


class EmailContext(BaseModel):
    """Context for email templates."""

    event_name: str
    event_date: str
    event_location: str | None
    attendee_name: str
    attendee_email: str
    group_size: int
    registration_status: str
    waitlist_position: int | None = None
    cancellation_url: str | None = None
    confirmation_yes_url: str | None = None
    confirmation_no_url: str | None = None


def _format_date(dt: datetime) -> str:
    """Format datetime for display in emails."""
    return dt.strftime("%A, %B %d, %Y at %H:%M")


def _build_cancellation_url(registration_id: UUID, token: str) -> str:
    """Build the cancellation URL for a registration."""
    settings = get_email_service_settings()
    return f"{settings.base_url}/cancel/{registration_id}?token={token}"


def _build_confirmation_url(registration_id: UUID, token: str, response: str) -> str:
    """Build a confirmation response URL."""
    settings = get_email_service_settings()
    return f"{settings.base_url}/confirm/{registration_id}?token={token}&response={response}"


class EmailTemplates:
    """Email templates for various notification types."""

    @staticmethod
    def registration_confirmed(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate registration confirmation email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Registration Confirmed: {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Your registration for "{ctx.event_name}" is confirmed!

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Group Size: {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}

Need to cancel? Use this link:
{ctx.cancellation_url}

We look forward to seeing you!

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Registration Confirmed ✓</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Your registration for <strong>"{ctx.event_name}"</strong> is confirmed!</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Group Size:</strong> {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Need to cancel?</a>
    </p>

    <p>We look forward to seeing you!</p>
    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def registration_waitlisted(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist notification email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Waitlist Position #{ctx.waitlist_position}: {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Thank you for registering for "{ctx.event_name}".

Unfortunately, the event is currently at capacity. You have been added to the waitlist.

Your waitlist position: #{ctx.waitlist_position}

If a spot becomes available, we will automatically move you to the confirmed list and notify you.

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Group Size: {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}

Need to cancel your waitlist position?
{ctx.cancellation_url}

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Added to Waitlist</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Thank you for registering for <strong>"{ctx.event_name}"</strong>.</p>

    <p>Unfortunately, the event is currently at capacity. You have been added to the waitlist.</p>

    <p style="font-size: 1.2em; background: #f5f5f5; padding: 15px; border-radius: 5px;">
        Your waitlist position: <strong>#{ctx.waitlist_position}</strong>
    </p>

    <p>If a spot becomes available, we will automatically move you to the confirmed list and notify you.</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Group Size:</strong> {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Need to cancel your waitlist position?</a>
    </p>

    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def registration_cancelled(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate cancellation confirmation email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Registration Cancelled: {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Your registration for "{ctx.event_name}" has been cancelled.

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}

If you change your mind and would like to register again, please visit the event registration page.

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Registration Cancelled</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Your registration for <strong>"{ctx.event_name}"</strong> has been cancelled.</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
    </ul>

    <p>If you change your mind and would like to register again, please visit the event registration page.</p>

    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def promoted_from_waitlist(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist promotion email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Good News! You're Confirmed: {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Great news! A spot has opened up and your registration for "{ctx.event_name}" is now CONFIRMED!

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Group Size: {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}

Need to cancel? Use this link:
{ctx.cancellation_url}

We look forward to seeing you!

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>🎉 You're Confirmed!</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Great news! A spot has opened up and your registration for <strong>"{ctx.event_name}"</strong> is now <strong>CONFIRMED</strong>!</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Group Size:</strong> {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Need to cancel?</a>
    </p>

    <p>We look forward to seeing you!</p>
    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_winner(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery winner notification email."""
        subject = f"Lottery Result: You're in for {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Great news! You have been selected to attend "{ctx.event_name}".

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Group Size: {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}

Need to cancel? Use this link:
{ctx.cancellation_url}

See you there!
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>🎉 You're In!</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>You have been selected to attend <strong>"{ctx.event_name}"</strong>.</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Group Size:</strong> {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Need to cancel?</a>
    </p>

    <p>See you there!</p>
    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_waitlisted(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery waitlist notification email."""
        subject = f"Lottery Result: Waitlisted for {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Thank you for registering for "{ctx.event_name}".

After the lottery draw, your registration is currently on the waitlist.
Your position: #{ctx.waitlist_position}

If a spot opens up, we'll notify you immediately.

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Group Size: {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}

Need to cancel your waitlist spot?
{ctx.cancellation_url}

Thank you for your patience!
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>You're on the Waitlist</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Thank you for registering for <strong>"{ctx.event_name}"</strong>.</p>

    <p>After the lottery draw, your registration is currently on the waitlist.</p>

    <p style="font-size: 1.2em; background: #f5f5f5; padding: 15px; border-radius: 5px;">
        Waitlist position: <strong>#{ctx.waitlist_position}</strong>
    </p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Group Size:</strong> {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Need to cancel your waitlist spot?</a>
    </p>

    <p>Thank you for your patience!</p>
    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_rejected(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery rejection notification email (no waitlist)."""
        subject = f"Lottery Result: Not Selected for {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

Thank you for registering for "{ctx.event_name}".

Unfortunately, after the lottery draw, your registration was not selected.
Due to high demand, we were unable to accommodate all registrations.

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Group Size: {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}

We hope to see you at future events!

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Lottery Result</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Thank you for registering for <strong>"{ctx.event_name}"</strong>.</p>
    <p>Unfortunately, after the lottery draw, your registration was not selected.
    Due to high demand, we were unable to accommodate all registrations.</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Group Size:</strong> {ctx.group_size} {'person' if ctx.group_size == 1 else 'people'}</li>
    </ul>

    <p>We hope to see you at future events!</p>
    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def event_cancelled(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate event cancellation notification email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Event Cancelled: {ctx.event_name}"

        text_body = f"""Hello {ctx.attendee_name},

We regret to inform you that "{ctx.event_name}" has been cancelled.

Original Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}

We apologize for any inconvenience this may cause.

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #dc2626;">Event Cancelled</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>We regret to inform you that <strong>"{ctx.event_name}"</strong> has been cancelled.</p>

    <h3>Original Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
    </ul>

    <p>We apologize for any inconvenience this may cause.</p>

    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def confirmation_request(ctx: EmailContext, days_until_event: int) -> tuple[str, str, str]:
        """Generate confirmation request email.

        Args:
            ctx: Email context with event and attendee details.
            days_until_event: Number of days until the event.

        Returns: (subject, text_body, html_body)
        """
        urgency = "soon" if days_until_event <= 3 else f"in {days_until_event} days"
        subject = f"Please Confirm: {ctx.event_name} is {urgency}"

        text_body = f"""Hello {ctx.attendee_name},

Your event "{ctx.event_name}" is coming up {urgency}!

Event Details:
- Date: {ctx.event_date}
- Location: {ctx.event_location or 'TBD'}
- Your group size: {ctx.group_size}

Please confirm your attendance:

✅ YES, I will attend: {ctx.confirmation_yes_url}

❌ NO, I cannot attend: {ctx.confirmation_no_url}

If you cannot attend, please let us know as soon as possible so we can offer your spot to someone on the waitlist.

Best regards,
The Event Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2563eb;">Please Confirm Your Attendance</h2>
    <p>Hello {ctx.attendee_name},</p>
    <p>Your event <strong>"{ctx.event_name}"</strong> is coming up {urgency}!</p>

    <h3>Event Details</h3>
    <ul>
        <li><strong>Date:</strong> {ctx.event_date}</li>
        <li><strong>Location:</strong> {ctx.event_location or 'TBD'}</li>
        <li><strong>Your group size:</strong> {ctx.group_size}</li>
    </ul>

    <p><strong>Please confirm your attendance:</strong></p>

    <div style="margin: 20px 0;">
        <a href="{ctx.confirmation_yes_url}" style="display: inline-block; padding: 12px 24px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; margin-right: 10px;">
            ✅ Yes, I will attend
        </a>
        <a href="{ctx.confirmation_no_url}" style="display: inline-block; padding: 12px 24px; background: #dc2626; color: white; text-decoration: none; border-radius: 6px;">
            ❌ No, I cannot attend
        </a>
    </div>

    <p style="color: #666; font-size: 0.9em;">
        If you cannot attend, please let us know as soon as possible so we can offer your spot to someone on the waitlist.
    </p>

    <p>Best regards,<br>The Event Team</p>
</body>
</html>
"""
        return subject, text_body, html_body


def _message_to_item(message: Message) -> dict:
    """Convert Message model to DynamoDB item."""
    item = {
        "pk": f"EVENT#{message.event_id}",
        "sk": f"MSG#{message.id}",
        "id": str(message.id),
        "event_id": str(message.event_id),
        "type": message.type.value,
        "direction": message.direction.value,
        "subject": message.subject,
        "body": message.body,
        "status": message.status.value,
        "retry_count": message.retry_count,
        "entity_type": "Message",
    }

    if message.registration_id:
        item["registration_id"] = str(message.registration_id)
        # GSI uses registration_id directly

    if message.email_message_id:
        item["message_id"] = message.email_message_id

    if message.in_reply_to:
        item["in_reply_to"] = message.in_reply_to

    if message.sent_at:
        item["sent_at"] = message.sent_at.isoformat()

    if message.received_at:
        item["received_at"] = message.received_at.isoformat()

    if message.error_code:
        item["error_code"] = message.error_code

    if message.ttl:
        item["ttl"] = message.ttl

    return item


class EmailService:
    """Service for sending registration-related emails."""

    def __init__(self):
        self._messages_table = None

    @property
    def messages_table(self) -> "Table":
        """Get the messages table (lazy initialization)."""
        if self._messages_table is None:
            self._messages_table = get_messages_table()
        return self._messages_table

    async def _store_message(self, message: Message) -> None:
        """Store a message record in DynamoDB."""
        try:
            item = _message_to_item(message)
            self.messages_table.put_item(Item=item)
            logger.info(
                "Message stored in DynamoDB",
                extra={"message_id": str(message.id), "type": message.type.value},
            )
        except ClientError as e:
            logger.error("Failed to store message", extra={"error": str(e)})
            raise  # Re-raise so outer handler can catch it

    async def send_registration_confirmation(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send registration confirmation email.

        Args:
            event: The event.
            registration: The registration.

        Returns:
            True if email was sent successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            cancellation_url=_build_cancellation_url(
                registration.id,
                registration.registration_token,
            ),
        )

        subject, text_body, html_body = EmailTemplates.registration_confirmed(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.REGISTRATION_CONFIRMATION,
        )

    async def send_waitlist_notification(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send waitlist notification email.

        Args:
            event: The event.
            registration: The registration.

        Returns:
            True if email was sent successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            waitlist_position=registration.waitlist_position,
            cancellation_url=_build_cancellation_url(
                registration.id,
                registration.registration_token,
            ),
        )

        subject, text_body, html_body = EmailTemplates.registration_waitlisted(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.WAITLIST_NOTIFICATION,
        )

    async def send_cancellation_confirmation(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send cancellation confirmation email.

        Args:
            event: The event.
            registration: The cancelled registration.

        Returns:
            True if email was sent successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
        )

        subject, text_body, html_body = EmailTemplates.registration_cancelled(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.CANCELLATION,
        )

    async def send_promotion_notification(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send promotion from waitlist notification.

        Args:
            event: The event.
            registration: The promoted registration.

        Returns:
            True if email was sent successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            cancellation_url=_build_cancellation_url(
                registration.id,
                registration.registration_token,
            ),
        )

        subject, text_body, html_body = EmailTemplates.promoted_from_waitlist(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.LOTTERY_RESULT,  # Reusing for promotion
        )

    async def send_lottery_winner(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send lottery winner notification."""
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            cancellation_url=_build_cancellation_url(
                registration.id,
                registration.registration_token,
            ),
        )

        subject, text_body, html_body = EmailTemplates.lottery_winner(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.LOTTERY_RESULT,
        )

    async def send_lottery_waitlist(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send lottery waitlist notification."""
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            waitlist_position=registration.waitlist_position,
            cancellation_url=_build_cancellation_url(
                registration.id,
                registration.registration_token,
            ),
        )

        subject, text_body, html_body = EmailTemplates.lottery_waitlisted(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.LOTTERY_RESULT,
        )

    async def send_lottery_rejection(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send lottery rejection notification (no waitlist)."""
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
        )

        subject, text_body, html_body = EmailTemplates.lottery_rejected(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.LOTTERY_RESULT,
        )

    async def send_event_cancellation(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send event cancellation notification.

        Args:
            event: The cancelled event.
            registration: The registration to notify.

        Returns:
            True if email was sent successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
        )

        subject, text_body, html_body = EmailTemplates.event_cancelled(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.CANCELLATION,
        )

    async def send_confirmation_request(
        self,
        event: Event,
        registration: Registration,
        days_until_event: int,
    ) -> bool:
        """Send confirmation request email.

        Args:
            event: The event.
            registration: The registration to request confirmation from.
            days_until_event: Number of days until the event.

        Returns:
            True if email was sent successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            confirmation_yes_url=_build_confirmation_url(
                registration.id,
                registration.registration_token,
                "yes",
            ),
            confirmation_no_url=_build_confirmation_url(
                registration.id,
                registration.registration_token,
                "no",
            ),
        )

        subject, text_body, html_body = EmailTemplates.confirmation_request(ctx, days_until_event)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.CONFIRMATION_REQUEST,
        )

    async def _send_email(
        self,
        event_id: UUID,
        registration_id: UUID,
        to: str,
        subject: str,
        text_body: str,
        html_body: str,
        message_type: MessageType,
    ) -> bool:
        """Send an email and record it.

        Args:
            event_id: Event ID.
            registration_id: Registration ID.
            to: Recipient email.
            subject: Email subject.
            text_body: Plain text body.
            html_body: HTML body.
            message_type: Type of message.

        Returns:
            True if email was sent successfully.
        """
        # Create message record
        message = Message(
            id=uuid4(),
            event_id=event_id,
            registration_id=registration_id,
            type=message_type,
            direction=MessageDirection.OUTBOUND,
            subject=subject,
            body=text_body,
            status=MessageStatus.QUEUED,
            retry_count=0,
        )

        try:
            # Log-only mode for development/testing
            # TODO: Replace with actual Gmail API call when ready for production
            logger.info(f"email {message_type.value} sent to {to}")

            message.status = MessageStatus.SENT
            message.sent_at = datetime.utcnow()

            # Store message (best effort - don't fail if DynamoDB unavailable)
            try:
                await self._store_message(message)
            except Exception as store_error:
                logger.warning(
                    "Failed to store message record (non-fatal)",
                    extra={"error": str(store_error)},
                )

            return True

        except Exception as e:
            logger.error(
                "Exception sending email",
                extra={
                    "to": to,
                    "error": str(e),
                },
            )
            return False


# Singleton instance
_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Get or create EmailService instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service

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
    """Format datetime for display in emails (German locale)."""
    weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    months = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
    weekday = weekdays[dt.weekday()]
    month = months[dt.month - 1]
    return f"{weekday}, {dt.day}. {month} {dt.year} um {dt.strftime('%H:%M')}"


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
        subject = f"Anmeldung bestätigt: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Deine Anmeldung für "{ctx.event_name}" ist bestätigt!

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht kannst, storniere hier:
{ctx.cancellation_url}

Wir freuen uns auf dich!

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Anmeldung bestätigt ✓</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Deine Anmeldung für <strong>"{ctx.event_name}"</strong> ist bestätigt!</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du doch nicht kannst, storniere hier</a>
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def registration_waitlisted(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist notification email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Warteliste #{ctx.waitlist_position}: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Leider ist die Veranstaltung schon voll. Du stehst jetzt auf der Warteliste.

Dein Wartelistenplatz: #{ctx.waitlist_position}

Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht willst, storniere hier:
{ctx.cancellation_url}

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Auf die Warteliste gesetzt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>

    <p>Leider ist die Veranstaltung schon voll. Du stehst jetzt auf der Warteliste.</p>

    <p style="font-size: 1.2em; background: #f5f5f5; padding: 15px; border-radius: 5px;">
        Dein Wartelistenplatz: <strong>#{ctx.waitlist_position}</strong>
    </p>

    <p>Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du doch nicht willst, storniere hier</a>
    </p>

    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def registration_cancelled(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate cancellation confirmation email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Anmeldung storniert: {ctx.event_name}"

        text_body = f"""Moin {ctx.attendee_name},

Deine Anmeldung für "{ctx.event_name}" wurde storniert.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Falls du es dir anders überlegst, kannst du dich gerne erneut anmelden.

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Anmeldung storniert</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Deine Anmeldung für <strong>"{ctx.event_name}"</strong> wurde storniert.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Falls du es dir anders überlegst, kannst du dich gerne erneut anmelden.</p>

    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def promoted_from_waitlist(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist promotion email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Du bist dabei! {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Gute Nachrichten! Ein Platz ist frei geworden und du bist jetzt für "{ctx.event_name}" bestätigt!

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht kannst, storniere hier:
{ctx.cancellation_url}

Wir freuen uns auf dich!

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du bist dabei!</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Gute Nachrichten! Ein Platz ist frei geworden und du bist jetzt für <strong>"{ctx.event_name}"</strong> <strong>bestätigt</strong>!</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du doch nicht kannst, storniere hier</a>
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_winner(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery winner notification email."""
        subject = f"Verlosung: Du bist dabei bei {ctx.event_name}!"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Glückwunsch! Du wurdest für "{ctx.event_name}" ausgelost!

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht kannst, storniere hier:
{ctx.cancellation_url}

Wir freuen uns auf dich!

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du bist dabei!</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Glückwunsch! Du wurdest für <strong>"{ctx.event_name}"</strong> ausgelost!</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du doch nicht kannst, storniere hier</a>
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_waitlisted(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery waitlist notification email."""
        subject = f"Verlosung: Warteliste für {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Bei der Verlosung hast du leider keinen Platz bekommen, aber du stehst auf der Warteliste.
Dein Wartelistenplatz: #{ctx.waitlist_position}

Sobald ein Platz frei wird, benachrichtigen wir dich sofort.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht willst, storniere hier:
{ctx.cancellation_url}

Drück die Daumen!

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du stehst auf der Warteliste</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>

    <p>Bei der Verlosung hast du leider keinen Platz bekommen, aber du stehst auf der Warteliste.</p>

    <p style="font-size: 1.2em; background: #f5f5f5; padding: 15px; border-radius: 5px;">
        Dein Wartelistenplatz: <strong>#{ctx.waitlist_position}</strong>
    </p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du doch nicht willst, storniere hier</a>
    </p>

    <p>Drück die Daumen!</p>
    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_rejected(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery rejection notification email (no waitlist)."""
        subject = f"Verlosung: Leider nicht dabei bei {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Leider hast du bei der Verlosung keinen Platz bekommen.
Die Nachfrage war diesmal einfach zu groß.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Wir hoffen, dich beim nächsten Mal dabei zu haben!

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Verlosungsergebnis</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>
    <p>Leider hast du bei der Verlosung keinen Platz bekommen.
    Die Nachfrage war diesmal einfach zu groß.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p>Wir hoffen, dich beim nächsten Mal dabei zu haben!</p>
    <p>Bis bald,<br>Dein Funke-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def event_cancelled(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate event cancellation notification email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Veranstaltung abgesagt: {ctx.event_name}"

        text_body = f"""Moin {ctx.attendee_name},

Leider müssen wir dir mitteilen, dass "{ctx.event_name}" abgesagt wurde.

Ursprüngliche Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Wir entschuldigen uns für die Unannehmlichkeiten.

Bis bald,
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #dc2626;">Veranstaltung abgesagt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Leider müssen wir dir mitteilen, dass <strong>"{ctx.event_name}"</strong> abgesagt wurde.</p>

    <h3>Ursprüngliche Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Wir entschuldigen uns für die Unannehmlichkeiten.</p>

    <p>Bis bald,<br>Dein Funke-Team</p>
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
        if days_until_event <= 1:
            urgency = "morgen"
        elif days_until_event <= 3:
            urgency = "bald"
        else:
            urgency = f"in {days_until_event} Tagen"
        subject = f"Bitte bestätigen: {ctx.event_name} ist {urgency}!"

        text_body = f"""Moin {ctx.attendee_name},

"{ctx.event_name}" steht {urgency} an!

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size}

Bitte bestätige deine Teilnahme:

✅ JA, ich bin dabei: {ctx.confirmation_yes_url}

❌ NEIN, ich kann nicht: {ctx.confirmation_no_url}

Falls du nicht teilnehmen kannst, sag bitte so früh wie möglich Bescheid, damit wir deinen Platz an jemanden von der Warteliste vergeben können.

Bis bald!
Dein Funke-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2563eb;">Bitte bestätige deine Teilnahme</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p><strong>"{ctx.event_name}"</strong> steht {urgency} an!</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size}</li>
    </ul>

    <p><strong>Bitte bestätige deine Teilnahme:</strong></p>

    <div style="margin: 20px 0;">
        <a href="{ctx.confirmation_yes_url}" style="display: inline-block; padding: 12px 24px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; margin-right: 10px;">
            Ja, ich bin dabei!
        </a>
        <a href="{ctx.confirmation_no_url}" style="display: inline-block; padding: 12px 24px; background: #dc2626; color: white; text-decoration: none; border-radius: 6px;">
            Nein, ich kann nicht
        </a>
    </div>

    <p style="color: #666; font-size: 0.9em;">
        Falls du nicht teilnehmen kannst, sag bitte so früh wie möglich Bescheid, damit wir deinen Platz an jemanden von der Warteliste vergeben können.
    </p>

    <p>Bis bald!<br>Dein Funke-Team</p>
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

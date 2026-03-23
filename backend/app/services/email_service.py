"""Email service for registration notifications.

Provides:
- Registration confirmation emails
- Waitlist notification emails
- Cancellation confirmation emails
- Promotion from waitlist emails
- Email templating with event/registration context
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from pydantic import BaseModel

from ..models import Event, Message, MessageDirection, MessageStatus, MessageType, Registration
from .config import get_messages_table, get_settings
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


class EmailContext(BaseModel):
    """Context for email templates."""

    event_name: str
    event_date: str
    event_location: str | None
    registration_deadline: str | None = None
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
    settings = get_settings()
    return f"{settings.base_url}/cancel/{registration_id}?token={token}"


def _build_confirmation_url(registration_id: UUID, token: str, response: str) -> str:
    """Build a confirmation response URL."""
    settings = get_settings()
    return f"{settings.base_url}/confirm/{registration_id}?token={token}&response={response}"


class EmailTemplates:
    """Email templates for various notification types."""

    @staticmethod
    def registration_confirmed(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate registration confirmation email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Anmeldung eingegangen: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

schön, dass du dabei sein willst! Deine Anmeldung für "{ctx.event_name}" ist bei uns eingegangen.

So geht's weiter:
- Bis zum Anmeldeschluss sammeln wir alle Anmeldungen.
- Gibt es mehr Anmeldungen als Plätze, entscheidet das Los.
- Du bekommst danach eine E-Mail, ob du einen Platz hast.

Deine Anmeldung:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}
- Anmeldeschluss: {ctx.registration_deadline or 'Nicht festgelegt'}

Falls du es dir anders überlegst, kannst du hier stornieren:
{ctx.cancellation_url}

Bei Fragen, einfach melden!

Bis bald,
Deine Crew von der Schaluppe
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Anmeldung eingegangen ✓</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>schön, dass du dabei sein willst! Deine Anmeldung für <strong>"{ctx.event_name}"</strong> ist bei uns eingegangen.</p>

    <h3>So geht's weiter</h3>
    <ul>
        <li>Bis zum Anmeldeschluss sammeln wir alle Anmeldungen.</li>
        <li>Gibt es mehr Anmeldungen als Plätze, entscheidet das Los.</li>
        <li>Du bekommst danach eine E-Mail, ob du einen Platz hast.</li>
    </ul>

    <h3>Deine Anmeldung</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
        <li><strong>Anmeldeschluss:</strong> {ctx.registration_deadline or 'Nicht festgelegt'}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du es dir anders überlegst, kannst du hier stornieren</a>
    </p>

    <p>Bei Fragen, einfach melden!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def registration_waitlisted(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist notification email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Warteliste: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

Danke für deine Anmeldung zu "{ctx.event_name}".

Du stehst auf der Warteliste. Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht willst, storniere hier:
{ctx.cancellation_url}

Bis bald,
Deine Crew von der Schaluppe
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du stehst auf der Warteliste</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>

    <p>Du stehst auf der Warteliste. Sobald ein Platz frei wird, rückst du automatisch nach und wir benachrichtigen dich.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.cancellation_url}" style="color: #666;">Falls du doch nicht willst, storniere hier</a>
    </p>

    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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
Deine Crew von der Schaluppe
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

    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def promoted_from_waitlist(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist promotion email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Platz frei geworden: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

gute Nachrichten! Ein Platz ist frei geworden und du bist von der Warteliste nachgerückt für "{ctx.event_name}".

Bitte bestätige kurz, ob du dabei sein kannst:

Ja, ich bin dabei: {ctx.confirmation_yes_url}
Nein, ich kann nicht: {ctx.confirmation_no_url}

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du nicht antwortest, wird dein Platz an die nächste Person auf der Warteliste vergeben.

Bei Fragen, einfach melden!

Bis bald,
Deine Crew von der Schaluppe
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Platz frei geworden!</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Gute Nachrichten! Ein Platz ist frei geworden und du bist von der Warteliste nachgerückt für <strong>"{ctx.event_name}"</strong>.</p>

    <p><strong>Bitte bestätige kurz, ob du dabei sein kannst:</strong></p>

    <p style="margin: 20px 0;">
        <a href="{ctx.confirmation_yes_url}" style="display: inline-block; padding: 12px 24px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin-right: 10px;">Ja, ich bin dabei!</a>
        <a href="{ctx.confirmation_no_url}" style="display: inline-block; padding: 12px 24px; background: #dc2626; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Nein, ich kann nicht</a>
    </p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="color: #666; font-size: 0.9em;">Falls du nicht antwortest, wird dein Platz an die nächste Person auf der Warteliste vergeben.</p>

    <p>Bei Fragen, einfach melden!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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
Deine Crew von der Schaluppe
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
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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
Sobald ein Platz frei wird, benachrichtigen wir dich sofort.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Falls du doch nicht willst, storniere hier:
{ctx.cancellation_url}

Drück die Daumen!

Bis bald,
Deine Crew von der Schaluppe
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Du stehst auf der Warteliste</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Anmeldung zu <strong>"{ctx.event_name}"</strong>.</p>

    <p>Bei der Verlosung hast du leider keinen Platz bekommen, aber du stehst auf der Warteliste.
    Sobald ein Platz frei wird, benachrichtigen wir dich sofort.</p>

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
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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
Deine Crew von der Schaluppe
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
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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
Deine Crew von der Schaluppe
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

    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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
Deine Crew von der Schaluppe
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

    <p>Bis bald!<br>Deine Crew von der Schaluppe</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def attendance_response_confirmation(ctx: EmailContext, participating: bool) -> tuple[str, str, str]:
        """Generate attendance response confirmation email.

        Sent after a user responds YES or NO to confirm they have a record.

        Args:
            ctx: Email context.
            participating: True if user said YES, False if NO.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Rückmeldung bestätigt: {ctx.event_name}"

        if participating:
            text_body = f"""Moin {ctx.attendee_name},

Danke für deine Rückmeldung! Deine Teilnahme an "{ctx.event_name}" ist bestätigt.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Wir freuen uns auf dich!

Bis bald,
Deine Crew von der Schaluppe
"""
            html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Teilnahme bestätigt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Danke für deine Rückmeldung! Deine Teilnahme an <strong>"{ctx.event_name}"</strong> ist bestätigt.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Wir freuen uns auf dich!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
</body>
</html>
"""
        else:
            text_body = f"""Moin {ctx.attendee_name},

Deine Absage für "{ctx.event_name}" wurde erfasst. Schade, dass du nicht dabei sein kannst.

Details:
- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}

Vielleicht beim nächsten Mal!

Bis bald,
Deine Crew von der Schaluppe
"""
            html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Absage bestätigt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Deine Absage für <strong>"{ctx.event_name}"</strong> wurde erfasst. Schade, dass du nicht dabei sein kannst.</p>

    <h3>Details</h3>
    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
    </ul>

    <p>Vielleicht beim nächsten Mal!</p>
    <p>Bis bald,<br>Deine Crew von der Schaluppe</p>
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

    if message.recipient_email:
        item["recipient_email"] = message.recipient_email

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
            registration_deadline=_format_date(event.registration_deadline),
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

        subject, text_body, html_body = EmailTemplates.promoted_from_waitlist(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.CONFIRMATION_REQUEST,
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

    async def send_attendance_response_confirmation(
        self,
        event: Event,
        registration: Registration,
        participating: bool,
    ) -> bool:
        """Send attendance response confirmation email.

        Sent after a user responds YES or NO so they have an email record.

        Args:
            event: The event.
            registration: The registration.
            participating: True if user said YES, False if NO.

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

        subject, text_body, html_body = EmailTemplates.attendance_response_confirmation(
            ctx, participating,
        )

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.CONFIRMATION_REQUEST,
        )

    async def send_custom_message(
        self,
        event: Event,
        registration: Registration,
        subject: str,
        body: str,
        *,
        include_links: bool = False,
    ) -> bool:
        """Send a custom message to a registration.

        Args:
            event: The event.
            registration: The registration to send to.
            subject: Email subject.
            body: Email body text.
            include_links: Whether to append confirmation and cancellation links.

        Returns:
            True if email was sent successfully.
        """
        text_links = ""
        html_links = ""

        if include_links:
            confirm_yes_url = _build_confirmation_url(
                registration.id, registration.registration_token, "yes",
            )
            confirm_no_url = _build_confirmation_url(
                registration.id, registration.registration_token, "no",
            )

            text_links = f"""

---
Ja, ich bin dabei: {confirm_yes_url}
Nein, ich kann nicht: {confirm_no_url}"""

            html_links = f"""
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
    <p style="margin: 10px 0;">
        <a href="{confirm_yes_url}" style="display: inline-block; padding: 10px 20px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin-right: 8px;">Ja, ich bin dabei!</a>
        <a href="{confirm_no_url}" style="display: inline-block; padding: 10px 20px; background: #dc2626; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Nein, ich kann nicht</a>
    </p>"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <p>{body.replace(chr(10), '<br>')}</p>{html_links}
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
    <p style="color: #666; font-size: 0.9em;">
        Diese Nachricht bezieht sich auf die Veranstaltung "{event.name}".
    </p>
    <p style="color: #666; font-size: 0.9em;">Deine Crew von der Schaluppe</p>
</body>
</html>
"""

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=body + text_links,
            html_body=html_body,
            message_type=MessageType.CUSTOM,
        )

    async def list_messages_for_event(self, event_id: UUID) -> list[dict]:
        """List outbound messages for an event.

        Args:
            event_id: Event ID.

        Returns:
            List of message dicts with type, subject, recipient, status, sent_at.
        """
        from boto3.dynamodb.conditions import Key

        try:
            response = self.messages_table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
                FilterExpression="direction = :outbound",
                ExpressionAttributeValues={":outbound": "outbound"},
            )
            items = response.get("Items", [])

            while "LastEvaluatedKey" in response:
                response = self.messages_table.query(
                    KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
                    FilterExpression="direction = :outbound",
                    ExpressionAttributeValues={":outbound": "outbound"},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            return [
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "subject": item.get("subject"),
                    "recipient_email": item.get("recipient_email"),
                    "status": item.get("status"),
                    "sent_at": item.get("sent_at"),
                }
                for item in items
            ]

        except ClientError as e:
            logger.error("Failed to list messages", extra={"error": str(e)})
            return []

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
            # Try to send via Gmail API
            from .email_client import EmailMessage as GmailEmailMessage
            from .email_client import get_gmail_client

            try:
                gmail_client = get_gmail_client()
                gmail_message = GmailEmailMessage(
                    to=to,
                    subject=subject,
                    body_text=text_body,
                    body_html=html_body,
                )
                result = await gmail_client.send_email(gmail_message)

                if result.success:
                    message = message.model_copy(
                        update={
                            "status": MessageStatus.SENT,
                            "email_message_id": result.message_id,
                            "sent_at": datetime.now(timezone.utc),
                            "recipient_email": to,
                        },
                    )
                else:
                    message = message.model_copy(
                        update={
                            "status": MessageStatus.FAILED,
                            "error_code": result.error or "send_failed",
                            "retry_count": 1,
                            "recipient_email": to,
                        },
                    )
            except ValueError:
                # Gmail credentials not configured — log-only fallback for local dev
                logger.info(
                    f"[LOG-ONLY] email {message_type.value} to {to} (Gmail not configured)",
                )
                message = message.model_copy(
                    update={
                        "status": MessageStatus.SENT,
                        "sent_at": datetime.now(timezone.utc),
                        "recipient_email": to,
                    },
                )

            # Store message (best effort - don't fail if DynamoDB unavailable)
            try:
                await self._store_message(message)
            except Exception as store_error:
                logger.warning(
                    "Failed to store message record (non-fatal)",
                    extra={"error": str(store_error)},
                )

            return message.status == MessageStatus.SENT

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

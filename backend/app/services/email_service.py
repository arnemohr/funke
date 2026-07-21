"""Email service for registration notifications.

Provides:
- Registration confirmation emails
- Waitlist notification emails
- Cancellation confirmation emails
- Promotion from waitlist emails
- Email templating with event/registration context
"""

import base64
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from pydantic import BaseModel

from ..models import (
    Event,
    InlineImageData,
    Invite,
    Message,
    MessageDirection,
    MessageStatus,
    MessageType,
    Registration,
)
from .config import get_messages_table, get_settings
from .email_client import get_email_settings
from .logging import get_logger
from .ticket_signing import SignedTicket, build_person_tickets, generate_qr_png

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


# Bulk-style mail that benefits from a List-Unsubscribe header — a positive
# complaint-friction / reputation signal at Gmail/GMX/Web.de. Transactional
# mail (confirmations, cancellations, single self-service replies) is
# deliberately excluded: an unsubscribe on a booking confirmation reads wrong.
_BULK_UNSUBSCRIBE_TYPES = frozenset(
    {
        MessageType.FESTIVAL_INVITATION,
        MessageType.LOTTERY_RESULT,
        MessageType.WAITLIST_NOTIFICATION,
        MessageType.REMINDER,
    },
)


def _unsubscribe_mailto() -> str | None:
    """RFC 2369 List-Unsubscribe value pointing at the monitored sender mailbox.

    mailto: only — no One-Click POST until a real HTTPS unsubscribe endpoint
    exists (a One-Click header pointing at a missing endpoint hurts).
    """
    sender = get_email_settings().smtp_sender_email
    if not sender:
        return None
    return f"<mailto:{sender}?subject=Abmelden>"


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
    cancellation_url: str | None = None  # Deprecated: kept for backward compat
    confirmation_yes_url: str | None = None  # Deprecated: kept for backward compat
    confirmation_no_url: str | None = None  # Deprecated: kept for backward compat
    management_url: str | None = None
    custom_message: str | None = None
    # Festival sidetrack (spec 019) — additive optional fields
    slot_labels: str | None = None  # {Zeitfenster}: comma-joined chosen slot labels, festival order
    accommodation_label: str | None = None  # {Schlafplatz}: Ä17 request semantics
    invite_url: str | None = None  # {EinladungsLink}
    contact_hint: str | None = None  # {KontaktAdresse}
    mitmach_hint: str | None = None  # {MitmachHinweis}, Ä16
    event_period: str | None = None  # {Zeitraum}: "vom 14. bis 16. August 2026" (festival F1)
    event_description: str | None = None  # {Beschreibung}: the event's free-text description (festival F1)


_GERMAN_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_GERMAN_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _format_date(dt: datetime) -> str:
    """Format datetime for display in emails (German locale)."""
    berlin_tz = ZoneInfo("Europe/Berlin")
    dt = dt.astimezone(berlin_tz)
    weekday = _GERMAN_WEEKDAYS[dt.weekday()]
    month = _GERMAN_MONTHS[dt.month - 1]
    return f"{weekday}, {dt.day}. {month} {dt.year} um {dt.strftime('%H:%M')}"


def _format_date_range(start: datetime, end: datetime | None) -> str:
    """Render an event period as German prose, e.g. "vom 14. bis 16. August 2026".

    Single-day events (no end, or same calendar day) render as
    "am Freitag, 14. August 2026". Dates are Europe/Berlin.
    """
    berlin_tz = ZoneInfo("Europe/Berlin")
    s = start.astimezone(berlin_tz)
    e = end.astimezone(berlin_tz) if end else None

    if e is None or (s.year, s.month, s.day) == (e.year, e.month, e.day):
        return f"am {_GERMAN_WEEKDAYS[s.weekday()]}, {s.day}. {_GERMAN_MONTHS[s.month - 1]} {s.year}"
    if (s.year, s.month) == (e.year, e.month):
        return f"vom {s.day}. bis {e.day}. {_GERMAN_MONTHS[s.month - 1]} {s.year}"
    if s.year == e.year:
        return f"vom {s.day}. {_GERMAN_MONTHS[s.month - 1]} bis {e.day}. {_GERMAN_MONTHS[e.month - 1]} {s.year}"
    return (
        f"vom {s.day}. {_GERMAN_MONTHS[s.month - 1]} {s.year} "
        f"bis {e.day}. {_GERMAN_MONTHS[e.month - 1]} {e.year}"
    )


def _build_cancellation_url(registration_id: UUID, token: str) -> str:
    """Build the cancellation URL for a registration (deprecated, kept for old links)."""
    settings = get_settings()
    return f"{settings.base_url}/cancel/{registration_id}?token={token}"


def _build_confirmation_url(registration_id: UUID, token: str, response: str) -> str:
    """Build a confirmation response URL (deprecated, kept for old links)."""
    settings = get_settings()
    return f"{settings.base_url}/confirm/{registration_id}?token={token}&response={response}"


def _build_management_url(registration_id: UUID, token: str) -> str:
    """Build the registration management URL."""
    settings = get_settings()
    return f"{settings.base_url}/registration/{registration_id}?token={token}"


def _build_guestlist_url(token: str) -> str:
    """Build the public guestlist page URL for a contingent invite."""
    settings = get_settings()
    return f"{settings.base_url}/invite/{token}/liste"


def _build_invite_url(token: str) -> str:
    """Build the festival invite (form-boot) URL."""
    settings = get_settings()
    return f"{settings.base_url}/invite/{token}"


def _build_slot_labels(event: Event, attendance_slots: list[str] | None) -> str:
    """Render {Zeitfenster}: comma-joined chosen slot labels, festival order.

    Never rendered as a range (spec §Emails) — always the individual labels.
    """
    if not attendance_slots:
        return ""
    chosen = set(attendance_slots)
    return ", ".join(slot.label for slot in (event.festival_slots or []) if slot.key in chosen)


def _build_accommodation_label(
    tent_count: int | None,
    camper_count: int | None,
    overnight_approved: bool,
) -> str | None:
    """Render {Schlafplatz}: Ä17/Ä21 request semantics.

    No overnight wish -> None (the "- Schlafplatz: …" line is omitted
    entirely). Otherwise the tent/camper units, e.g. "2 Zelte, 1 Camper —
    angefragt" until an admin sets `overnight_approved`, then "... —
    zugesagt". There is deliberately no automatic approval email —
    organizers coordinate by phone (Ä17).
    """
    parts: list[str] = []
    if tent_count:
        parts.append(f"{tent_count} {'Zelt' if tent_count == 1 else 'Zelte'}")
    if camper_count:
        parts.append(f"{camper_count} Camper")
    if not parts:
        return None
    status = "zugesagt" if overnight_approved else "angefragt"
    return f"{', '.join(parts)} — {status}"


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

Deine Anmeldung verwalten:
{ctx.management_url}

Bei Fragen, einfach melden!

Bis bald,
Dein Orga-Team
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
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Bei Fragen, einfach melden!</p>
    <p>Bis bald,<br>Dein Orga-Team</p>
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

Deine Anmeldung verwalten:
{ctx.management_url}

Bis bald,
Dein Orga-Team
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
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Bis bald,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def registration_cancelled(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate cancellation confirmation email.

        Uses custom_message from admin if provided, otherwise falls back to default text.
        The template wraps the message body with greeting and signature.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Dein Platz an Bord: {ctx.event_name}"

        default_message = (
            "Leider haben wir innerhalb der Frist keine Rückmeldung von dir erhalten, "
            "ob du wirklich mit an Bord kommst. Daher mussten wir deinen Platz an einen "
            "anderen Fisch aus unserem Schwarm weitergeben.\n\n"
            "Falls du beim nächsten Mal wieder anheuern möchtest, freuen wir uns sehr auf dich!"
        )
        message_body = ctx.custom_message if ctx.custom_message else default_message

        text_body = f"""Moin {ctx.attendee_name},

{message_body}

Herzliche Grüße,
Dein Orga-Team
"""

        # Convert newlines in message body to <br> for HTML
        html_message = message_body.replace("\n", "<br>")

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #555;">Info zu deiner Anmeldung</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>{html_message}</p>

    <p>Herzliche Grüße,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def promoted_from_waitlist(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate waitlist promotion email.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Platz frei! {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

ein Fisch ist abgesprungen und du rückst nach! Du hast jetzt einen Platz für "{ctx.event_name}".

- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{ctx.management_url}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Dein Orga-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Platz frei!</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Ein Fisch ist abgesprungen und du rückst nach! Du hast jetzt einen Platz für <strong>"{ctx.event_name}"</strong>.</p>

    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p><strong>Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:</strong></p>

    <p style="margin: 20px 0;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Anmeldung verwalten</a>
    </p>

    <p style="color: #666; font-size: 0.9em;">
        Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Liebste Grüße,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def lottery_winner(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate lottery winner notification email."""
        subject = f"Platz reserviert — bitte bestätigen: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        text_body = f"""Moin {ctx.attendee_name},

gute Nachrichten: Du wurdest für "{ctx.event_name}" ausgelost und dein Platz ist reserviert!

- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size} {persons}

Damit der Platz nicht verfällt, bestätige bitte innerhalb von 24 Stunden:

{ctx.management_url}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Wir freuen uns auf dich!

Liebste Grüße,
Dein Orga-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #b45309;">🎉 Platz reserviert — bitte bestätigen</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Gute Nachrichten: Du wurdest für <strong>"{ctx.event_name}"</strong> ausgelost und dein Platz ist reserviert!</p>

    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="background: #fffbeb; border: 1px solid #f59e0b; border-radius: 6px; padding: 12px; color: #92400e;">
        <strong>Damit der Platz nicht verfällt, bestätige bitte innerhalb von 24 Stunden:</strong>
    </p>

    <p style="margin: 20px 0;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 12px 24px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Jetzt bestätigen</a>
    </p>

    <p style="color: #666; font-size: 0.9em;">
        Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.
    </p>

    <p>Wir freuen uns auf dich!</p>
    <p>Liebste Grüße,<br>Dein Orga-Team</p>
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

Deine Anmeldung verwalten:
{ctx.management_url}

Drück die Daumen!

Bis bald,
Dein Orga-Team
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
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Drück die Daumen!</p>
    <p>Bis bald,<br>Dein Orga-Team</p>
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
Dein Orga-Team
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
    <p>Bis bald,<br>Dein Orga-Team</p>
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
Dein Orga-Team
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

    <p>Bis bald,<br>Dein Orga-Team</p>
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

- Datum: {ctx.event_date}
- Ort: {ctx.event_location or 'Wird noch bekannt gegeben'}
- Personen: {ctx.group_size}

Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:

{ctx.management_url}

Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.

Liebste Grüße,
Dein Orga-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2563eb;">Bitte bestätige deine Teilnahme</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p><strong>"{ctx.event_name}"</strong> steht {urgency} an!</p>

    <ul>
        <li><strong>Datum:</strong> {ctx.event_date}</li>
        <li><strong>Ort:</strong> {ctx.event_location or 'Wird noch bekannt gegeben'}</li>
        <li><strong>Personen:</strong> {ctx.group_size}</li>
    </ul>

    <p><strong>Bitte bestätige innerhalb von 24 Stunden, ob du wirklich dabei bist:</strong></p>

    <div style="margin: 20px 0;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Anmeldung verwalten</a>
    </div>

    <p style="color: #666; font-size: 0.9em;">
        Falls dir doch etwas dazwischen kommt, sag bitte umgehend Bescheid, damit sich ein anderer Fisch unserem Schwarm anschließen kann. Nichterscheinen schafft unseren ehrenamtlichen Vereinsprojekten außerdem finanzielle Probleme.
    </p>

    <p>Liebste Grüße,<br>Dein Orga-Team</p>
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
Dein Orga-Team
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
    <p>Bis bald,<br>Dein Orga-Team</p>
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
Dein Orga-Team
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
    <p>Bis bald,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def festival_invitation(
        ctx: EmailContext,
        greeting_name: str | None,
        include_personal_sentence: bool,
        max_uses: int = 1,
        guestlist_url: str | None = None,
    ) -> tuple[str, str, str]:
        """Generate festival invitation email (F1).

        Two independent template params (no single "personal" flag):
        `greeting_name` controls the greeting line, `include_personal_sentence`
        controls the "Der Link ist persönlich..." sentence.

        Contingent invites (`max_uses > 1`) get an extra paragraph spelling
        out the numbers (how many registrations, how many people each) and —
        when `guestlist_url` is set — where the owner can watch their
        guestlist fill up. `ctx.group_size` carries the invite's
        `max_group_size`.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Du bist eingeladen: {ctx.event_name}"
        greeting = f"Moin {greeting_name}," if greeting_name else "Moin!"

        personal_sentence = (
            "\n\nDer Link ist persönlich für dich — bitte leite ihn nicht weiter."
            if include_personal_sentence
            else ""
        )

        # Companion allowance for personal invites with room for more than
        # one person — contingent invites explain group size in their own
        # paragraph instead.
        companion_sentence = ""
        if max_uses == 1 and ctx.group_size and ctx.group_size > 1:
            companions = ctx.group_size - 1
            companion_word = "eine Begleitung" if companions == 1 else f"bis zu {companions} Begleitungen"
            companion_sentence = f"Du kannst {companion_word} mitbringen."
        companion_text = f"\n\n{companion_sentence}" if companion_sentence else ""
        companion_html = f"<p>{companion_sentence}</p>" if companion_sentence else ""

        contingent_paragraph_text = ""
        contingent_paragraph_html = ""
        if max_uses > 1:
            per_reg = (
                f"jede Anmeldung kann bis zu {ctx.group_size} Personen umfassen"
                if ctx.group_size and ctx.group_size > 1
                else "eine Person pro Anmeldung"
            )
            contingent_paragraph_text = (
                f"\n\nDer Link ist dein Kontingent: Du kannst ihn weitergeben, "
                f"er gilt für bis zu {max_uses} Anmeldungen — {per_reg}."
            )
            contingent_paragraph_html = (
                f"<p>Der Link ist dein Kontingent: Du kannst ihn weitergeben, "
                f"er gilt für bis zu {max_uses} Anmeldungen — {per_reg}.</p>"
            )
            if guestlist_url:
                contingent_paragraph_text += (
                    f"\n\nWer sich über deinen Link schon angemeldet hat, siehst du hier:\n{guestlist_url}"
                )
                contingent_paragraph_html += (
                    f'<p>Wer sich über deinen Link schon angemeldet hat, '
                    f'siehst du <a href="{guestlist_url}">auf deiner Gästeliste</a>.</p>'
                )

        # Every fact below comes from the event itself — nothing hardcoded.
        # Same conditional-paragraph pattern as mitmach_hint (F2): never
        # render a literal "None" when the event has no value.
        period = ctx.event_period or ctx.event_date
        location_fact_text = f"\n- Wo: {ctx.event_location}" if ctx.event_location else ""
        location_fact_html = f"<li><strong>Wo:</strong> {ctx.event_location}</li>" if ctx.event_location else ""
        deadline_fact_text = f"\n- Anmelden bis: {ctx.registration_deadline}" if ctx.registration_deadline else ""
        deadline_fact_html = (
            f"<li><strong>Anmelden bis:</strong> {ctx.registration_deadline}</li>"
            if ctx.registration_deadline
            else ""
        )
        mitmach_paragraph_text = f"\n\n{ctx.mitmach_hint}" if ctx.mitmach_hint else ""
        mitmach_paragraph_html = f"<p>{ctx.mitmach_hint}</p>" if ctx.mitmach_hint else ""
        contact_paragraph_text = f"\n\nBei Fragen: {ctx.contact_hint}" if ctx.contact_hint else ""
        description = (ctx.event_description or "").strip()
        description_paragraph_text = f"\n\n{description}" if description else ""
        description_html = description.replace("\n", "<br>")
        description_paragraph_html = f"<p>{description_html}</p>" if description else ""

        text_body = f"""{greeting}

wir feiern {period} — und du bist eingeladen!

- Was: {ctx.event_name}{location_fact_text}{deadline_fact_text}{description_paragraph_text}

Hier meldest du dich an:
{ctx.invite_url}

Bei der Anmeldung sagst du uns, an welchen Tagen du kommst und wen du mitbringst.{personal_sentence}{companion_text}{contingent_paragraph_text}{mitmach_paragraph_text}{contact_paragraph_text}

Bis bald,
Dein Orga-Team
"""

        personal_html = (
            "<p>Der Link ist persönlich für dich — bitte leite ihn nicht weiter.</p>"
            if include_personal_sentence
            else ""
        )
        contact_paragraph_html = f"<p>Bei Fragen: {ctx.contact_hint}</p>" if ctx.contact_hint else ""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <p>{greeting}</p>
    <p>wir feiern {period} — und du bist eingeladen!</p>

    <ul>
        <li><strong>Was:</strong> {ctx.event_name}</li>
        {location_fact_html}
        {deadline_fact_html}
    </ul>
    {description_paragraph_html}
    <p style="margin: 20px 0;">
        <a href="{ctx.invite_url}" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Jetzt anmelden</a>
    </p>

    <p>Bei der Anmeldung sagst du uns, an welchen Tagen du kommst und wen du mitbringst.</p>
    {personal_html}
    {companion_html}
    {contingent_paragraph_html}
    {mitmach_paragraph_html}
    {contact_paragraph_html}
    <p>Bis bald,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def festival_registration_confirmed(
        ctx: EmailContext,
        include_qr_paragraph: bool = False,
        tickets: list[SignedTicket] | None = None,
    ) -> tuple[str, str, str]:
        """Generate festival registration confirmation email (F2).

        The Eintritts-Codes paragraph is rendered ONLY when
        `include_qr_paragraph=True` (P1 always passes False; T308 flips the
        call site to True in P3 once manage-page QRs are live). The
        {MitmachHinweis} paragraph is rendered as its own paragraph ONLY when
        `ctx.mitmach_hint` is set (Ä16).

        `tickets` (T312), when given, embeds one QR code image per person
        directly in the HTML body (`cid:qr-{person_index}` — the caller
        attaches the matching `InlineImage`s), so check-in works straight
        from the mail without opening the manage-page link. The text body
        can't show images, so it always falls back to the manage-page link.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Deine Anmeldung: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"

        qr_paragraph_text = (
            (
                "\n\nDeine Eintritts-Codes sind als Bilder in dieser Mail eingebettet "
                "(siehe HTML-Ansicht) — leite sie an deine Begleitungen weiter."
                if tickets
                else "\n\nAuf der Verwaltungsseite findest du auch die Eintritts-Codes für deine\n"
                "ganze Gruppe — bitte leite sie an deine Begleitungen weiter."
            )
            if include_qr_paragraph
            else ""
        )
        mitmach_paragraph_text = f"\n\n{ctx.mitmach_hint}" if ctx.mitmach_hint else ""
        contact_line_text = f"\nBei Fragen: {ctx.contact_hint}" if ctx.contact_hint else ""
        # Omit the line entirely when there's no accommodation wish (rather
        # than printing "Schlafplatz: Nein") — nothing to report.
        accommodation_line_text = (
            f"\n- Schlafplatz: {ctx.accommodation_label}" if ctx.accommodation_label else ""
        )

        text_body = f"""Moin {ctx.attendee_name},

schön, dass du dabei bist! Deine Anmeldung für "{ctx.event_name}" steht.

Deine Anmeldung:
- Wann: {ctx.slot_labels}{accommodation_line_text}
- Personen: {ctx.group_size} {persons}

Deine Anmeldung verwalten (Zeiten ändern, Begleitungen, absagen):
{ctx.management_url}{qr_paragraph_text}{mitmach_paragraph_text}

Ändern kannst du deine Angaben jederzeit über den Link oben.{contact_line_text}

Bis bald,
Dein Orga-Team
"""

        qr_paragraph_html = (
            (
                "<p>Deine Eintritts-Codes findest du unten — leite sie an deine "
                "Begleitungen weiter.</p>"
                if tickets
                else '<p>Auf der Verwaltungsseite findest du auch die Eintritts-Codes für deine '
                "ganze Gruppe — bitte leite sie an deine Begleitungen weiter.</p>"
            )
            if include_qr_paragraph
            else ""
        )
        mitmach_paragraph_html = f"<p>{ctx.mitmach_hint}</p>" if ctx.mitmach_hint else ""
        contact_line_html = f"<br>Bei Fragen: {ctx.contact_hint}" if ctx.contact_hint else ""
        accommodation_line_html = (
            f"<li><strong>Schlafplatz:</strong> {ctx.accommodation_label}</li>"
            if ctx.accommodation_label
            else ""
        )

        tickets_html = ""
        if tickets:
            cards = "".join(
                f"""
        <div style="display: inline-block; text-align: center; margin: 8px 16px 8px 0; vertical-align: top;">
            <img src="cid:qr-{t.person_index}" width="160" height="160" alt="Eintritts-Code {t.name}" style="display: block; border: 1px solid #e5e7eb; border-radius: 8px;">
            <p style="margin: 4px 0 0; font-size: 0.9em;">{t.name}</p>
        </div>"""
                for t in tickets
            )
            tickets_html = f"""
    <h3>Eure Eintritts-Codes</h3>
    <p style="color: #666; font-size: 0.9em;">Am Einlass zeigt jede Person ihren eigenen Code — ein Screenshot reicht.</p>
    <div>{cards}
    </div>
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #16a34a;">Deine Anmeldung steht ✓</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>schön, dass du dabei bist! Deine Anmeldung für <strong>"{ctx.event_name}"</strong> steht.</p>

    <h3>Deine Anmeldung</h3>
    <ul>
        <li><strong>Wann:</strong> {ctx.slot_labels}</li>
        {accommodation_line_html}
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>
    {tickets_html}
    <p style="margin-top: 20px;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>
    <p style="color: #666; font-size: 0.9em;">Zeiten ändern, Begleitungen, absagen — alles über den Link oben.</p>
    {qr_paragraph_html}
    {mitmach_paragraph_html}

    <p>Ändern kannst du deine Angaben jederzeit über den Link oben.{contact_line_html}</p>

    <p>Bis bald,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def festival_updated(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate festival change confirmation email (F3).

        Returns: (subject, text_body, html_body)
        """
        subject = f"Deine Änderung: {ctx.event_name}"
        persons = "Person" if ctx.group_size == 1 else "Personen"
        # Omit the line entirely when there's no accommodation wish (rather
        # than printing "Schlafplatz: Nein") — nothing to report.
        accommodation_line_text = (
            f"\n- Schlafplatz: {ctx.accommodation_label}" if ctx.accommodation_label else ""
        )
        accommodation_line_html = (
            f"<li><strong>Schlafplatz:</strong> {ctx.accommodation_label}</li>"
            if ctx.accommodation_label
            else ""
        )

        text_body = f"""Moin {ctx.attendee_name},

alles klar, wir haben deine Änderung gespeichert.

Deine aktuelle Anmeldung:
- Wann: {ctx.slot_labels}{accommodation_line_text}
- Personen: {ctx.group_size} {persons}

Deine Anmeldung verwalten:
{ctx.management_url}

Bis bald,
Dein Orga-Team
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2563eb;">Änderung gespeichert</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Alles klar, wir haben deine Änderung gespeichert.</p>

    <h3>Deine aktuelle Anmeldung</h3>
    <ul>
        <li><strong>Wann:</strong> {ctx.slot_labels}</li>
        {accommodation_line_html}
        <li><strong>Personen:</strong> {ctx.group_size} {persons}</li>
    </ul>

    <p style="margin-top: 20px;">
        <a href="{ctx.management_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">Anmeldung verwalten</a>
    </p>

    <p>Bis bald,<br>Dein Orga-Team</p>
</body>
</html>
"""
        return subject, text_body, html_body

    @staticmethod
    def festival_cancelled(ctx: EmailContext) -> tuple[str, str, str]:
        """Generate festival cancellation confirmation email (F4).

        A dedicated template, so the lottery default text ("...Platz an
        einen anderen Fisch...") never reaches a festival guest.

        Returns: (subject, text_body, html_body)
        """
        subject = f"Deine Absage: {ctx.event_name}"

        # Conditional paragraph — never render a literal "None" when the
        # event has no contact_hint.
        contact_paragraph_text = (
            f"\n\nFalls du es dir anders überlegst, schreib uns: {ctx.contact_hint}"
            if ctx.contact_hint
            else ""
        )

        text_body = f"""Moin {ctx.attendee_name},

schade, dass du nicht dabei bist — deine Anmeldung für "{ctx.event_name}"
ist storniert.{contact_paragraph_text}

Bis zum nächsten Mal,
Dein Orga-Team
"""

        contact_paragraph_html = (
            f"<p>Falls du es dir anders überlegst, schreib uns: {ctx.contact_hint}</p>"
            if ctx.contact_hint
            else ""
        )

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #555;">Absage bestätigt</h2>
    <p>Moin {ctx.attendee_name},</p>
    <p>Schade, dass du nicht dabei bist — deine Anmeldung für <strong>"{ctx.event_name}"</strong> ist storniert.</p>
    {contact_paragraph_html}
    <p>Bis zum nächsten Mal,<br>Dein Orga-Team</p>
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

    if message.body_html:
        item["body_html"] = message.body_html

    if message.inline_images:
        item["inline_images"] = [img.model_dump() for img in message.inline_images]

    if message.list_unsubscribe:
        item["list_unsubscribe"] = message.list_unsubscribe

    if message.registration_id:
        item["registration_id"] = str(message.registration_id)
        # GSI uses registration_id directly

    if message.email_message_id:
        item["email_message_id"] = message.email_message_id

    if message.in_reply_to:
        item["in_reply_to"] = message.in_reply_to

    if message.sent_at:
        item["sent_at"] = message.sent_at.isoformat()

    if message.received_at:
        item["received_at"] = message.received_at.isoformat()

    if message.recipient_email:
        item["recipient_email"] = message.recipient_email

    if message.created_at:
        item["created_at"] = message.created_at.isoformat()

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
            management_url=_build_management_url(
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
            management_url=_build_management_url(
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
        reason: str | None = None,
        subject_override: str | None = None,
    ) -> bool:
        """Send cancellation confirmation email.

        Args:
            event: The event.
            registration: The cancelled registration.
            reason: Optional custom message from admin.
            subject_override: Optional custom email subject line.

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
            custom_message=reason,
        )

        subject, text_body, html_body = EmailTemplates.registration_cancelled(ctx)

        if subject_override:
            subject = subject_override

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
            management_url=_build_management_url(
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
            management_url=_build_management_url(
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
            management_url=_build_management_url(
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
            management_url=_build_management_url(
                registration.id,
                registration.registration_token,
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
            manage_url = _build_management_url(
                registration.id, registration.registration_token,
            )

            text_links = f"""

---
Anmeldung verwalten: {manage_url}"""

            html_links = f"""
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
    <p style="margin: 10px 0;">
        <a href="{manage_url}" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Anmeldung verwalten</a>
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
    <p style="color: #666; font-size: 0.9em;">Dein Orga-Team</p>
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

    async def send_festival_invitation(
        self,
        event: Event,
        invite: Invite,
    ) -> bool:
        """Send a festival invitation email (F1).

        Args:
            event: The festival event.
            invite: The invite to send. Requires `invite.email` — returns
                False otherwise (nothing to send to).

        Returns:
            True if email was queued successfully.
        """
        if not invite.email:
            return False

        # The mail goes to `invite.email` — the person the row is labeled
        # after (personal guest or contingent owner), so the greeting always
        # uses the label. Only the "persönlich, nicht weiterleiten" sentence
        # is tied to single-use links.
        is_personal = invite.max_uses == 1
        greeting_name = invite.label

        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_period=_format_date_range(event.start_at, event.end_at),
            event_description=event.description,
            event_location=event.location,
            registration_deadline=_format_date(event.registration_deadline),
            attendee_name=invite.label,
            attendee_email=invite.email,
            group_size=invite.max_group_size,
            registration_status="invited",
            invite_url=_build_invite_url(invite.token),
            contact_hint=event.contact_hint,
            mitmach_hint=event.participation_hint,
        )

        subject, text_body, html_body = EmailTemplates.festival_invitation(
            ctx,
            greeting_name=greeting_name,
            include_personal_sentence=is_personal,
            max_uses=invite.max_uses,
            guestlist_url=None if is_personal else _build_guestlist_url(invite.token),
        )

        return await self._send_email(
            event_id=event.id,
            registration_id=None,
            to=invite.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.FESTIVAL_INVITATION,
        )

    async def send_festival_confirmation(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send festival registration confirmation email (F2).

        Args:
            event: The festival event.
            registration: The new festival registration.

        Returns:
            True if email was queued successfully.
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
            management_url=_build_management_url(
                registration.id,
                registration.registration_token,
            ),
            slot_labels=_build_slot_labels(event, registration.attendance_slots),
            accommodation_label=_build_accommodation_label(
                registration.tent_count,
                registration.camper_count,
                registration.overnight_approved,
            ),
            contact_hint=event.contact_hint,
            mitmach_hint=event.participation_hint,
        )

        # T312: embed one QR ticket image per person directly in the mail
        # (in addition to the manage-page's live QRs) so check-in works
        # straight from the inbox. Never fail the confirmation over this —
        # worst case the guest falls back to the manage-page link.
        tickets: list[SignedTicket] = []
        inline_images: list[InlineImageData] = []
        try:
            from .event_service import get_event_service

            event_svc = get_event_service()
            credentialed_event = await event_svc.ensure_gate_credentials(event.org_id, event.id)
            if credentialed_event is not None and credentialed_event.ticket_secret:
                tickets = build_person_tickets(
                    credentialed_event.ticket_secret,
                    registration.id,
                    registration.name,
                    registration.group_members,
                    registration.attendance_slots,
                    registration.overnight_approved,
                )
                for t in tickets:
                    png = generate_qr_png(t.code)
                    inline_images.append(
                        InlineImageData(
                            content_id=f"qr-{t.person_index}",
                            content_b64=base64.b64encode(png).decode("ascii"),
                        ),
                    )
        except Exception as e:
            logger.error(
                "Failed to build QR ticket images for confirmation email",
                extra={"error": str(e), "registration_id": str(registration.id)},
            )
            tickets = []
            inline_images = []

        subject, text_body, html_body = EmailTemplates.festival_registration_confirmed(
            ctx, include_qr_paragraph=True, tickets=tickets,
        )

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.FESTIVAL_CONFIRMATION,
            inline_images=inline_images,
        )

    async def send_festival_update_confirmation(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send festival change confirmation email (F3).

        Args:
            event: The festival event.
            registration: The updated festival registration.

        Returns:
            True if email was queued successfully.
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
            management_url=_build_management_url(
                registration.id,
                registration.registration_token,
            ),
            slot_labels=_build_slot_labels(event, registration.attendance_slots),
            accommodation_label=_build_accommodation_label(
                registration.tent_count,
                registration.camper_count,
                registration.overnight_approved,
            ),
            contact_hint=event.contact_hint,
        )

        subject, text_body, html_body = EmailTemplates.festival_updated(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.FESTIVAL_UPDATE,
        )

    async def send_festival_cancellation(
        self,
        event: Event,
        registration: Registration,
    ) -> bool:
        """Send festival cancellation confirmation email (F4).

        A dedicated template, so the lottery default text never reaches a
        festival guest.

        Args:
            event: The festival event.
            registration: The cancelled festival registration.

        Returns:
            True if email was queued successfully.
        """
        ctx = EmailContext(
            event_name=event.name,
            event_date=_format_date(event.start_at),
            event_location=event.location,
            attendee_name=registration.name,
            attendee_email=registration.email,
            group_size=registration.group_size,
            registration_status=registration.status.value,
            contact_hint=event.contact_hint,
        )

        subject, text_body, html_body = EmailTemplates.festival_cancelled(ctx)

        return await self._send_email(
            event_id=event.id,
            registration_id=registration.id,
            to=registration.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            message_type=MessageType.FESTIVAL_CANCELLATION,
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
        registration_id: UUID | None,
        to: str,
        subject: str,
        text_body: str,
        html_body: str,
        message_type: MessageType,
        inline_images: list[InlineImageData] | None = None,
        list_unsubscribe: str | None = None,
    ) -> bool:
        """Queue an email for delivery.

        Stores the message in DynamoDB with QUEUED status. The queue worker
        (process_email_queue) picks it up and sends it with proper pacing
        to avoid triggering SMTP rate limits.

        Args:
            event_id: Event ID.
            registration_id: Registration ID (None for pre-registration
                sends, e.g. the festival invitation F1).
            to: Recipient email.
            subject: Email subject.
            text_body: Plain text body.
            html_body: HTML body.
            message_type: Type of message.
            inline_images: Optional Content-ID referenced images (e.g. QR
                codes) — base64 round-trips through the queue and is decoded
                back to bytes at actual SMTP send time.

        Returns:
            True if email was queued successfully.
        """
        # Auto-attach a List-Unsubscribe header for bulk-style mail (unless the
        # caller passed one explicitly).
        if list_unsubscribe is None and message_type in _BULK_UNSUBSCRIBE_TYPES:
            list_unsubscribe = _unsubscribe_mailto()

        message = Message(
            id=uuid4(),
            event_id=event_id,
            registration_id=registration_id,
            type=message_type,
            direction=MessageDirection.OUTBOUND,
            subject=subject,
            body=text_body,
            body_html=html_body,
            inline_images=inline_images or [],
            list_unsubscribe=list_unsubscribe,
            status=MessageStatus.QUEUED,
            retry_count=0,
            recipient_email=to,
        )

        try:
            await self._store_message(message)
            logger.info(
                "Email queued for delivery",
                extra={
                    "message_id": str(message.id),
                    "to": to,
                    "type": message_type.value,
                    "subject": subject,
                },
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to queue email",
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

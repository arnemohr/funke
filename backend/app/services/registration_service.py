"""Registration service for capacity/waitlist management and cancellation.

Provides:
- Registration submission with capacity checking
- Automatic waitlist assignment when capacity exceeded
- Cancellation token handling
- Waitlist promotion when spots open
- DynamoDB transactions for atomic capacity operations
"""

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models import (
    AccommodationType,
    Event,
    EventStatus,
    EventType,
    FestivalAttendancePatch,
    FestivalRegistrationCreate,
    Registration,
    RegistrationAdminPatch,
    RegistrationCreate,
    RegistrationStatus,
)
from .config import get_events_table, get_registrations_table
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _generate_registration_token() -> str:
    """Generate a unique token for cancellation/confirmation links."""
    return secrets.token_urlsafe(32)


def format_overnight_units(tent_count: int | None, camper_count: int | None) -> str:
    """Render tent/camper counts as German text, e.g. "2 Zelte, 1 Camper".

    Empty string when there is no overnight wish. "Zelt/Zelte" pluralizes;
    "Camper" is invariant. Shared shape with
    `email_service._build_accommodation_label` (Ä21).
    """
    parts: list[str] = []
    if tent_count:
        parts.append(f"{tent_count} {'Zelt' if tent_count == 1 else 'Zelte'}")
    if camper_count:
        parts.append(f"{camper_count} Camper")
    return ", ".join(parts)


def _gate_accommodation_label(registration: Registration) -> str:
    """Render the Schlafplatz column: Ä17 approval semantics.

    Same mapping as `{Schlafplatz}` in the F1-F4 email templates
    (`email_service._build_accommodation_label`): no wish -> "Nein";
    otherwise "<2 Zelte, 1 Camper> — angefragt" until an admin sets
    `overnight_approved`, then "... — zugesagt" (Ä21).
    """
    units = format_overnight_units(registration.tent_count, registration.camper_count)
    if not units:
        return "Nein"
    status = "zugesagt" if registration.overnight_approved else "angefragt"
    return f"{units} — {status}"


def build_gate_rows(registrations: list[Registration], event: Event) -> list[dict]:
    """Build one printable gate-list row per person (Ä9 CSV export floor).

    Pure and HTTP-free so it is directly unit-testable (T113). Excludes
    CANCELLED registrations (Ä5) and expands each surviving registration
    into one row per person: the contact plus every `group_members` entry
    (`None` entries are tombstones for removed members and yield no row —
    person_index stability, spec 019 §Registration index stability).

    Rows are sorted alphabetically by person name (`str.casefold`, locale-
    naive — fine for a printed list). Slot columns are informational only;
    slots are never checked at the gate (Ä13). This list is reprinted every
    festival evening (Ä14) — callers must always pass the live registration
    list, never a cached one.
    """
    slot_labels = [slot.label for slot in (event.festival_slots or [])]
    slot_keys = [slot.key for slot in (event.festival_slots or [])]

    rows: list[dict] = []
    for registration in registrations:
        if registration.status == RegistrationStatus.CANCELLED:
            continue

        kontingent = registration.invite_label or ""
        tier = registration.tier or ""
        schlafplatz = _gate_accommodation_label(registration)
        telefon = registration.phone or "" if registration.has_overnight else ""
        chosen_slots = set(registration.attendance_slots or [])
        slot_values = {label: ("x" if key in chosen_slots else "") for key, label in zip(slot_keys, slot_labels)}

        person_names = [registration.name, *(registration.group_members or [])]
        for person_name in person_names:
            if person_name is None:
                continue
            row = {
                "Name": person_name,
                "Kontaktperson": registration.name,
                "Kontingent": kontingent,
                "Tier": tier,
                "Schlafplatz": schlafplatz,
                "Telefon": telefon,
                **slot_values,
                "Angekommen": "",
                "Bändchen": "",
            }
            rows.append(row)

    rows.sort(key=lambda row: row["Name"].casefold())
    return rows


VERY_FULL_THRESHOLD = 0.9  # Ä4: public "very_full" soft-warning threshold — 90% of a slot's effective cap


def compute_very_full_slots(headcount: dict) -> dict[str, bool]:
    """Ä4 (if-time): per-slot "very_full" booleans from a `get_headcount` (T201) result.

    Pure and headcount-driven, mirroring `build_gate_rows`' shape — no
    separate event lookup needed since `headcount["slots"][i]["cap"]` and
    `headcount["overall_cap"]` already carry everything required. Effective
    cap is the slot's own `cap`, falling back to `overall_cap` (the event
    capacity) when the slot has none; **never true when neither cap
    exists** — a missing cap must never manufacture a false "nearly full"
    warning. Returns booleans only — counts/caps/percentages stay
    admin-only (the public invite-boot payload exposes just this dict's
    values, never the numbers behind them).
    """
    overall_cap = headcount["overall_cap"]
    result: dict[str, bool] = {}
    for slot in headcount["slots"]:
        effective_cap = slot["cap"] if slot["cap"] is not None else overall_cap
        result[slot["key"]] = effective_cap is not None and slot["total"] >= VERY_FULL_THRESHOLD * effective_cap
    return result


def _registration_to_item(registration: Registration) -> dict:
    """Convert Registration model to DynamoDB item."""
    item = {
        "pk": f"EVENT#{registration.event_id}",
        "sk": f"REG#{registration.id}",
        "id": str(registration.id),
        "event_id": str(registration.event_id),
        "name": registration.name,
        "email": registration.email,
        "group_size": registration.group_size,
        "status": registration.status.value,
        "registration_token": registration.registration_token,
        "registered_at": registration.registered_at.isoformat(),
        "promoted_from_waitlist": registration.promoted_from_waitlist,
        "promoted": registration.promoted,
        "entity_type": "Registration",
        # GSI fields are already included: event_id, email, registration_token
        # Written unconditionally (Ä17 — the flag must be legible without the
        # attribute existing yet on legacy items, which parse as False).
        "overnight_approved": registration.overnight_approved,
    }

    # Optional fields
    if registration.phone:
        item["phone"] = registration.phone

    if registration.notes:
        item["notes"] = registration.notes

    if registration.waitlist_position is not None:
        item["waitlist_position"] = registration.waitlist_position

    if registration.responded_at:
        item["responded_at"] = registration.responded_at.isoformat()

    if registration.page_viewed_at:
        item["page_viewed_at"] = registration.page_viewed_at.isoformat()

    if registration.last_reminder_sent_at:
        item["last_reminder_sent_at"] = registration.last_reminder_sent_at.isoformat()

    if registration.group_members is not None:
        item["group_members"] = registration.group_members

    if registration.ttl:
        item["ttl"] = registration.ttl

    # Festival sidetrack (spec 019) — additive optional fields
    if registration.attendance_slots is not None:
        item["attendance_slots"] = registration.attendance_slots

    if registration.tent_count is not None:
        item["tent_count"] = registration.tent_count

    if registration.camper_count is not None:
        item["camper_count"] = registration.camper_count

    if registration.invite_id is not None:
        item["invite_id"] = str(registration.invite_id)

    if registration.invite_label:
        item["invite_label"] = registration.invite_label

    if registration.tier:
        item["tier"] = registration.tier

    return item


def _item_to_registration(item: dict) -> Registration:
    """Convert DynamoDB item to Registration model."""
    return Registration(
        id=UUID(item["id"]),
        event_id=UUID(item["event_id"]),
        name=item["name"],
        email=item["email"],
        phone=item.get("phone"),
        notes=item.get("notes"),
        group_size=item["group_size"],
        group_members=item.get("group_members"),
        status=RegistrationStatus(item["status"]),
        waitlist_position=item.get("waitlist_position"),
        registration_token=item["registration_token"],
        registered_at=datetime.fromisoformat(item["registered_at"]),
        responded_at=(
            datetime.fromisoformat(item["responded_at"])
            if item.get("responded_at")
            else None
        ),
        page_viewed_at=(
            datetime.fromisoformat(item["page_viewed_at"])
            if item.get("page_viewed_at")
            else None
        ),
        last_reminder_sent_at=(
            datetime.fromisoformat(item["last_reminder_sent_at"])
            if item.get("last_reminder_sent_at")
            else None
        ),
        promoted_from_waitlist=item.get("promoted_from_waitlist", False),
        promoted=item.get("promoted", False),
        ttl=item.get("ttl"),
        # Festival sidetrack (spec 019) — additive optional fields
        invite_id=UUID(item["invite_id"]) if item.get("invite_id") else None,
        invite_label=item.get("invite_label"),
        tier=item.get("tier"),
        attendance_slots=item.get("attendance_slots"),
        overnight_approved=item.get("overnight_approved", False),
        **_overnight_counts_from_item(item),
    )


def _overnight_counts_from_item(item: dict) -> dict:
    """Read tent/camper counts, mapping legacy pre-Ä21 rows (single
    `accommodation` + `accommodation_count`) into the new two-count shape."""
    if "tent_count" in item or "camper_count" in item:
        return {
            "tent_count": item.get("tent_count"),
            "camper_count": item.get("camper_count"),
        }
    # Legacy: a single TENT/CAMPER choice with an optional count (default 1).
    legacy = item.get("accommodation")
    if not legacy:
        return {"tent_count": None, "camper_count": None}
    count = item.get("accommodation_count") or 1
    if legacy == AccommodationType.TENT.value:
        return {"tent_count": count, "camper_count": None}
    return {"tent_count": None, "camper_count": count}


class RegistrationService:
    """Service for registration management operations."""

    def __init__(self):
        self._registrations_table = None
        self._events_table = None

    @property
    def registrations_table(self) -> "Table":
        """Get the registrations table (lazy initialization)."""
        if self._registrations_table is None:
            self._registrations_table = get_registrations_table()
        return self._registrations_table

    @property
    def events_table(self) -> "Table":
        """Get the events table (lazy initialization)."""
        if self._events_table is None:
            self._events_table = get_events_table()
        return self._events_table

    async def record_page_view(self, event_id: UUID, registration_id: UUID) -> None:
        """Record that the registrant opened their manage page."""
        now = datetime.now(UTC).isoformat()
        try:
            self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
                UpdateExpression="SET page_viewed_at = :ts",
                ExpressionAttributeValues={":ts": now},
            )
        except ClientError as e:
            logger.error(
                "Failed to record page view",
                extra={"registration_id": str(registration_id), "error": str(e)},
            )

    async def update_reminder_sent(
        self, event_id: UUID, registration_id: UUID, sent_at: datetime,
    ) -> None:
        """Record that a reminder was sent to prevent duplicate sends."""
        try:
            self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
                UpdateExpression="SET last_reminder_sent_at = :ts",
                ExpressionAttributeValues={":ts": sent_at.isoformat()},
            )
        except ClientError as e:
            logger.error(
                "Failed to update reminder sent timestamp",
                extra={"registration_id": str(registration_id), "error": str(e)},
            )

    async def _get_event_by_link_token(self, link_token: str) -> Event | None:
        """Get event by public link token."""
        try:
            from .event_service import _item_to_event

            response = self.events_table.query(
                IndexName="link-token-index",
                KeyConditionExpression="registration_link_token = :token",
                ExpressionAttributeValues={":token": link_token},
            )
            items = response.get("Items", [])
            if not items:
                return None
            return _item_to_event(items[0])
        except ClientError as e:
            logger.error("Failed to get event by link token", extra={"error": str(e)})
            return None

    async def _get_active_spots_count(self, event_id: UUID) -> int:
        """Get total active spots (REGISTERED + CONFIRMED + PARTICIPATING).

        These are the spots that count against capacity. WAITLISTED and
        CANCELLED registrations do not occupy capacity.
        """
        try:
            active_statuses = {
                RegistrationStatus.REGISTERED.value,
                RegistrationStatus.CONFIRMED.value,
                RegistrationStatus.PARTICIPATING.value,
            }
            response = self.registrations_table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#"),
                ProjectionExpression="group_size, #status",
                ExpressionAttributeNames={"#status": "status"},
            )

            items = response.get("Items", [])
            while "LastEvaluatedKey" in response:
                response = self.registrations_table.query(
                    KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#"),
                    ProjectionExpression="group_size, #status",
                    ExpressionAttributeNames={"#status": "status"},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            return sum(
                item.get("group_size", 1)
                for item in items
                if item.get("status") in active_statuses
            )

        except ClientError as e:
            logger.error("Failed to get active spots count", extra={"error": str(e)})
            return 0

    async def _get_max_waitlist_position(self, event_id: UUID) -> int:
        """Get the maximum waitlist position for an event."""
        try:
            response = self.registrations_table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#"),
                FilterExpression="#status = :waitlisted",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":waitlisted": RegistrationStatus.WAITLISTED.value},
                ProjectionExpression="waitlist_position",
            )

            items = response.get("Items", [])
            if not items:
                return 0

            return max(item.get("waitlist_position", 0) for item in items)

        except ClientError as e:
            logger.error("Failed to get max waitlist position", extra={"error": str(e)})
            return 0

    async def _check_duplicate_email(self, event_id: UUID, email: str) -> bool:
        """Check if email is already registered for this event."""
        try:
            response = self.registrations_table.query(
                IndexName="email-index",
                KeyConditionExpression="event_id = :event_id AND email = :email",
                ExpressionAttributeValues={
                    ":event_id": str(event_id),
                    ":email": email.lower(),
                    ":cancelled": RegistrationStatus.CANCELLED.value,
                },
                FilterExpression="#status <> :cancelled",
                ExpressionAttributeNames={"#status": "status"},
            )
            return len(response.get("Items", [])) > 0

        except ClientError as e:
            logger.error("Failed to check duplicate email", extra={"error": str(e)})
            return False

    async def create_registration(
        self,
        link_token: str,
        registration_data: RegistrationCreate,
    ) -> tuple[Registration | None, str | None]:
        """Create a new registration for an event.

        - During open registration: status = REGISTERED (lottery eligible)
        - After lottery (CONFIRMED/LOTTERY_PENDING): status = WAITLISTED (late signup)
        - COMPLETED/CANCELLED/DRAFT: rejected

        Args:
            link_token: Public registration link token.
            registration_data: Registration form data.

        Returns:
            Tuple of (Registration, None) on success, or (None, error_message) on failure.
        """
        # Get the event by link token
        event = await self._get_event_by_link_token(link_token)
        if not event:
            return None, "Event not found"

        # Festivals never use this legacy path (spec 019 §T110) — dead by
        # construction (festivals have no registration_link_token), guarded
        # explicitly anyway.
        if event.event_type == EventType.FESTIVAL:
            return None, "Registration is not open for this event"

        # Determine registration mode based on event status
        accepting_statuses = {
            EventStatus.OPEN,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.LOTTERY_PENDING,
            EventStatus.CONFIRMED,
        }
        if event.status not in accepting_statuses:
            return None, "Registration is not open for this event"

        # During open registration, check deadline
        is_late_signup = event.status != EventStatus.OPEN
        if not is_late_signup:
            if datetime.now(UTC) >= event.registration_deadline.replace(tzinfo=UTC):
                return None, "Registration deadline has passed"

        # Normalize email
        email = registration_data.email.lower().strip()

        # Check for duplicate email
        if await self._check_duplicate_email(event.id, email):
            return None, "Email already registered for this event"

        # Validate group size
        if registration_data.group_size > 5:
            return None, "Group size cannot exceed 5"

        if (
            registration_data.group_members is not None
            and len(registration_data.group_members) > registration_data.group_size
        ):
            return None, "group_members cannot exceed group_size"

        # Late signups go straight to waitlist
        if is_late_signup:
            max_pos = await self._get_max_waitlist_position(event.id)
            initial_status = RegistrationStatus.WAITLISTED
            waitlist_position = max_pos + 1
        else:
            initial_status = RegistrationStatus.REGISTERED
            waitlist_position = None

        registration = Registration(
            id=uuid4(),
            event_id=event.id,
            name=registration_data.name,
            email=email,
            phone=registration_data.phone,
            notes=registration_data.notes,
            group_size=registration_data.group_size,
            group_members=registration_data.group_members,
            status=initial_status,
            waitlist_position=waitlist_position,
            registration_token=_generate_registration_token(),
            registered_at=datetime.now(UTC),
        )

        item = _registration_to_item(registration)

        try:
            # Use conditional write to prevent race conditions
            self.registrations_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )

            logger.info(
                "Registration created",
                extra={
                    "registration_id": str(registration.id),
                    "event_id": str(event.id),
                    "email": email,
                    "status": RegistrationStatus.REGISTERED.value,
                    "group_size": registration_data.group_size,
                },
            )

            return registration, None

        except ClientError as e:
            logger.error(
                "Failed to create registration",
                extra={"error": str(e), "event_id": str(event.id)},
            )
            return None, "Failed to create registration"

    async def create_festival_registration(
        self,
        invite_token: str,
        data: FestivalRegistrationCreate,
    ) -> tuple[Registration | None, str | None]:
        """Create a festival registration by redeeming an invite (spec 019 §T108).

        Same tuple contract as ``create_registration``. Registrations are
        created directly in status PARTICIPATING with
        ``responded_at == registered_at`` — never CONFIRMED (spec "Critical
        semantic decision"; CONFIRMED feeds the nag-reminder worker and the
        discard-unacknowledged flow, neither of which apply to festivals).
        There is no waitlist branch and slot caps are never enforced here
        (soft only, Ä8/Ä4).

        Validation chain (spec §Data model deltas), in order:
        invite lookup -> revoked -> event lookup -> FESTIVAL+OPEN -> deadline
        -> invite expiry -> group cap -> slot subset -> phone required
        -> duplicate email -> atomic consume -> build + conditional put
        (release the use on put failure) -> touch_last_registered -> send F2
        (never-fail).

        Args:
            invite_token: The invite's public redemption token.
            data: Festival registration form data.

        Returns:
            Tuple of (Registration, None) on success, or (None, error) on
            failure. Error strings are router-mappable (T111): they contain
            one of "not found", "revoked", "expired", "exhausted",
            "deadline", "not open", "already registered", or are plain
            messages otherwise.
        """
        from .event_service import get_event_service
        from .invite_service import get_invite_service

        invite_service = get_invite_service()
        invite = await invite_service.get_invite_by_token(invite_token)
        if not invite:
            return None, "Invite not found"
        if invite.revoked_at is not None:
            return None, "Invite revoked"

        event_service = get_event_service()
        event = await event_service.get_event(invite.org_id, invite.event_id)
        if not event:
            return None, "Event not found"

        if event.event_type != EventType.FESTIVAL or event.status != EventStatus.OPEN:
            return None, "Registration is not open for this event"

        deadline = event.registration_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if datetime.now(UTC) >= deadline:
            return None, "Registration deadline has passed"

        if invite.is_expired(event.registration_deadline):
            return None, "Invite has expired"

        if data.group_size > invite.max_group_size:
            return (
                None,
                f"Group size cannot exceed the invite's allowance of {invite.max_group_size}",
            )

        # group_members is EXCLUSIVE of the contact person (spec §QR payload:
        # person_index 0 = contact, 1.. = group_members). Fail loudly when a
        # client sends an inconsistent pair instead of storing garbage rows.
        if (
            data.group_members is not None
            and len(data.group_members) != data.group_size - 1
        ):
            return None, "group_members must list exactly group_size - 1 companions"

        if not data.attendance_slots or not set(data.attendance_slots).issubset(
            set(event.slot_keys()),
        ):
            return None, "Unknown attendance slot selected"

        # Overnight (Ä15/Ä21): tent/camper counts are optional and independent
        # of the chosen slots — is_night no longer gates anything. Phone is
        # required for every registration regardless of overnight; the schema
        # already enforces this, re-checked here as defense in depth.
        phone = data.phone
        if not phone or not phone.strip():
            return None, "Phone number is required"

        email = data.email.lower().strip()
        if await self._check_duplicate_email(event.id, email):
            return None, "Email already registered for this event"

        # Atomic consume — AFTER all other validations, so a rejected
        # registration never touches the invite's use_count.
        consumed = await invite_service.consume_use(event.id, invite.id)
        if not consumed:
            return None, "Invite exhausted (Kontingent aufgebraucht)"

        registered_at = datetime.now(UTC)
        registration = Registration(
            id=uuid4(),
            event_id=event.id,
            name=data.name,
            email=email,
            phone=phone,
            notes=data.notes,
            group_size=data.group_size,
            group_members=data.group_members,
            status=RegistrationStatus.PARTICIPATING,
            registration_token=_generate_registration_token(),
            registered_at=registered_at,
            responded_at=registered_at,
            invite_id=invite.id,
            invite_label=invite.label,
            tier=invite.tier,
            attendance_slots=data.attendance_slots,
            tent_count=data.tent_count,
            camper_count=data.camper_count,
        )

        item = _registration_to_item(registration)

        try:
            self.registrations_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )
        except ClientError as e:
            logger.error(
                "Failed to create festival registration",
                extra={
                    "flow": "festival", "step": "register_persist", "outcome": "error",
                    "error": str(e), "event_id": str(event.id), "invite_id": str(invite.id),
                },
            )
            # Undo the consume — the registration never made it to storage.
            await invite_service.release_use(event.id, invite.id)
            return None, "Failed to create registration"

        logger.info(
            "Festival registration created",
            extra={
                "flow": "festival",
                "step": "register_persist",
                "outcome": "ok",
                "registration_id": str(registration.id),
                "event_id": str(event.id),
                "invite_id": str(invite.id),
                "status": RegistrationStatus.PARTICIPATING.value,
            },
        )

        await invite_service.touch_last_registered(event.id, invite.id)

        # Send F2, never fail the registration on email trouble.
        try:
            from .email_service import get_email_service

            email_service = get_email_service()
            await email_service.send_festival_confirmation(event, registration)
        except Exception as e:
            logger.error(
                "Failed to send festival confirmation email",
                extra={
                    "flow": "festival", "step": "confirmation_email", "outcome": "error",
                    "error": str(e), "registration_id": str(registration.id),
                    "event_id": str(event.id),
                },
            )

        return registration, None

    async def get_registration(
        self,
        event_id: UUID,
        registration_id: UUID,
    ) -> Registration | None:
        """Get a registration by ID.

        Args:
            event_id: Event ID.
            registration_id: Registration ID.

        Returns:
            Registration if found, None otherwise.
        """
        try:
            response = self.registrations_table.get_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
            )
            item = response.get("Item")
            return _item_to_registration(item) if item else None

        except ClientError as e:
            logger.error(
                "Failed to get registration",
                extra={"error": str(e), "registration_id": str(registration_id)},
            )
            return None

    async def delete_registration(
        self,
        event_id: UUID,
        registration_id: UUID,
    ) -> Registration | None:
        """Delete a registration permanently.

        Args:
            event_id: Event ID.
            registration_id: Registration ID.

        Returns:
            The deleted Registration if found, None otherwise.
        """
        registration = await self.get_registration(event_id, registration_id)
        if not registration:
            return None

        try:
            self.registrations_table.delete_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
            )
            logger.info(
                "Registration deleted",
                extra={
                    "event_id": str(event_id),
                    "registration_id": str(registration_id),
                    "name": registration.name,
                },
            )
            return registration
        except ClientError as e:
            logger.error(
                "Failed to delete registration",
                extra={"error": str(e), "registration_id": str(registration_id)},
            )
            return None

    async def get_registration_by_token(self, token: str) -> Registration | None:
        """Get a registration by its cancellation/confirmation token.

        Args:
            token: The registration token.

        Returns:
            Registration if found, None otherwise.
        """
        try:
            response = self.registrations_table.query(
                IndexName="token-index",
                KeyConditionExpression="registration_token = :token",
                ExpressionAttributeValues={":token": token},
            )
            items = response.get("Items", [])
            if not items:
                return None
            return _item_to_registration(items[0])

        except ClientError as e:
            logger.error(
                "Failed to get registration by token",
                extra={"error": str(e)},
            )
            return None

    async def list_registrations(
        self,
        event_id: UUID,
        status_filter: RegistrationStatus | None = None,
        search: str | None = None,
    ) -> list[Registration]:
        """List registrations for an event.

        Args:
            event_id: Event ID.
            status_filter: Optional status filter.
            search: Optional search term (name or email).

        Returns:
            List of registrations.
        """
        try:
            query_kwargs = {
                "KeyConditionExpression": Key("pk").eq(f"EVENT#{event_id}") & Key("sk").begins_with("REG#"),
            }

            filter_expressions = []
            expression_attribute_names = {}
            expression_attribute_values = {}

            if status_filter:
                filter_expressions.append("#status = :status")
                expression_attribute_names["#status"] = "status"
                expression_attribute_values[":status"] = status_filter.value

            if search:
                search_lower = search.lower()
                filter_expressions.append("(contains(#name_lower, :search) OR contains(email, :search))")
                expression_attribute_names["#name_lower"] = "name"
                expression_attribute_values[":search"] = search_lower

            if filter_expressions:
                query_kwargs["FilterExpression"] = " AND ".join(filter_expressions)
                query_kwargs["ExpressionAttributeNames"] = expression_attribute_names
                query_kwargs["ExpressionAttributeValues"] = expression_attribute_values

            response = self.registrations_table.query(**query_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.registrations_table.query(**query_kwargs)
                items.extend(response.get("Items", []))

            return [_item_to_registration(item) for item in items]

        except ClientError as e:
            logger.error(
                "Failed to list registrations",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return []

    async def update_festival_attendance(
        self,
        registration_id: UUID,
        token: str,
        patch: FestivalAttendancePatch,
    ) -> tuple[Registration | None, str | None]:
        """Self-service edit of a festival registration's attendance (spec 019 §T109).

        Re-runs the T108 validations against the patched values and enforces
        the invite grandfathering rule and the append-only/tombstone rule
        for `group_members`. Sends F3 (never-fail) on success.

        Returns:
            Tuple of (updated Registration, None) on success, or
            (None, error) on failure. The "deadline" error covers both the
            event-status and the past-deadline branch of the lifecycle
            gate (spec matrix) — the manage page then shows `contact_hint`.
        """
        from .email_service import get_email_service
        from .event_service import get_event_service
        from .invite_service import get_invite_service

        registration = await self.get_registration_by_token(token)
        if not registration:
            return None, "Registration not found"
        if registration.id != registration_id:
            return None, "Invalid token for this registration"
        if registration.status == RegistrationStatus.CANCELLED:
            return None, "Cannot edit a cancelled registration"

        event_service = get_event_service()
        event = await event_service.get_event_by_id(registration.event_id)
        if not event or event.event_type != EventType.FESTIVAL:
            return None, "Not a festival registration"

        # Lifecycle gate (spec matrix): status ∈ {OPEN, REGISTRATION_CLOSED,
        # CONFIRMED} AND before the deadline — combined into a single
        # "deadline" error either way.
        accepting_statuses = {
            EventStatus.OPEN,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.CONFIRMED,
        }
        deadline = event.registration_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if event.status not in accepting_statuses or datetime.now(UTC) >= deadline:
            return None, "Editing deadline has passed"

        updates = patch.model_dump(exclude_unset=True)
        if not updates:
            return registration, None

        # Slots (re-run T108's subset/non-empty check).
        target_slots = updates.get("attendance_slots", registration.attendance_slots)
        if "attendance_slots" in updates:
            if not target_slots:
                return None, "At least one attendance slot is required"
            if not set(target_slots).issubset(set(event.slot_keys())):
                return None, "Unknown attendance slot selected"

        # Phone is required for every festival registration, independent of
        # overnight. Ä17 approval resets when the whole wish is cleared.
        target_phone = updates.get("phone", registration.phone)
        overnight_approved = registration.overnight_approved

        if not target_phone or not target_phone.strip():
            return None, "Phone number is required"

        # Grandfathering (spec §Invite): a group may grow to
        # max(current group_size, invite.max_group_size) — reducing the
        # invite's allowance never invalidates an existing registration.
        invite = None
        if registration.invite_id is not None:
            invite_service = get_invite_service()
            invite = await invite_service.get_invite(event.id, registration.invite_id)
        allowed_max_group_size = max(
            registration.group_size,
            invite.max_group_size if invite else registration.group_size,
        )

        # group_members: APPEND-ONLY with tombstones (spec §Registration
        # index stability) — a shorter list would reindex, which is
        # forbidden; removal must replace an entry with None instead.
        target_group_members = updates.get("group_members", registration.group_members)
        if "group_members" in updates:
            old_members = registration.group_members or []
            new_members = updates["group_members"] or []
            if len(new_members) < len(old_members):
                return (
                    None,
                    "group_members entries cannot be removed — use null to tombstone instead",
                )
            target_group_members = new_members

        non_none_count = sum(1 for m in (target_group_members or []) if m is not None)

        if "group_size" in updates:
            target_group_size = updates["group_size"]
        elif "group_members" in updates:
            # group_size counts contact + non-None members only.
            target_group_size = 1 + non_none_count
        else:
            target_group_size = registration.group_size

        if target_group_size > allowed_max_group_size:
            return None, f"Group size cannot exceed {allowed_max_group_size}"
        if non_none_count > target_group_size - 1:
            return None, "group_members exceeds group_size"

        # Overnight counts (Ä21): 0 normalizes to None; neither may exceed the
        # resulting group size. Clearing the whole wish (both None) resets the
        # Ä17 approval flag.
        target_tent = updates.get("tent_count", registration.tent_count)
        target_camper = updates.get("camper_count", registration.camper_count)
        target_tent = target_tent or None
        target_camper = target_camper or None
        if target_tent and target_tent > target_group_size:
            return None, "tent_count_exceeds_group"
        if target_camper and target_camper > target_group_size:
            return None, "camper_count_exceeds_group"
        if not target_tent and not target_camper and registration.has_overnight:
            overnight_approved = False

        updated = registration.model_copy(
            update={
                "attendance_slots": target_slots,
                "tent_count": target_tent,
                "camper_count": target_camper,
                "phone": target_phone,
                "overnight_approved": overnight_approved,
                "group_size": target_group_size,
                "group_members": target_group_members,
            },
        )

        try:
            self.registrations_table.put_item(Item=_registration_to_item(updated))
        except ClientError as e:
            logger.error(
                "Failed to update festival attendance",
                extra={
                    "flow": "festival", "step": "edit_persist", "outcome": "error",
                    "error": str(e), "registration_id": str(registration_id),
                    "event_id": str(registration.event_id),
                },
            )
            return None, "Failed to update festival attendance"

        logger.info(
            "Festival attendance updated",
            extra={
                "flow": "festival",
                "step": "edit_persist",
                "outcome": "ok",
                "registration_id": str(registration_id),
                "event_id": str(registration.event_id),
            },
        )

        try:
            email_service = get_email_service()
            await email_service.send_festival_update_confirmation(event, updated)
        except Exception as e:
            logger.error(
                "Failed to send festival update confirmation email",
                extra={
                    "flow": "festival", "step": "update_email", "outcome": "error",
                    "error": str(e), "registration_id": str(registration_id),
                    "event_id": str(registration.event_id),
                },
            )

        return updated, None

    async def cancel_registration(
        self,
        registration_id: UUID,
        token: str,
    ) -> tuple[Registration | None, str | None]:
        """Cancel a registration using its token.

        Args:
            registration_id: Registration ID.
            token: Cancellation token.

        Returns:
            Tuple of (cancelled Registration, None) on success, or (None, error_message) on failure.
        """
        # Get registration by token
        registration = await self.get_registration_by_token(token)
        if not registration:
            return None, "Registration not found"

        # Verify registration ID matches
        if registration.id != registration_id:
            return None, "Invalid token for this registration"

        # Check if can be cancelled
        if not registration.can_cancel():
            return None, f"Cannot cancel registration with status {registration.status.value}"

        held_spot = registration.status in (
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.PARTICIPATING,
        )
        group_size = registration.group_size

        try:
            # Update registration status
            response = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{registration.event_id}",
                    "sk": f"REG#{registration.id}",
                },
                UpdateExpression="SET #status = :cancelled",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":cancelled": RegistrationStatus.CANCELLED.value,
                    ":current_status": registration.status.value,
                },
                ConditionExpression="#status = :current_status",
                ReturnValues="ALL_NEW",
            )

            cancelled_registration = _item_to_registration(response["Attributes"])

            logger.info(
                "Registration cancelled",
                extra={
                    "registration_id": str(registration_id),
                    "event_id": str(registration.event_id),
                    "held_spot": held_spot,
                },
            )

            # Festival branch (spec 019 §T109): release the invite use, send
            # F4 from HERE (so every caller — public cancel, admin cancel —
            # gets it for free with exactly one send site), and never
            # promote from a waitlist that festivals don't have (explicit
            # guard — already inert via autopromote_waitlist=False, but
            # belt and braces).
            from .event_service import get_event_service

            event_service = get_event_service()
            event = await event_service.get_event_by_id(registration.event_id)
            is_festival = event is not None and event.event_type == EventType.FESTIVAL

            if is_festival:
                if cancelled_registration.invite_id is not None:
                    try:
                        from .invite_service import get_invite_service

                        invite_service = get_invite_service()
                        await invite_service.release_use(
                            registration.event_id, cancelled_registration.invite_id,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to release invite use on cancel",
                            extra={"error": str(e), "registration_id": str(registration_id)},
                        )

                try:
                    from .email_service import get_email_service

                    email_service = get_email_service()
                    await email_service.send_festival_cancellation(event, cancelled_registration)
                except Exception as e:
                    logger.error(
                        "Failed to send festival cancellation email",
                        extra={"error": str(e), "registration_id": str(registration_id)},
                    )
            elif held_spot:
                # If held a spot (CONFIRMED or PARTICIPATING), trigger waitlist promotion.
                await self._promote_from_waitlist(registration.event_id, group_size)

            return cancelled_registration, None

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None, "Registration status has changed"
            logger.error("Failed to cancel registration", extra={"error": str(e)})
            return None, "Failed to cancel registration"

    async def _promote_from_waitlist(
        self,
        event_id: UUID,
        available_spots: int,
    ) -> list[Registration]:
        """Promote registrations from waitlist to fill available spots.

        Args:
            event_id: Event ID.
            available_spots: Number of spots that became available.

        Returns:
            List of promoted registrations.
        """
        from .email_service import get_email_service
        from .event_service import get_event_service

        # Get event to check autopromote setting
        event_service = get_event_service()
        event = await event_service.get_event_by_id(event_id)

        # Festivals never autopromote (spec 019 §T110) — already inert via
        # autopromote_waitlist=False from T103, but guarded explicitly here
        # too (belt and braces / defense in depth).
        if not event or event.event_type == EventType.FESTIVAL or not event.autopromote_waitlist:
            return []

        # Get waitlisted registrations ordered by position
        waitlisted = await self.list_registrations(
            event_id,
            status_filter=RegistrationStatus.WAITLISTED,
        )
        waitlisted.sort(key=lambda r: r.waitlist_position or 0)

        promoted = []
        remaining_spots = available_spots

        for registration in waitlisted:
            if remaining_spots <= 0:
                break

            # Only promote if entire group fits
            if registration.group_size <= remaining_spots:
                try:
                    response = self.registrations_table.update_item(
                        Key={
                            "pk": f"EVENT#{event_id}",
                            "sk": f"REG#{registration.id}",
                        },
                        UpdateExpression=(
                            "SET #status = :confirmed, "
                            "waitlist_position = :null, "
                            "promoted_from_waitlist = :true"
                        ),
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":confirmed": RegistrationStatus.CONFIRMED.value,
                            ":null": None,
                            ":true": True,
                            ":waitlisted": RegistrationStatus.WAITLISTED.value,
                        },
                        ConditionExpression="#status = :waitlisted",
                        ReturnValues="ALL_NEW",
                    )

                    promoted_reg = _item_to_registration(response["Attributes"])
                    promoted.append(promoted_reg)
                    remaining_spots -= registration.group_size

                    logger.info(
                        "Registration promoted from waitlist",
                        extra={
                            "registration_id": str(registration.id),
                            "event_id": str(event_id),
                        },
                    )

                    # Send promotion notification email
                    try:
                        email_service = get_email_service()
                        await email_service.send_promotion_notification(event, promoted_reg)
                    except Exception as e:
                        logger.error(
                            "Failed to send promotion email",
                            extra={"error": str(e), "registration_id": str(registration.id)},
                        )

                except ClientError:
                    continue  # Skip if update fails

        # Recompute waitlist positions for remaining waitlisted
        if promoted:
            await self._recompute_waitlist_positions(event_id)

        return promoted

    async def _recompute_waitlist_positions(self, event_id: UUID) -> None:
        """Recompute waitlist positions after promotions.

        Args:
            event_id: Event ID.
        """
        waitlisted = await self.list_registrations(
            event_id,
            status_filter=RegistrationStatus.WAITLISTED,
        )
        waitlisted.sort(key=lambda r: r.waitlist_position or 0)

        for i, registration in enumerate(waitlisted, start=1):
            if registration.waitlist_position != i:
                try:
                    self.registrations_table.update_item(
                        Key={
                            "pk": f"EVENT#{event_id}",
                            "sk": f"REG#{registration.id}",
                        },
                        UpdateExpression="SET waitlist_position = :pos",
                        ExpressionAttributeValues={":pos": i},
                    )
                except ClientError:
                    continue

    async def get_registration_stats(self, event_id: UUID) -> dict:
        """Get registration statistics for an event.

        Args:
            event_id: Event ID.

        Returns:
            Statistics dictionary.
        """
        registrations = await self.list_registrations(event_id)

        registered_count = 0
        registered_spots = 0
        confirmed_count = 0
        confirmed_spots = 0
        participating_count = 0
        participating_spots = 0
        waitlist_count = 0
        waitlist_spots = 0
        cancelled_count = 0
        checked_in_count = 0
        promoted_count = 0
        promoted_spots = 0

        for reg in registrations:
            if reg.status == RegistrationStatus.REGISTERED:
                registered_count += 1
                registered_spots += reg.group_size
            elif reg.status == RegistrationStatus.CONFIRMED:
                confirmed_count += 1
                confirmed_spots += reg.group_size
            elif reg.status == RegistrationStatus.PARTICIPATING:
                participating_count += 1
                participating_spots += reg.group_size
            elif reg.status == RegistrationStatus.WAITLISTED:
                waitlist_count += 1
                waitlist_spots += reg.group_size
            elif reg.status == RegistrationStatus.CANCELLED:
                cancelled_count += 1
            elif reg.status == RegistrationStatus.CHECKED_IN:
                checked_in_count += 1

            # Count promoted registrations (excluding cancelled)
            if reg.promoted and reg.status != RegistrationStatus.CANCELLED:
                promoted_count += 1
                promoted_spots += reg.group_size

        # confirmed_spots includes CONFIRMED + PARTICIPATING + CHECKED_IN for capacity display
        total_confirmed_spots = confirmed_spots + participating_spots

        # Total active registrations (all signups excluding cancelled)
        total_registrations = registered_count + confirmed_count + participating_count + waitlist_count + checked_in_count
        total_registration_spots = registered_spots + confirmed_spots + participating_spots + waitlist_spots

        return {
            "event_id": str(event_id),
            "registered_count": registered_count,
            "registered_spots": registered_spots,
            "confirmed_registrations": confirmed_count,
            "confirmed_spots": total_confirmed_spots,  # For backward compatibility
            "participating_count": participating_count,
            "participating_spots": participating_spots,
            "waitlist_registrations": waitlist_count,
            "waitlist_spots": waitlist_spots,
            "cancelled_count": cancelled_count,
            "checked_in_count": checked_in_count,
            "total_registrations": total_registrations,
            "total_registration_spots": total_registration_spots,
            "promoted_count": promoted_count,
            "promoted_spots": promoted_spots,
        }

    async def get_headcount(self, event: Event) -> dict:
        """Aggregate festival attendance into a slot x tier headcount board.

        Modeled on `get_registration_stats` above: **one** `list_registrations`
        call, then a single in-Python aggregation loop — no per-slot queries.

        Ä5: CANCELLED registrations are excluded from every bucket. A
        registration contributes its full `group_size` to every slot key in
        `attendance_slots` (the grid is shared by the whole group — peak
        counting, not person-splitting). Keys not present in
        `event.festival_slots` (orphaned after a slot-config edit) are
        collected into `unknown_slots` instead of silently vanishing.
        Accommodation totals are OVERALL, not per slot (Ä15/Ä21). Each type
        (TENT/CAMPER) reports `requested_units`/`approved_units` = Σ of that
        type's count (the real Stellplatz demand); `approved_units` is the
        subset with `overnight_approved=True` (Ä17). A group may bring both
        types, so `overnight_people` (Σ group_size of regs with any wish,
        split requested/approved) counts humans separately. Per-slot
        `overnight` demand is Σ group_size of regs on that slot with any
        overnight wish, independent of `is_night` (Ä15).

        Soft-cap semantics (Ä4/Ä8): `overbooked` is a display flag only —
        this method never raises and blocks nothing.

        Args:
            event: The FESTIVAL event to aggregate.

        Returns:
            Headcount board dict — see spec 019 T201 for the exact shape.
        """
        registrations = await self.list_registrations(event.id)

        slots = event.festival_slots or []
        slot_totals: dict[str, int] = {slot.key: 0 for slot in slots}
        slot_by_tier: dict[str, dict[str, int]] = {slot.key: {} for slot in slots}
        slot_overnight: dict[str, int] = {slot.key: 0 for slot in slots}

        unknown_slots: dict[str, int] = {}
        # Per type: units = tents/campers themselves (the real Stellplatz
        # demand); `*_units` requested vs. approved (Ä17/Ä21). A group may
        # bring both types, so people are counted once in `overnight_people`.
        accommodation_totals: dict[str, dict[str, int]] = {
            accommodation.value: {"requested_units": 0, "approved_units": 0}
            for accommodation in AccommodationType
        }
        overnight_people = {"requested": 0, "approved": 0}
        total_registrations = 0
        total_people = 0
        registrations_without_slots = 0

        for reg in registrations:
            if reg.status == RegistrationStatus.CANCELLED:
                continue

            total_registrations += 1
            total_people += reg.group_size

            tier = reg.tier or "unknown"

            if not reg.attendance_slots:
                registrations_without_slots += 1
            else:
                for key in reg.attendance_slots:
                    if key in slot_totals:
                        slot_totals[key] += reg.group_size
                        slot_by_tier[key][tier] = slot_by_tier[key].get(tier, 0) + reg.group_size
                        if reg.has_overnight:
                            slot_overnight[key] += reg.group_size
                    else:
                        unknown_slots[key] = unknown_slots.get(key, 0) + reg.group_size

            tent_bucket = accommodation_totals[AccommodationType.TENT.value]
            camper_bucket = accommodation_totals[AccommodationType.CAMPER.value]
            if reg.tent_count:
                tent_bucket["requested_units"] += reg.tent_count
                if reg.overnight_approved:
                    tent_bucket["approved_units"] += reg.tent_count
            if reg.camper_count:
                camper_bucket["requested_units"] += reg.camper_count
                if reg.overnight_approved:
                    camper_bucket["approved_units"] += reg.camper_count
            if reg.has_overnight:
                overnight_people["requested"] += reg.group_size
                if reg.overnight_approved:
                    overnight_people["approved"] += reg.group_size

        slot_rows = [
            {
                "key": slot.key,
                "label": slot.label,
                "date": slot.date.isoformat(),
                "is_night": slot.is_night,
                "total": slot_totals[slot.key],
                "by_tier": slot_by_tier[slot.key],
                "cap": slot.capacity,
                "overbooked": slot.capacity is not None and slot_totals[slot.key] > slot.capacity,
                "overnight": slot_overnight[slot.key],
            }
            for slot in slots
        ]

        peak_total = max((row["total"] for row in slot_rows), default=0)

        return {
            "slots": slot_rows,
            "peak_total": peak_total,
            "overall_cap": event.capacity,
            "overall_overbooked": peak_total > event.capacity,
            "accommodation_totals": accommodation_totals,
            "overnight_people": overnight_people,
            "total_registrations": total_registrations,
            "total_people": total_people,
            "registrations_without_slots": registrations_without_slots,
            "unknown_slots": unknown_slots,
        }

    async def set_attendance_response(
        self,
        registration_id: UUID,
        token: str,
        participating: bool,
    ) -> tuple[Registration | None, str | None]:
        """Set attendance response for a registration.

        Changes status from CONFIRMED to PARTICIPATING (yes) or CANCELLED (no).

        Args:
            registration_id: Registration ID.
            token: Registration token for verification.
            participating: True for YES, False for NO.

        Returns:
            Tuple of (updated Registration, None) on success, or (None, error_message) on failure.
        """
        # Get registration by token
        registration = await self.get_registration_by_token(token)
        if not registration:
            return None, "Registration not found"

        # Verify registration ID matches
        if registration.id != registration_id:
            return None, "Invalid token for this registration"

        # Only CONFIRMED registrations can respond to attendance requests
        if registration.status != RegistrationStatus.CONFIRMED:
            return None, f"Cannot respond with status {registration.status.value}"

        # Check if already responded (status is no longer CONFIRMED)
        if registration.responded_at is not None:
            return None, "Attendance response has already been recorded"

        group_size = registration.group_size
        new_status = RegistrationStatus.PARTICIPATING if participating else RegistrationStatus.CANCELLED

        try:
            # Update status and set responded_at
            response_data = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{registration.event_id}",
                    "sk": f"REG#{registration.id}",
                },
                UpdateExpression="SET #status = :new_status, responded_at = :responded_at",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": new_status.value,
                    ":responded_at": datetime.now(UTC).isoformat(),
                    ":confirmed": RegistrationStatus.CONFIRMED.value,
                },
                ConditionExpression="#status = :confirmed",
                ReturnValues="ALL_NEW",
            )
            updated_registration = _item_to_registration(response_data["Attributes"])

            logger.info(
                "Attendance response recorded",
                extra={
                    "registration_id": str(registration_id),
                    "event_id": str(registration.event_id),
                    "participating": participating,
                    "new_status": new_status.value,
                },
            )

            # Send attendance response confirmation email
            try:
                from .email_service import get_email_service
                from .event_service import get_event_service

                event_service = get_event_service()
                event = await event_service.get_event_by_id(registration.event_id)
                if event:
                    email_service = get_email_service()
                    await email_service.send_attendance_response_confirmation(
                        event, updated_registration, participating,
                    )
            except Exception as e:
                logger.error(
                    "Failed to send attendance response confirmation email",
                    extra={"error": str(e), "registration_id": str(registration_id)},
                )

            # If declined (cancelled), trigger waitlist promotion
            if not participating:
                await self._promote_from_waitlist(registration.event_id, group_size)

            return updated_registration, None

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None, "Attendance response has already been recorded"
            logger.error("Failed to set attendance response", extra={"error": str(e)})
            return None, "Failed to record attendance response"

    async def set_promoted(
        self,
        event_id: UUID,
        registration_id: UUID,
        promoted: bool,
    ) -> Registration | None:
        """Set the promoted flag on a registration.

        Only allowed for registrations in REGISTERED status.

        Args:
            event_id: Event ID.
            registration_id: Registration ID.
            promoted: Whether the registration is promoted.

        Returns:
            Updated registration, or None on failure.
        """
        try:
            response = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
                UpdateExpression="SET promoted = :promoted",
                ExpressionAttributeValues={
                    ":promoted": promoted,
                    ":registered": RegistrationStatus.REGISTERED.value,
                },
                ConditionExpression="#status = :registered",
                ExpressionAttributeNames={"#status": "status"},
                ReturnValues="ALL_NEW",
            )

            updated = _item_to_registration(response["Attributes"])
            logger.info(
                "Registration promoted flag updated",
                extra={
                    "registration_id": str(registration_id),
                    "event_id": str(event_id),
                    "promoted": promoted,
                },
            )
            return updated

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    "Cannot set promoted: registration not in REGISTERED status",
                    extra={"registration_id": str(registration_id)},
                )
                return None
            logger.error("Failed to set promoted flag", extra={"error": str(e)})
            return None

    async def promote_single_from_waitlist(
        self,
        event_id: UUID,
        registration_id: UUID,
        target_status: RegistrationStatus = RegistrationStatus.CONFIRMED,
    ) -> Registration | None:
        """Manually promote a single registration from the waitlist.

        Args:
            event_id: Event ID.
            registration_id: Registration ID.
            target_status: CONFIRMED (user must acknowledge) or PARTICIPATING (direct).

        Returns:
            Updated registration, or None on failure.
        """
        from .email_service import get_email_service
        from .event_service import get_event_service

        registration = await self.get_registration(event_id, registration_id)
        if not registration or registration.status != RegistrationStatus.WAITLISTED:
            return None

        update_expr = (
            "SET #status = :new_status, "
            "waitlist_position = :null, "
            "promoted_from_waitlist = :true"
        )
        expr_values: dict = {
            ":new_status": target_status.value,
            ":null": None,
            ":true": True,
            ":waitlisted": RegistrationStatus.WAITLISTED.value,
        }

        if target_status == RegistrationStatus.PARTICIPATING:
            update_expr += ", responded_at = :responded_at"
            expr_values[":responded_at"] = datetime.now(UTC).isoformat()

        try:
            response = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
                UpdateExpression=update_expr,
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=expr_values,
                ConditionExpression="#status = :waitlisted",
                ReturnValues="ALL_NEW",
            )

            promoted_reg = _item_to_registration(response["Attributes"])

            logger.info(
                "Registration manually promoted from waitlist",
                extra={
                    "registration_id": str(registration_id),
                    "event_id": str(event_id),
                    "target_status": target_status.value,
                },
            )

            # Send notification email
            try:
                event_service = get_event_service()
                event = await event_service.get_event_by_id(event_id)
                if event:
                    email_service = get_email_service()
                    if target_status == RegistrationStatus.CONFIRMED:
                        await email_service.send_promotion_notification(event, promoted_reg)
                    else:
                        # PARTICIPATING: send a simpler confirmation
                        await email_service.send_attendance_response_confirmation(
                            event, promoted_reg, participating=True,
                        )
            except Exception as e:
                logger.error(
                    "Failed to send manual promotion email",
                    extra={"error": str(e), "registration_id": str(registration_id)},
                )

            # Recompute waitlist positions
            await self._recompute_waitlist_positions(event_id)

            return promoted_reg

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            logger.error("Failed to promote from waitlist", extra={"error": str(e)})
            return None

    async def discard_unacknowledged(
        self,
        event_id: UUID,
        registration_ids: list[UUID] | None = None,
        reason: str | None = None,
        subject: str | None = None,
    ) -> tuple[int, int]:
        """Discard unacknowledged (CONFIRMED) registrations for an event.

        Transitions CONFIRMED registrations to CANCELLED and sends notification emails.
        Triggers waitlist promotion for freed spots.

        Args:
            event_id: Event ID.
            registration_ids: Optional list of specific registration IDs to discard.
                If None, all CONFIRMED registrations are discarded.
            reason: Optional custom message from admin for the cancellation email.
            subject: Optional custom email subject line.

        Returns:
            Tuple of (discarded_count, discarded_spots).
        """
        from .email_service import get_email_service
        from .event_service import get_event_service

        confirmed = await self.list_registrations(
            event_id, status_filter=RegistrationStatus.CONFIRMED,
        )

        if not confirmed:
            return 0, 0

        # Filter to specific IDs if provided
        if registration_ids is not None:
            id_set = set(registration_ids)
            confirmed = [r for r in confirmed if r.id in id_set]

        if not confirmed:
            return 0, 0

        event_service = get_event_service()
        event = await event_service.get_event_by_id(event_id)

        discarded_count = 0
        discarded_spots = 0

        for registration in confirmed:
            try:
                self.registrations_table.update_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"REG#{registration.id}",
                    },
                    UpdateExpression="SET #status = :cancelled",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":cancelled": RegistrationStatus.CANCELLED.value,
                        ":confirmed": RegistrationStatus.CONFIRMED.value,
                    },
                    ConditionExpression="#status = :confirmed",
                )
                discarded_count += 1
                discarded_spots += registration.group_size

                # Send cancellation email
                if event:
                    try:
                        email_service = get_email_service()
                        cancelled_reg = registration.model_copy(
                            update={"status": RegistrationStatus.CANCELLED},
                        )
                        await email_service.send_cancellation_confirmation(event, cancelled_reg, reason, subject)
                    except Exception as e:
                        logger.error(
                            "Failed to send discard email",
                            extra={"error": str(e), "registration_id": str(registration.id)},
                        )

            except ClientError as e:
                logger.error(
                    "Failed to discard registration",
                    extra={"registration_id": str(registration.id), "error": str(e)},
                )

        # Trigger waitlist promotion for freed spots
        if discarded_spots > 0:
            await self._promote_from_waitlist(event_id, discarded_spots)

        logger.info(
            "Discarded unacknowledged registrations",
            extra={
                "event_id": str(event_id),
                "discarded_count": discarded_count,
                "discarded_spots": discarded_spots,
            },
        )

        return discarded_count, discarded_spots

    async def cancel_all_registrations_for_event(self, event_id: UUID) -> int:
        """Cancel all non-cancelled registrations for an event.

        Used when an event is cancelled to transition all registrations to CANCELLED status.

        Args:
            event_id: Event ID.

        Returns:
            Number of registrations that were cancelled.
        """
        registrations = await self.list_registrations(event_id)
        cancelled_count = 0

        for registration in registrations:
            # Skip already-cancelled registrations
            if registration.status == RegistrationStatus.CANCELLED:
                continue

            try:
                self.registrations_table.update_item(
                    Key={
                        "pk": f"EVENT#{event_id}",
                        "sk": f"REG#{registration.id}",
                    },
                    UpdateExpression="SET #status = :cancelled",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":cancelled": RegistrationStatus.CANCELLED.value,
                    },
                )
                cancelled_count += 1
            except ClientError as e:
                logger.error(
                    "Failed to cancel registration for event cancellation",
                    extra={
                        "registration_id": str(registration.id),
                        "event_id": str(event_id),
                        "error": str(e),
                    },
                )

        logger.info(
            "Cancelled all registrations for event",
            extra={
                "event_id": str(event_id),
                "cancelled_count": cancelled_count,
            },
        )

        return cancelled_count

    async def confirm_with_names(
        self,
        registration_id: UUID,
        token: str,
        group_members: list[str],
    ) -> tuple[Registration | None, str | None]:
        """Confirm participation and store group member names.

        Transitions CONFIRMED → PARTICIPATING. The group may be reduced
        (fewer names than original group_size) but never increased.

        Args:
            registration_id: Registration ID.
            token: Registration token for verification.
            group_members: List of group member names (all non-empty).

        Returns:
            Tuple of (updated Registration, None) on success, or (None, error_message) on failure.
        """
        registration = await self.get_registration_by_token(token)
        if not registration:
            return None, "Registration not found"

        if registration.id != registration_id:
            return None, "Invalid token for this registration"

        if registration.status != RegistrationStatus.CONFIRMED:
            return None, f"Cannot confirm with status {registration.status.value}"

        # Validate group_members
        if not group_members or len(group_members) < 1:
            return None, "At least one group member name is required"

        if len(group_members) > registration.group_size:
            return None, f"Cannot exceed original group size of {registration.group_size}"

        # All names must be non-empty
        stripped = [name.strip() for name in group_members]
        if any(not name for name in stripped):
            return None, "All group member names must be non-empty"

        new_group_size = len(stripped)

        try:
            response_data = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{registration.event_id}",
                    "sk": f"REG#{registration.id}",
                },
                UpdateExpression=(
                    "SET #status = :new_status, "
                    "responded_at = :responded_at, "
                    "group_members = :group_members, "
                    "group_size = :group_size"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": RegistrationStatus.PARTICIPATING.value,
                    ":responded_at": datetime.now(UTC).isoformat(),
                    ":group_members": stripped,
                    ":group_size": new_group_size,
                    ":confirmed": RegistrationStatus.CONFIRMED.value,
                },
                ConditionExpression="#status = :confirmed",
                ReturnValues="ALL_NEW",
            )
            updated = _item_to_registration(response_data["Attributes"])

            logger.info(
                "Participation confirmed with group member names",
                extra={
                    "registration_id": str(registration_id),
                    "event_id": str(registration.event_id),
                    "group_size": new_group_size,
                    "original_group_size": registration.group_size,
                },
            )

            # Send attendance response confirmation email
            try:
                from .email_service import get_email_service
                from .event_service import get_event_service

                event_service = get_event_service()
                event = await event_service.get_event_by_id(registration.event_id)
                if event:
                    email_service = get_email_service()
                    await email_service.send_attendance_response_confirmation(
                        event, updated, participating=True,
                    )
            except Exception as e:
                logger.error(
                    "Failed to send confirmation email",
                    extra={"error": str(e), "registration_id": str(registration_id)},
                )

            return updated, None

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None, "Registration status has changed"
            logger.error("Failed to confirm with names", extra={"error": str(e)})
            return None, "Failed to confirm participation"

    async def update_group_members(
        self,
        registration_id: UUID,
        token: str,
        group_members: list[str],
    ) -> tuple[Registration | None, str | None]:
        """Update group member names for a PARTICIPATING registration.

        May also reduce group size if fewer names are provided.
        Does NOT trigger immediate waitlist promotion (batch job handles it).

        Args:
            registration_id: Registration ID.
            token: Registration token for verification.
            group_members: Updated list of group member names.

        Returns:
            Tuple of (updated Registration, None) on success, or (None, error_message) on failure.
        """
        registration = await self.get_registration_by_token(token)
        if not registration:
            return None, "Registration not found"

        if registration.id != registration_id:
            return None, "Invalid token for this registration"

        if registration.status != RegistrationStatus.PARTICIPATING:
            return None, f"Cannot update group members with status {registration.status.value}"

        # Validate
        if not group_members or len(group_members) < 1:
            return None, "At least one group member name is required"

        if len(group_members) > registration.group_size:
            return None, f"Cannot exceed current group size of {registration.group_size}"

        stripped = [name.strip() for name in group_members]
        if any(not name for name in stripped):
            return None, "All group member names must be non-empty"

        new_group_size = len(stripped)
        spots_freed = registration.group_size - new_group_size

        try:
            response_data = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{registration.event_id}",
                    "sk": f"REG#{registration.id}",
                },
                UpdateExpression=(
                    "SET group_members = :group_members, "
                    "group_size = :group_size"
                ),
                ExpressionAttributeValues={
                    ":group_members": stripped,
                    ":group_size": new_group_size,
                    ":participating": RegistrationStatus.PARTICIPATING.value,
                },
                ConditionExpression="#status = :participating",
                ExpressionAttributeNames={"#status": "status"},
                ReturnValues="ALL_NEW",
            )
            updated = _item_to_registration(response_data["Attributes"])

            if spots_freed > 0:
                logger.info(
                    "Group size reduced, spots freed for batch promotion",
                    extra={
                        "registration_id": str(registration_id),
                        "event_id": str(registration.event_id),
                        "spots_freed": spots_freed,
                        "new_group_size": new_group_size,
                    },
                )
                # Increment freed_spots on the event for batch promotion
                await self._increment_freed_spots(registration.event_id, spots_freed)
            else:
                logger.info(
                    "Group member names updated",
                    extra={
                        "registration_id": str(registration_id),
                        "event_id": str(registration.event_id),
                    },
                )

            return updated, None

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None, "Registration status has changed"
            logger.error("Failed to update group members", extra={"error": str(e)})
            return None, "Failed to update group members"

    async def admin_update_registration(
        self,
        event_id: UUID,
        registration_id: UUID,
        patch: RegistrationAdminPatch,
    ) -> tuple[Registration | None, str | None]:
        """Admin: partial update of a single registration (spec 018 + 019 T205).

        Returns ``(registration, None)`` on success, ``(None, error_code)`` otherwise.
        Error codes: ``not_found``, ``frozen_registration``, ``frozen_event``,
        ``invalid_group_size``, ``invalid_group_members``, ``conflict``,
        ``update_failed``, and (festival-only, T205) ``not_festival_event``,
        ``invalid_slots``, ``phone_required_for_accommodation``,
        ``overnight_approval_requires_accommodation``.

        Capacity is intentionally local: this method does NOT increment
        ``freed_spots`` or trigger waitlist promotion (see spec § Capacity behaviour).

        Festival sidetrack (spec 019, T205): this admin patch is the ONLY
        write path for `overnight_approved` (Ä17) — no public schema has it.
        `attendance_slots` / `accommodation` / `overnight_approved` are
        rejected on non-FESTIVAL events. `attendance_slots` is validated
        against `event.slot_keys()`. The phone-iff-accommodation rule (Ä15)
        is enforced against the RESULTING state (patched-or-existing
        accommodation + patched-or-existing phone); clearing accommodation
        also resets `overnight_approved`, mirroring T109's self-service
        reset. `group_members` on a FESTIVAL registration follows the same
        append-only/tombstone rule as T109 (the list may only grow —
        removals become `None` entries instead), overriding the SINGLE-event
        shrink-only rule below.
        """
        from .event_service import get_event_service

        registration = await self.get_registration(event_id, registration_id)
        if not registration or registration.event_id != event_id:
            return None, "not_found"

        if registration.status in (
            RegistrationStatus.CANCELLED,
            RegistrationStatus.CHECKED_IN,
        ):
            return None, "frozen_registration"

        event_service = get_event_service()
        event = await event_service.get_event_by_id(event_id)
        if not event:
            return None, "not_found"
        if event.status == EventStatus.COMPLETED:
            return None, "frozen_event"

        fields_set = patch.model_fields_set
        is_festival = event.event_type == EventType.FESTIVAL
        festival_only_fields = {
            "attendance_slots",
            "tent_count",
            "camper_count",
            "overnight_approved",
        }
        if not is_festival and (fields_set & festival_only_fields):
            return None, "not_festival_event"

        target_name = registration.name if patch.name is None else patch.name
        target_notes = registration.notes if patch.notes is None else patch.notes
        target_phone = registration.phone if patch.phone is None else patch.phone

        target_attendance_slots = registration.attendance_slots
        if "attendance_slots" in fields_set:
            target_attendance_slots = patch.attendance_slots
            if not target_attendance_slots or not set(target_attendance_slots).issubset(
                set(event.slot_keys()),
            ):
                return None, "invalid_slots"

        target_tent = registration.tent_count
        target_camper = registration.camper_count
        target_overnight_approved = registration.overnight_approved
        if is_festival:
            if "tent_count" in fields_set:
                target_tent = patch.tent_count or None
            if "camper_count" in fields_set:
                target_camper = patch.camper_count or None
            has_overnight = bool(target_tent or target_camper)

            # Ä15 phone-iff-overnight rule (admin path only), enforced on the
            # RESULTING state; clearing the whole wish clears phone + approval.
            if has_overnight:
                if not target_phone or not target_phone.strip():
                    return None, "phone_required_for_accommodation"
            else:
                target_phone = None
                if registration.has_overnight and (
                    "tent_count" in fields_set or "camper_count" in fields_set
                ):
                    target_overnight_approved = False

            if "overnight_approved" in fields_set:
                target_overnight_approved = patch.overnight_approved

            if target_overnight_approved and not has_overnight:
                return None, "overnight_approval_requires_accommodation"

        # group_members / group_size: a FESTIVAL registration touching
        # group_members uses the T109 append-only/tombstone rule (list may
        # only grow — see method docstring); everything else keeps the
        # spec-018 shrink-only rule.
        if is_festival and patch.group_members is not None:
            old_members = registration.group_members or []
            new_members = patch.group_members
            if len(new_members) < len(old_members):
                return None, "invalid_group_members"
            target_group_members: list[str | None] | None = new_members
            non_none_count = sum(1 for m in new_members if m is not None)
            target_group_size = (
                patch.group_size if patch.group_size is not None else 1 + non_none_count
            )
            if non_none_count > target_group_size - 1:
                return None, "invalid_group_members"
            if target_group_size < 1:
                return None, "invalid_group_size"
        else:
            target_group_size = registration.group_size
            target_group_members = registration.group_members

            if patch.group_members is not None and patch.group_size is not None:
                if len(patch.group_members) != patch.group_size:
                    return None, "invalid_group_members"
                target_group_members = patch.group_members
                target_group_size = patch.group_size
            elif patch.group_members is not None:
                if len(patch.group_members) > registration.group_size:
                    return None, "invalid_group_members"
                target_group_members = patch.group_members
                target_group_size = len(patch.group_members)
            elif patch.group_size is not None:
                target_group_size = patch.group_size
                if registration.group_members is not None:
                    target_group_members = registration.group_members[: patch.group_size]

            if target_group_size < 1 or target_group_size > registration.group_size:
                return None, "invalid_group_size"

        # Overnight counts (Ä21): neither may exceed the resulting group size.
        # Only reconciled on festival events (single-event patches never carry
        # the fields — rejected above).
        if is_festival:
            if target_tent and target_tent > target_group_size:
                return None, "tent_count_exceeds_group"
            if target_camper and target_camper > target_group_size:
                return None, "camper_count_exceeds_group"

        set_parts: list[str] = []
        remove_parts: list[str] = []
        expr_values: dict = {}
        expr_names: dict = {}
        changed_fields: list[str] = []

        if target_name != registration.name:
            set_parts.append("#n = :name")
            expr_names["#n"] = "name"
            expr_values[":name"] = target_name
            changed_fields.append("name")

        if target_phone != registration.phone:
            if not target_phone:
                remove_parts.append("phone")
            else:
                set_parts.append("phone = :phone")
                expr_values[":phone"] = target_phone
            changed_fields.append("phone")

        if target_notes != registration.notes:
            if not target_notes:
                remove_parts.append("notes")
            else:
                set_parts.append("notes = :notes")
                expr_values[":notes"] = target_notes
            changed_fields.append("notes")

        if target_group_size != registration.group_size:
            set_parts.append("group_size = :group_size")
            expr_values[":group_size"] = target_group_size
            changed_fields.append("group_size")

        if target_group_members != registration.group_members:
            if target_group_members is None:
                remove_parts.append("group_members")
            else:
                set_parts.append("group_members = :group_members")
                expr_values[":group_members"] = target_group_members
            changed_fields.append("group_members")

        if target_attendance_slots != registration.attendance_slots:
            if not target_attendance_slots:
                remove_parts.append("attendance_slots")
            else:
                set_parts.append("attendance_slots = :attendance_slots")
                expr_values[":attendance_slots"] = target_attendance_slots
            changed_fields.append("attendance_slots")

        if target_tent != registration.tent_count:
            if target_tent is None:
                remove_parts.append("tent_count")
            else:
                set_parts.append("tent_count = :tent_count")
                expr_values[":tent_count"] = target_tent
            changed_fields.append("tent_count")

        if target_camper != registration.camper_count:
            if target_camper is None:
                remove_parts.append("camper_count")
            else:
                set_parts.append("camper_count = :camper_count")
                expr_values[":camper_count"] = target_camper
            changed_fields.append("camper_count")

        if target_overnight_approved != registration.overnight_approved:
            set_parts.append("overnight_approved = :overnight_approved")
            expr_values[":overnight_approved"] = target_overnight_approved
            changed_fields.append("overnight_approved")

        if not changed_fields:
            return registration, None

        update_clauses: list[str] = []
        if set_parts:
            update_clauses.append("SET " + ", ".join(set_parts))
        if remove_parts:
            update_clauses.append("REMOVE " + ", ".join(remove_parts))
        update_expression = " ".join(update_clauses)

        expr_names["#s"] = "status"
        expr_values[":cur_status"] = registration.status.value
        if registration.responded_at is None:
            condition_expr = "#s = :cur_status AND attribute_not_exists(responded_at)"
        else:
            condition_expr = "#s = :cur_status AND responded_at = :cur_responded"
            expr_values[":cur_responded"] = registration.responded_at.isoformat()

        try:
            response = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
                UpdateExpression=update_expression,
                ConditionExpression=condition_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ReturnValues="ALL_NEW",
            )
            updated = _item_to_registration(response["Attributes"])
            logger.info(
                "Registration admin-updated",
                extra={
                    "registration_id": str(registration_id),
                    "event_id": str(event_id),
                    "changed_fields": changed_fields,
                },
            )
            return updated, None

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None, "conflict"
            logger.error(
                "Failed to admin-update registration",
                extra={
                    "error": str(e),
                    "registration_id": str(registration_id),
                },
            )
            return None, "update_failed"

    async def _increment_freed_spots(self, event_id: UUID, spots: int) -> None:
        """Atomically increment freed_spots counter on the event.

        Used by the daily batch promotion job to know how many spots
        were freed by group size reductions.
        """
        try:
            from .event_service import get_event_service
            event_service = get_event_service()
            event = await event_service.get_event_by_id(event_id)
            if not event:
                return

            self.events_table.update_item(
                Key={
                    "pk": f"ORG#{event.org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="ADD freed_spots :spots",
                ExpressionAttributeValues={":spots": spots},
            )
        except ClientError as e:
            logger.error(
                "Failed to increment freed_spots",
                extra={"error": str(e), "event_id": str(event_id), "spots": spots},
            )


# Singleton instance
_registration_service: RegistrationService | None = None


def get_registration_service() -> RegistrationService:
    """Get or create RegistrationService instance."""
    global _registration_service
    if _registration_service is None:
        _registration_service = RegistrationService()
    return _registration_service

"""Event service for create/publish/clone operations.

Provides:
- Event CRUD operations with DynamoDB
- Status transitions (DRAFT -> OPEN via publish)
- Event cloning for recurring events
- Capacity and registration tracking
"""

import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models import Event, EventCreate, EventStatus, EventType, EventUpdate, FestivalSlot
from .config import (
    CHECKIN_SK_PREFIX,
    EVENT_SK_INVITE_PREFIX,
    get_events_table,
    get_messages_table,
    get_registrations_table,
)
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from .charter_service import CharterService
    from .event_photo_service import EventPhotoService
    from .lost_and_found_service import LostAndFoundService

logger = get_logger(__name__)

# Raised as a ``ValueError`` by both delete paths when the event's Fundsachen
# page (spec 023) refused to go. The routers map it to 503 so the operator
# retries: an event deleted while its page still owns S3 objects takes the only
# handle on them with it.
LOSTFOUND_NOT_DELETED = "lostfound_not_deleted"

# Same contract for the event photo collection (spec 024). Kept as its own
# string rather than folded into the one above, because the two live in
# different buckets and „which one is stuck" is the first thing anyone reading
# the 503 needs to know.
PHOTOS_NOT_DELETED = "photos_not_deleted"

# Fields an organiser may still change after the Anmeldeschluss. Deliberately
# small: none of these is read by the lottery, the gate or a ticket, so
# changing one cannot invalidate something already issued. It can still leave
# guests holding a mail with the old time — the edit page says so loudly,
# because Funke sends nothing by itself (Spec 025 side note).
LATE_EDITABLE_FIELDS = frozenset({"description", "start_at", "location"})


def _same_value(current, incoming) -> bool:
    """Whether an incoming update leaves a field as it already is.

    Deliberately lenient about representation, because the payload has been
    through JSON: enums arrive as their value, datetimes may carry a different
    tzinfo for the same instant, and Pydantic sub-models arrive as dicts.
    Anything it cannot compare confidently counts as *changed* — refusing an
    edit is recoverable, silently dropping one is not.
    """
    if current == incoming:
        return True
    if isinstance(current, Enum) and current.value == incoming:
        return True
    if isinstance(current, datetime) and isinstance(incoming, datetime):
        # The edit form's `datetime-local` inputs carry minute precision, so a
        # value that merely made the round trip through the form comes back
        # shorn of seconds and microseconds. Comparing to the minute is what
        # „did the organiser change this?" actually means here; anything finer
        # would refuse every late edit on an untouched deadline.
        return current.replace(second=0, microsecond=0) == incoming.replace(
            second=0, microsecond=0,
        )
    if isinstance(current, list) and isinstance(incoming, list):
        if len(current) != len(incoming):
            return False
        return all(_same_value(a, b) for a, b in zip(current, incoming, strict=True))
    if isinstance(incoming, dict) and hasattr(current, "model_dump"):
        return current.model_dump(mode="json") == incoming
    return False

# Third refusal, and the only one that is not about stranded S3 objects: a
# signed charter contract (spec 025) is an accounting record with a ten-year
# deadline, and it lives under `pk=EVENT#{event_id}` — a partition neither
# delete path removes. Deleting the event would therefore not delete the
# contract, it would orphan it: name, postal address and two licence numbers,
# reachable through no admin route and bound by no deadline. The routers answer
# 409 rather than the 503 the two above get, because retrying will not help;
# only the deadline passing will.
CHARTER_NOT_DELETED = "charter_not_deleted"

# Registrations live under `sk="REG#{id}"`; no shared constant exists for it
# (registration_service.py inlines the literal), so mirror that here too.
REGISTRATION_SK_PREFIX = "REG#"
# Messages live under `sk="MSG#{id}"` in the separate messages table; same
# story as REGISTRATION_SK_PREFIX — email_service.py inlines the literal.
MESSAGE_SK_PREFIX = "MSG#"


def _purge_rows_by_prefix(table: "Table", pk: str, sk_prefix: str) -> int:
    """Paginated query + `batch_writer` delete of every row under `pk` whose
    `sk` starts with `sk_prefix`.

    Used by `delete_festival_event` to purge co-located festival data
    (invites, registrations, check-in scans, messages) before the EVENT#
    item itself is removed.

    Returns:
        Number of rows deleted.
    """
    query_kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
        "ProjectionExpression": "pk, sk",
    }
    items: list[dict] = []
    response = table.query(**query_kwargs)
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))

    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    return len(items)


def _generate_link_token() -> str:
    """Generate a unique, URL-safe registration link token."""
    return secrets.token_urlsafe(16)


def _event_to_item(event: Event) -> dict:
    """Convert Event model to DynamoDB item."""
    item = {
        "pk": f"ORG#{event.org_id}",
        "sk": f"EVENT#{event.id}",
        "id": str(event.id),
        "org_id": str(event.org_id),
        "name": event.name,
        "description": event.description,
        "location": event.location,
        "start_at": event.start_at.isoformat(),
        "capacity": event.capacity,
        "registration_deadline": event.registration_deadline.isoformat(),
        "status": event.status.value,
        "reminder_schedule_days": event.reminder_schedule_days,
        "autopromote_waitlist": event.autopromote_waitlist,
        "created_at": event.created_at.isoformat(),
        "entity_type": "Event",
        "event_type": event.event_type.value,
    }

    # Optional fields
    if event.registration_link_token:
        item["registration_link_token"] = event.registration_link_token
        # GSI for public link lookups
        # GSI uses registration_link_token directly as partition key

    if event.end_at:
        item["end_at"] = event.end_at.isoformat()

    if event.contact_hint:
        item["contact_hint"] = event.contact_hint

    if event.participation_hint:
        item["participation_hint"] = event.participation_hint

    if event.festival_slots:
        item["festival_slots"] = [
            {
                "key": slot.key,
                "label": slot.label,
                "date": slot.date.isoformat(),
                "is_night": slot.is_night,
                **({"capacity": slot.capacity} if slot.capacity else {}),
            }
            for slot in event.festival_slots
        ]

    if event.created_by_admin_id:
        item["created_by_admin_id"] = str(event.created_by_admin_id)

    if event.cloned_from_event_id:
        item["cloned_from_event_id"] = str(event.cloned_from_event_id)

    if event.published_at:
        item["published_at"] = event.published_at.isoformat()

    if event.cancelled_at:
        item["cancelled_at"] = event.cancelled_at.isoformat()

    if event.ttl:
        item["ttl"] = event.ttl

    if event.gate_token:
        item["gate_token"] = event.gate_token

    if event.ticket_secret:
        item["ticket_secret"] = event.ticket_secret

    if event.anonymized_at:
        item["anonymized_at"] = event.anonymized_at.isoformat()

    return item


def _item_to_event(item: dict) -> Event:
    """Convert DynamoDB item to Event model."""
    return Event(
        id=UUID(item["id"]),
        org_id=UUID(item["org_id"]),
        name=item["name"],
        description=item.get("description"),
        location=item.get("location"),
        start_at=datetime.fromisoformat(item["start_at"]),
        capacity=item["capacity"],
        registration_deadline=datetime.fromisoformat(item["registration_deadline"]),
        status=EventStatus(item["status"]),
        reminder_schedule_days=item.get("reminder_schedule_days", [7, 3, 1]),
        autopromote_waitlist=item.get("autopromote_waitlist", True),
        event_type=item.get("event_type", "SINGLE"),
        end_at=datetime.fromisoformat(item["end_at"]) if item.get("end_at") else None,
        contact_hint=item.get("contact_hint"),
        participation_hint=item.get("participation_hint"),
        festival_slots=[FestivalSlot(**s) for s in item["festival_slots"]] if item.get("festival_slots") else None,
        registration_link_token=item.get("registration_link_token"),
        created_by_admin_id=UUID(item["created_by_admin_id"]) if item.get("created_by_admin_id") else None,
        cloned_from_event_id=UUID(item["cloned_from_event_id"]) if item.get("cloned_from_event_id") else None,
        created_at=datetime.fromisoformat(item["created_at"]),
        published_at=datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None,
        cancelled_at=datetime.fromisoformat(item["cancelled_at"]) if item.get("cancelled_at") else None,
        ttl=item.get("ttl"),
        gate_token=item.get("gate_token"),
        ticket_secret=item.get("ticket_secret"),
        anonymized_at=(
            datetime.fromisoformat(item["anonymized_at"]) if item.get("anonymized_at") else None
        ),
    )


class EventService:
    """Service for event management operations."""

    def __init__(self):
        self._table = None
        self._lost_and_found = None
        self._event_photos = None
        self._charter = None

    @property
    def table(self) -> "Table":
        """Get the events table (lazy initialization)."""
        if self._table is None:
            self._table = get_events_table()
        return self._table

    @property
    def lost_and_found(self) -> "LostAndFoundService":
        """The Fundsachen service (lazy), used by the delete paths (spec 023).

        Imported inside the property because the lost & found service reaches
        back into this one for the public page's event lookup.
        """
        if self._lost_and_found is None:
            from .lost_and_found_service import get_lost_and_found_service

            self._lost_and_found = get_lost_and_found_service()
        return self._lost_and_found

    @property
    def event_photos(self) -> "EventPhotoService":
        """The Eventfotos service (lazy), used by the delete paths (spec 024).

        Imported inside the property for the same reason as above: the photo
        service resolves an event through this one on every public request, and
        a module-level import either way round would be a cycle.
        """
        if self._event_photos is None:
            from .event_photo_service import get_event_photo_service

            self._event_photos = get_event_photo_service()
        return self._event_photos

    @property
    def charter(self) -> "CharterService":
        """The Chartervertrag service (lazy), used by the delete paths (spec 025).

        Imported inside the property like its two neighbours — and here it also
        keeps the PDF renderer out of the import graph of every route that only
        ever lists events.
        """
        if self._charter is None:
            from .charter_service import get_charter_service

            self._charter = get_charter_service()
        return self._charter

    async def create_event(
        self,
        org_id: UUID,
        event_data: EventCreate,
        admin_id: UUID,
    ) -> Event:
        """Create a new event in DRAFT status.

        Args:
            org_id: Organization ID.
            event_data: Event creation data.
            admin_id: ID of the admin creating the event.

        Returns:
            Created Event with generated ID and registration link token.
            Festival events get no registration link token (invite-only,
            spec 019) and always have autopromote_waitlist disabled.
        """
        is_festival = event_data.event_type == EventType.FESTIVAL

        event = Event(
            id=uuid4(),
            org_id=org_id,
            name=event_data.name,
            description=event_data.description,
            location=event_data.location,
            start_at=event_data.start_at,
            capacity=event_data.capacity,
            registration_deadline=event_data.registration_deadline,
            reminder_schedule_days=event_data.reminder_schedule_days,
            autopromote_waitlist=False if is_festival else event_data.autopromote_waitlist,
            event_type=event_data.event_type,
            end_at=event_data.end_at,
            festival_slots=event_data.festival_slots,
            contact_hint=event_data.contact_hint,
            participation_hint=event_data.participation_hint,
            status=EventStatus.DRAFT,
            registration_link_token=None if is_festival else _generate_link_token(),
            created_by_admin_id=admin_id,
            created_at=datetime.now(timezone.utc),
        )

        item = _event_to_item(event)

        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )

            logger.info(
                "Event created",
                extra={
                    "event_id": str(event.id),
                    "org_id": str(org_id),
                    "admin_id": str(admin_id),
                    "event_name": event.name,
                },
            )

            return event

        except ClientError as e:
            logger.error(
                "Failed to create event",
                extra={"error": str(e), "org_id": str(org_id)},
            )
            raise

    async def get_event(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Get an event by ID.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Event if found, None otherwise.
        """
        try:
            response = self.table.get_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
            )
            item = response.get("Item")
            return _item_to_event(item) if item else None

        except ClientError as e:
            logger.error(
                "Failed to get event",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return None

    async def get_event_by_link_token(self, link_token: str) -> Event | None:
        """Get an event by its registration link token.

        Args:
            link_token: The public registration link token.

        Returns:
            Event if found and in valid status, None otherwise.
        """
        try:
            response = self.table.query(
                IndexName="link-token-index",
                KeyConditionExpression="registration_link_token = :token",
                ExpressionAttributeValues={":token": link_token},
            )
            items = response.get("Items", [])
            if not items:
                return None

            event = _item_to_event(items[0])
            return event

        except ClientError as e:
            logger.error(
                "Failed to get event by link token",
                extra={"error": str(e)},
            )
            return None

    async def get_event_by_gate_token(self, gate_token: str) -> Event | None:
        """Get an event by its check-in gate token (spec 019 §P3).

        Args:
            gate_token: The public checkin/scanner gate token.

        Returns:
            Event if found, None otherwise.
        """
        try:
            response = self.table.query(
                IndexName="gate-token-index",
                KeyConditionExpression="gate_token = :token",
                ExpressionAttributeValues={":token": gate_token},
            )
            items = response.get("Items", [])
            if not items:
                return None

            return _item_to_event(items[0])

        except ClientError as e:
            logger.error(
                "Failed to get event by gate token",
                extra={"error": str(e)},
            )
            return None

    async def ensure_gate_credentials(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Lazily generate the event's gate_token and ticket_secret (spec 019 §P3).

        Idempotent: once set, both values are persisted as-is on subsequent
        calls. `ticket_secret` is never rotated here — rotating it would
        invalidate every QR code already issued to guests.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            The (possibly unchanged) Event with both fields set, or None if
            the event does not exist.
        """
        event = await self.get_event(org_id, event_id)
        if event is None:
            return None

        if event.gate_token is not None and event.ticket_secret is not None:
            return event

        # Race-safe first mint: two concurrent first calls (e.g. two manage
        # pages opening right after deploy, or a manage GET racing the
        # scanner boot) must NOT each persist a different ticket_secret —
        # the loser would sign QR payloads with an overwritten secret that
        # scans red at the gate. `if_not_exists` lets DynamoDB serialize
        # the writes: whichever value lands first wins, and every caller
        # gets the winning values back via ALL_NEW.
        try:
            response = self.table.update_item(
                Key={"pk": f"ORG#{org_id}", "sk": f"EVENT#{event_id}"},
                UpdateExpression=(
                    "SET gate_token = if_not_exists(gate_token, :gt), "
                    "ticket_secret = if_not_exists(ticket_secret, :ts)"
                ),
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={
                    ":gt": _generate_link_token(),
                    ":ts": secrets.token_urlsafe(32),
                },
                ReturnValues="ALL_NEW",
            )
            return _item_to_event(response["Attributes"])

        except ClientError as e:
            logger.error(
                "Failed to ensure gate credentials",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return None

    async def get_event_by_id(self, event_id: UUID) -> Event | None:
        """Get an event by ID (scans all orgs).

        Note: This uses a table scan and should be used sparingly.
        Prefer get_event() when org_id is available.

        Args:
            event_id: Event ID.

        Returns:
            Event if found, None otherwise.
        """
        try:
            # No Limit — DynamoDB Limit on scans caps items *evaluated* not *returned*,
            # which can miss results when combined with FilterExpression. The same
            # applies to the 1 MB page size, hence the pagination: this table also
            # holds invites and lost & found rows, so one page stopped covering it
            # long ago, and callers read a miss as „the event is gone".
            scan_kwargs = {
                "FilterExpression": "id = :event_id",
                "ExpressionAttributeValues": {":event_id": str(event_id)},
            }
            while True:
                response = self.table.scan(**scan_kwargs)
                items = response.get("Items", [])
                if items:
                    return _item_to_event(items[0])
                if "LastEvaluatedKey" not in response:
                    return None
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        except ClientError as e:
            logger.error(
                "Failed to get event by ID",
                extra={"error": str(e), "event_id": str(event_id)},
            )
            return None

    async def get_events_by_status(self, status: EventStatus) -> list[Event]:
        """Get all events with a specific status (scans all orgs).

        Note: This uses a table scan and should be used for background workers.

        Args:
            status: Event status to filter by.

        Returns:
            List of events with the specified status.
        """
        try:
            events = []
            scan_kwargs = {
                "FilterExpression": "#status = :status AND begins_with(sk, :sk_prefix)",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":status": status.value,
                    ":sk_prefix": "EVENT#",
                },
            }

            response = self.table.scan(**scan_kwargs)
            events.extend([_item_to_event(item) for item in response.get("Items", [])])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.scan(**scan_kwargs)
                events.extend([_item_to_event(item) for item in response.get("Items", [])])

            logger.info(
                f"Found {len(events)} events with status {status.value}",
                extra={"status": status.value, "count": len(events)},
            )

            return events

        except ClientError as e:
            logger.error(
                "Failed to get events by status",
                extra={"error": str(e), "status": status.value},
            )
            return []

    async def list_events(
        self,
        org_id: UUID,
        status_filter: EventStatus | None = None,
    ) -> list[Event]:
        """List all events for an organization.

        Args:
            org_id: Organization ID.
            status_filter: Optional status filter.

        Returns:
            List of events.
        """
        try:
            key_condition = "pk = :pk AND begins_with(sk, :sk_prefix)"
            expression_values = {
                ":pk": f"ORG#{org_id}",
                ":sk_prefix": "EVENT#",
            }

            filter_expression = None
            if status_filter:
                filter_expression = "#status = :status"
                expression_values[":status"] = status_filter.value

            query_kwargs = {
                "KeyConditionExpression": key_condition,
                "ExpressionAttributeValues": expression_values,
            }
            if filter_expression:
                query_kwargs["FilterExpression"] = filter_expression
                query_kwargs["ExpressionAttributeNames"] = {"#status": "status"}

            response = self.table.query(**query_kwargs)
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.query(**query_kwargs)
                items.extend(response.get("Items", []))

            return [_item_to_event(item) for item in items]

        except ClientError as e:
            logger.error(
                "Failed to list events",
                extra={"error": str(e), "org_id": str(org_id)},
            )
            return []

    async def update_event(
        self,
        org_id: UUID,
        event_id: UUID,
        update_data: EventUpdate,
    ) -> Event | None:
        """Update an event.

        Freely editable while DRAFT or OPEN. Once registration has closed the
        lottery has allocated against capacity and the deadline, so only
        `LATE_EDITABLE_FIELDS` may still move. Finished events are frozen.

        Args:
            org_id: Organization ID.
            event_id: Event ID.
            update_data: Fields to update.

        Returns:
            Updated Event or None if not found/not editable.

        Raises:
            ValueError: A frozen field was included after registration closed.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        # A finished or cancelled event is history — nothing about it may move.
        if event.status in (EventStatus.COMPLETED, EventStatus.CANCELLED):
            logger.warning(
                "Cannot update a finished event",
                extra={"event_id": str(event_id), "status": event.status},
            )
            return None

        # Build update expression
        update_fields = update_data.model_dump(exclude_unset=True)
        if not update_fields:
            return event

        # Between Anmeldeschluss and Abschluss the organiser must still be able
        # to fix a wrong time, a moved meeting point or a typo in the text —
        # that used to require cancelling the whole event. Everything else
        # stays frozen: the lottery has already run against `capacity` and
        # `registration_deadline`, and `name` is what the gate checks against
        # tickets already in people's inboxes (Spec 020).
        #
        # Keep in sync with EDITABLE_AFTER_LOTTERY in EventEditPage.vue.
        if event.status not in (EventStatus.DRAFT, EventStatus.OPEN):
            # The edit form is a full-document upsert, not a patch: it posts
            # every field it renders, so `exclude_unset` still carries the ones
            # nobody touched. Rejecting a frozen field for merely *appearing*
            # would refuse every late edit — what matters is whether it would
            # actually change. Unchanged frozen fields are dropped instead.
            changed_frozen = []
            for field in sorted(set(update_fields) - LATE_EDITABLE_FIELDS):
                if _same_value(getattr(event, field, None), update_fields[field]):
                    del update_fields[field]
                else:
                    changed_frozen.append(field)
            if changed_frozen:
                raise ValueError(
                    "Nach dem Anmeldeschluss können nur noch Beschreibung, "
                    "Datum/Uhrzeit und Ort geändert werden. Gesperrt: "
                    + ", ".join(changed_frozen),
                )
            if not update_fields:
                return event

        # Ä8: enforce the per-type capacity cap against the persisted
        # event_type — EventUpdate's own validator can only check when the
        # payload carries BOTH capacity and event_type.
        new_capacity = update_fields.get("capacity")
        if new_capacity is not None:
            effective_type = update_fields.get("event_type") or event.event_type
            max_capacity = 2000 if effective_type == EventType.FESTIVAL else 500
            if new_capacity > max_capacity:
                raise ValueError(
                    f"Capacity must not exceed {max_capacity} for "
                    f"{EventType(effective_type).value} events",
                )

        update_expression_parts = []
        expression_attribute_names = {}
        expression_attribute_values = {}

        for field, value in update_fields.items():
            attr_name = f"#{field}"
            attr_value = f":{field}"
            update_expression_parts.append(f"{attr_name} = {attr_value}")
            expression_attribute_names[attr_name] = field

            # Convert datetime to ISO string
            if isinstance(value, datetime):
                value = value.isoformat()

            # festival_slots dump to dicts holding datetime.date objects,
            # which boto3's serializer rejects — store them in the exact
            # shape _event_to_item uses (isoformat date, no None capacity).
            if field == "festival_slots" and value is not None:
                # exclude_unset recurses into the slot dicts — fall back to
                # the FestivalSlot model defaults for omitted fields.
                value = [
                    {
                        "key": slot["key"],
                        "label": slot["label"],
                        "date": slot["date"].isoformat(),
                        "is_night": slot.get("is_night", False),
                        **({"capacity": slot["capacity"]} if slot.get("capacity") else {}),
                    }
                    for slot in value
                ]

            expression_attribute_values[attr_value] = value

        update_expression = "SET " + ", ".join(update_expression_parts)

        try:
            # Race guard. This used to pin the status to DRAFT-or-OPEN, which
            # was a second, hidden copy of the editability rule — widening the
            # rule above alone left every late edit failing the condition.
            # Pinning it to the status we just read keeps the protection (and
            # sharpens it: any concurrent transition now loses, not just one
            # out of DRAFT/OPEN) without restating which statuses may edit.
            expression_attribute_names["#status"] = "status"
            expression_attribute_values[":expected_status"] = event.status.value

            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expression_attribute_names,
                ExpressionAttributeValues=expression_attribute_values,
                ConditionExpression="#status = :expected_status",
                ReturnValues="ALL_NEW",
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning("Event update condition failed", extra={"event_id": str(event_id)})
                return None
            logger.error("Failed to update event", extra={"error": str(e)})
            raise

    async def publish_event(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Publish an event (DRAFT -> OPEN).

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Published Event or None if not found/cannot publish.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if not event.can_transition_to(EventStatus.OPEN):
            logger.warning(
                "Cannot publish event",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        published_at = datetime.now(timezone.utc)

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status, published_at = :published_at",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.OPEN.value,
                    ":published_at": published_at.isoformat(),
                    ":draft_status": EventStatus.DRAFT.value,
                },
                ConditionExpression="#status = :draft_status",
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Event published",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning("Event publish condition failed", extra={"event_id": str(event_id)})
                return None
            logger.error("Failed to publish event", extra={"error": str(e)})
            raise

    async def close_registration(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Close registration for an event (OPEN -> REGISTRATION_CLOSED).

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Updated Event or None if not found/cannot close.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if not event.can_transition_to(EventStatus.REGISTRATION_CLOSED):
            logger.warning(
                "Cannot close registration",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.REGISTRATION_CLOSED.value,
                    ":open_status": EventStatus.OPEN.value,
                },
                ConditionExpression="#status = :open_status",
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Registration closed",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    async def reopen_registration(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Reopen registration for an event (REGISTRATION_CLOSED -> OPEN).

        Intended for operator recovery when registration was closed by mistake.
        Only valid while the event is still in REGISTRATION_CLOSED — once the
        lottery has advanced the event further, this path is unavailable.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Updated Event or None if not found/cannot reopen.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if not event.can_transition_to(EventStatus.OPEN):
            logger.warning(
                "Cannot reopen registration",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.OPEN.value,
                    ":closed_status": EventStatus.REGISTRATION_CLOSED.value,
                },
                ConditionExpression="#status = :closed_status",
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Registration reopened",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    async def mark_lottery_pending(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Transition event to LOTTERY_PENDING after registration closes.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Updated Event or None if transition not allowed.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if event.status == EventStatus.LOTTERY_PENDING:
            return event

        if not event.can_transition_to(EventStatus.LOTTERY_PENDING):
            logger.warning(
                "Cannot mark event as LOTTERY_PENDING",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.LOTTERY_PENDING.value,
                    ":closed_status": EventStatus.REGISTRATION_CLOSED.value,
                },
                ConditionExpression="#status = :closed_status",
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Event marked as lottery pending",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    async def mark_confirmed_after_lottery(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Transition event to CONFIRMED after lottery finalization.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Updated Event or None if transition not allowed.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if event.status == EventStatus.CONFIRMED:
            return event

        if not event.can_transition_to(EventStatus.CONFIRMED):
            logger.warning(
                "Cannot mark event as CONFIRMED",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.CONFIRMED.value,
                    ":pending_status": EventStatus.LOTTERY_PENDING.value,
                    ":closed_status": EventStatus.REGISTRATION_CLOSED.value,
                },
                ConditionExpression="#status = :pending_status OR #status = :closed_status",
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Event confirmed after lottery",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    async def complete_event(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Mark event as completed (CONFIRMED -> COMPLETED).

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Updated Event or None if not found/cannot complete.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if not event.can_transition_to(EventStatus.COMPLETED):
            logger.warning(
                "Cannot complete event",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.COMPLETED.value,
                    ":confirmed_status": EventStatus.CONFIRMED.value,
                },
                ConditionExpression="#status = :confirmed_status",
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Event completed",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    async def cancel_event(self, org_id: UUID, event_id: UUID) -> Event | None:
        """Cancel an event.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Cancelled Event or None if not found/cannot cancel.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if not event.can_transition_to(EventStatus.CANCELLED):
            logger.warning(
                "Cannot cancel event",
                extra={"event_id": str(event_id), "current_status": event.status},
            )
            return None

        cancelled_at = datetime.now(timezone.utc)

        try:
            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression="SET #status = :new_status, cancelled_at = :cancelled_at",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": EventStatus.CANCELLED.value,
                    ":cancelled_at": cancelled_at.isoformat(),
                },
                ReturnValues="ALL_NEW",
            )

            logger.info(
                "Event cancelled",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )

            return _item_to_event(response["Attributes"])

        except ClientError as e:
            logger.error("Failed to cancel event", extra={"error": str(e)})
            raise

    async def delete_event(self, org_id: UUID, event_id: UUID) -> bool:
        """Delete an event (only allowed for CANCELLED events).

        Takes the event's Fundsachen page (spec 023) and its event photo
        collection (spec 024) with it, objects included; the rest of a SINGLE
        event's co-located rows are still left to `delete_festival_event`'s
        festival-only purge.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Raises:
            ValueError: ``lostfound_not_deleted`` or ``photos_not_deleted`` —
                that bucket's objects could not be removed, so the event stays
                (the router answers 503 for either); or ``charter_not_deleted``
                when a signed charter contract (spec 025) is still inside its
                ten-year retention (409 — this one is not retryable).

        Returns:
            True if deleted, False if not found or not deletable.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return False

        if event.status != EventStatus.CANCELLED:
            logger.warning(
                "Cannot delete event not in CANCELLED status",
                extra={"event_id": str(event_id), "status": event.status},
            )
            return False

        # Checked before anything is removed, so a refusal costs nothing: a
        # signed charter contract (spec 025) lives under `pk=EVENT#{event_id}`,
        # a partition this delete never touches, and would outlive the event as
        # an orphan carrying the charterer's name, address and licence numbers.
        # Ten years of accounting retention outrank the delete request.
        charter_retention_year = await self.charter.deletion_block_year(event_id)

        if charter_retention_year is not None:
            logger.warning(
                "Refusing to delete an event with a signed charter contract",
                extra={
                    "event_id": str(event_id),
                    "charter_retention_year": charter_retention_year,
                },
            )
            raise ValueError(CHARTER_NOT_DELETED)

        # Photos of guests' belongings and their captions are personal data
        # (spec 023): they go now, not on the next daily sweep. Before the
        # EVENT# item, so a failure here leaves both discoverable.
        lost_and_found = await self.lost_and_found.delete_page(event_id)

        if not lost_and_found["completed"]:
            # The page still owns photo rows and S3 objects, and this event is
            # the only handle anything has on them: `expire_pages` deliberately
            # skips a page whose event does not resolve, and the admin API 404s
            # once the ORG#/EVENT# row is gone. Deleting the event now would
            # leave photos of guests' belongings in the bucket until the 400-day
            # lifecycle rule, unreachable. So the event stays and the operator
            # calls again — the same contract the page's own DELETE endpoint has.
            logger.error(
                "Refusing to delete an event whose Fundsachen page survived",
                extra={
                    "event_id": str(event_id),
                    "lostfound_photos": lost_and_found["deleted_photos"],
                },
            )
            raise ValueError(LOSTFOUND_NOT_DELETED)

        # The guests' own photos (spec 024) are in a second bucket with the same
        # problem: `expire_collections` skips a collection whose event does not
        # resolve, so deleting the event first would strand faces of guests in
        # the bucket until the 400-day lifecycle rule, with nothing left that
        # could find them.
        photos = await self.event_photos.delete_collection(event_id)

        if not photos["completed"]:
            logger.error(
                "Refusing to delete an event whose photo collection survived",
                extra={"event_id": str(event_id), "event_photos": photos["photos"]},
            )
            raise ValueError(PHOTOS_NOT_DELETED)

        try:
            self.table.delete_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                ConditionExpression="#status = :cancelled_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":cancelled_status": EventStatus.CANCELLED.value},
            )

            logger.info(
                "Event deleted",
                extra={
                    "event_id": str(event_id),
                    "org_id": str(org_id),
                    "lostfound_photos": lost_and_found["deleted_photos"],
                    "lostfound_completed": lost_and_found["completed"],
                    "event_photos": photos["photos"],
                },
            )
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning("Event delete condition failed", extra={"event_id": str(event_id)})
                return False
            logger.error("Failed to delete event", extra={"error": str(e)})
            raise

    async def delete_festival_event(self, org_id: UUID, event_id: UUID) -> bool:
        """Delete a FESTIVAL event and every co-located row it owns.

        Mirrors `delete_event`'s CANCELLED-only guard (Ä-isolation: this
        only ever touches FESTIVAL events, a SINGLE event id 404s one layer
        up in the router via `_get_festival_event_or_404`), but additionally
        purges everything `delete_event` leaves behind as orphans for a
        SINGLE event — that's intentional scope-creep for festivals only,
        since a festival's invites/registrations/scans/messages are large
        and otherwise unreachable once the event itself is gone:

        - Invite rows (events table, `pk=EVENT#{event_id}`, `sk=INVITE#...`)
        - Registration rows (registrations table, `pk=EVENT#{event_id}`,
          `sk=REG#...`)
        - Check-in scan log rows (registrations table, same partition,
          `sk=SCAN#...`)
        - Message rows (messages table, `pk=EVENT#{event_id}`, `sk=MSG#...`)
        - The Fundsachen page (events table, same partition, `sk=LNF#...`)
          together with its photo objects in S3 (spec 023)
        - The event photo collection (events table, same partition,
          `sk=PHOTOS#...`) together with its objects in S3 (spec 024)

        Co-located rows are purged BEFORE the EVENT# item itself, so a
        failure partway through leaves the event (and any remaining rows)
        discoverable and the delete retryable, rather than orphaning data
        under a partition nothing points to anymore.

        Args:
            org_id: Organization ID.
            event_id: Festival event ID.

        Raises:
            ValueError: the event exists but is not in CANCELLED status
                (German detail — the router maps this to 409),
                ``lostfound_not_deleted`` / ``photos_not_deleted`` when that
                bucket's objects could not be removed and the event therefore
                has to stay (503), or ``charter_not_deleted`` when a signed
                charter contract (spec 025) is still inside its ten-year
                retention (409).

        Returns:
            True if deleted, False if not found (including a SINGLE event
            id, or a conditional-check race where another request deleted
            or un-cancelled it first).
        """
        event = await self.get_event(org_id, event_id)
        if not event or event.event_type != EventType.FESTIVAL:
            return False

        if event.status != EventStatus.CANCELLED:
            logger.warning(
                "Cannot delete festival event not in CANCELLED status",
                extra={"event_id": str(event_id), "status": event.status},
            )
            raise ValueError(
                "Festival muss zuerst abgesagt werden, bevor es gelöscht werden "
                f"kann (aktueller Status: {event.status.value})",
            )

        # Same guard as in `delete_event`, and for the same reason (spec 025):
        # the contract row is in this partition, and the prefix purges below
        # cover INVITE#/REG#/SCAN#/MSG# only, so a signed contract would be left
        # behind unreachable. A FESTIVAL cannot acquire one through the API —
        # the charter router refuses anything but a SINGLE event — so this is
        # defence in depth against a row that got there some other way.
        charter_retention_year = await self.charter.deletion_block_year(event_id)

        if charter_retention_year is not None:
            logger.warning(
                "Refusing to delete a festival event with a signed charter contract",
                extra={
                    "event_id": str(event_id),
                    "charter_retention_year": charter_retention_year,
                },
            )
            raise ValueError(CHARTER_NOT_DELETED)

        event_pk = f"EVENT#{event_id}"

        invite_count = _purge_rows_by_prefix(self.table, event_pk, EVENT_SK_INVITE_PREFIX)

        registrations_table = get_registrations_table()
        registration_count = _purge_rows_by_prefix(registrations_table, event_pk, REGISTRATION_SK_PREFIX)
        scan_count = _purge_rows_by_prefix(registrations_table, event_pk, CHECKIN_SK_PREFIX)

        messages_table = get_messages_table()
        message_count = _purge_rows_by_prefix(messages_table, event_pk, MESSAGE_SK_PREFIX)

        # The Fundsachen page (spec 023) lives in this same partition and owns
        # S3 objects on top of its rows, so it is deleted through its own
        # service rather than by prefix — the objects have to go with it.
        lost_and_found = await self.lost_and_found.delete_page(event_id)

        if not lost_and_found["completed"]:
            # The page still owns photo rows and S3 objects, and this event is
            # the only handle anything has on them: `expire_pages` deliberately
            # skips a page whose event does not resolve, and the admin API 404s
            # once the ORG#/EVENT# row is gone. Deleting the event now would
            # leave photos of guests' belongings in the bucket until the 400-day
            # lifecycle rule, unreachable. So the event stays and the operator
            # calls again — the same contract the page's own DELETE endpoint has.
            logger.error(
                "Refusing to delete an event whose Fundsachen page survived",
                extra={
                    "event_id": str(event_id),
                    "lostfound_photos": lost_and_found["deleted_photos"],
                },
            )
            raise ValueError(LOSTFOUND_NOT_DELETED)

        # The guests' own photos (spec 024) are in a second bucket with the same
        # problem: `expire_collections` skips a collection whose event does not
        # resolve, so deleting the event first would strand faces of guests in
        # the bucket until the 400-day lifecycle rule, with nothing left that
        # could find them.
        photos = await self.event_photos.delete_collection(event_id)

        if not photos["completed"]:
            logger.error(
                "Refusing to delete an event whose photo collection survived",
                extra={"event_id": str(event_id), "event_photos": photos["photos"]},
            )
            raise ValueError(PHOTOS_NOT_DELETED)

        logger.info(
            "Purged festival co-located data",
            extra={
                "event_id": str(event_id),
                "invites": invite_count,
                "registrations": registration_count,
                "scans": scan_count,
                "messages": message_count,
                "lostfound_photos": lost_and_found["deleted_photos"],
                "lostfound_completed": lost_and_found["completed"],
                "event_photos": photos["photos"],
            },
        )

        try:
            self.table.delete_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                ConditionExpression="#status = :cancelled_status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":cancelled_status": EventStatus.CANCELLED.value},
            )

            logger.info(
                "Festival event deleted",
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    "Festival event delete condition failed", extra={"event_id": str(event_id)},
                )
                return False
            logger.error("Failed to delete festival event", extra={"error": str(e)})
            raise

    async def clone_event(
        self,
        org_id: UUID,
        source_event_id: UUID,
        new_start_at: datetime,
        admin_id: UUID,
    ) -> Event | None:
        """Clone an existing event with a new start date.

        Args:
            org_id: Organization ID.
            source_event_id: ID of the event to clone.
            new_start_at: Start date/time for the new event.
            admin_id: ID of the admin performing the clone.

        Returns:
            New cloned Event in DRAFT status, or None if source not found.
        """
        source_event = await self.get_event(org_id, source_event_id)
        if not source_event:
            return None

        # Calculate the time delta between old and new start dates
        time_delta = new_start_at - source_event.start_at

        # Apply delta to registration deadline
        new_deadline = source_event.registration_deadline + time_delta

        new_event = Event(
            id=uuid4(),
            org_id=org_id,
            name=source_event.name,
            description=source_event.description,
            location=source_event.location,
            start_at=new_start_at,
            capacity=source_event.capacity,
            registration_deadline=new_deadline,
            reminder_schedule_days=source_event.reminder_schedule_days,
            autopromote_waitlist=source_event.autopromote_waitlist,
            status=EventStatus.DRAFT,
            registration_link_token=_generate_link_token(),
            created_by_admin_id=admin_id,
            cloned_from_event_id=source_event_id,
            created_at=datetime.now(timezone.utc),
        )

        item = _event_to_item(new_event)

        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )

            logger.info(
                "Event cloned",
                extra={
                    "new_event_id": str(new_event.id),
                    "source_event_id": str(source_event_id),
                    "org_id": str(org_id),
                    "admin_id": str(admin_id),
                },
            )

            return new_event

        except ClientError as e:
            logger.error(
                "Failed to clone event",
                extra={"error": str(e), "source_event_id": str(source_event_id)},
            )
            raise

    async def get_registration_stats(self, org_id: UUID, event_id: UUID) -> dict:
        """Get registration statistics for an event.

        Args:
            org_id: Organization ID.
            event_id: Event ID.

        Returns:
            Dict with confirmed_count, waitlist_count, cancelled_count, total_spots.
        """
        # This will query the registrations table
        # For now, return placeholder - will be implemented with registration service
        event = await self.get_event(org_id, event_id)
        if not event:
            return {}

        return {
            "event_id": str(event_id),
            "capacity": event.capacity,
            "confirmed_count": 0,
            "waitlist_count": 0,
            "cancelled_count": 0,
            "available_spots": event.capacity,
        }


# Singleton instance
_event_service: EventService | None = None


def get_event_service() -> EventService:
    """Get or create EventService instance."""
    global _event_service
    if _event_service is None:
        _event_service = EventService()
    return _event_service

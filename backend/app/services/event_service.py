"""Event service for create/publish/clone operations.

Provides:
- Event CRUD operations with DynamoDB
- Status transitions (DRAFT -> OPEN via publish)
- Event cloning for recurring events
- Capacity and registration tracking
"""

import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from botocore.exceptions import ClientError

from ..models import Event, EventCreate, EventStatus, EventUpdate
from .config import get_events_table
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


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
    }

    # Optional fields
    if event.registration_link_token:
        item["registration_link_token"] = event.registration_link_token
        # GSI for public link lookups
        # GSI uses registration_link_token directly as partition key

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
        registration_link_token=item.get("registration_link_token"),
        created_by_admin_id=UUID(item["created_by_admin_id"]) if item.get("created_by_admin_id") else None,
        cloned_from_event_id=UUID(item["cloned_from_event_id"]) if item.get("cloned_from_event_id") else None,
        created_at=datetime.fromisoformat(item["created_at"]),
        published_at=datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None,
        cancelled_at=datetime.fromisoformat(item["cancelled_at"]) if item.get("cancelled_at") else None,
        ttl=item.get("ttl"),
    )


class EventService:
    """Service for event management operations."""

    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        """Get the events table (lazy initialization)."""
        if self._table is None:
            self._table = get_events_table()
        return self._table

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
        """
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
            autopromote_waitlist=event_data.autopromote_waitlist,
            status=EventStatus.DRAFT,
            registration_link_token=_generate_link_token(),
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
            # Scan for event by ID across all orgs.
            # No Limit — DynamoDB Limit on scans caps items *evaluated* not *returned*,
            # which can miss results when combined with FilterExpression.
            response = self.table.scan(
                FilterExpression="id = :event_id",
                ExpressionAttributeValues={":event_id": str(event_id)},
            )
            items = response.get("Items", [])
            if not items:
                return None
            return _item_to_event(items[0])

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
        """Update an event (only in DRAFT or OPEN status).

        Args:
            org_id: Organization ID.
            event_id: Event ID.
            update_data: Fields to update.

        Returns:
            Updated Event or None if not found/not editable.
        """
        event = await self.get_event(org_id, event_id)
        if not event:
            return None

        if event.status not in [EventStatus.DRAFT, EventStatus.OPEN]:
            logger.warning(
                "Cannot update event not in DRAFT or OPEN status",
                extra={"event_id": str(event_id), "status": event.status},
            )
            return None

        # Build update expression
        update_fields = update_data.model_dump(exclude_unset=True)
        if not update_fields:
            return event

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

            expression_attribute_values[attr_value] = value

        update_expression = "SET " + ", ".join(update_expression_parts)

        try:
            # Add status condition to prevent race conditions
            expression_attribute_names["#status"] = "status"
            expression_attribute_values[":draft_status"] = EventStatus.DRAFT.value
            expression_attribute_values[":open_status"] = EventStatus.OPEN.value

            response = self.table.update_item(
                Key={
                    "pk": f"ORG#{org_id}",
                    "sk": f"EVENT#{event_id}",
                },
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expression_attribute_names,
                ExpressionAttributeValues=expression_attribute_values,
                ConditionExpression="#status = :draft_status OR #status = :open_status",
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

        Args:
            org_id: Organization ID.
            event_id: Event ID.

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
                extra={"event_id": str(event_id), "org_id": str(org_id)},
            )
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning("Event delete condition failed", extra={"event_id": str(event_id)})
                return False
            logger.error("Failed to delete event", extra={"error": str(e)})
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

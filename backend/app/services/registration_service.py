"""Registration service for capacity/waitlist management and cancellation.

Provides:
- Registration submission with capacity checking
- Automatic waitlist assignment when capacity exceeded
- Cancellation token handling
- Waitlist promotion when spots open
- DynamoDB transactions for atomic capacity operations
"""

import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings

from ..models import (
    Event,
    EventStatus,
    Registration,
    RegistrationCreate,
    RegistrationStatus,
)
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


class DynamoDBSettings(BaseSettings):
    """DynamoDB configuration settings."""

    dynamodb_table_prefix: str = "funke-dev"
    aws_region: str = "eu-central-1"
    dynamodb_endpoint_url: str | None = None

    class Config:
        env_prefix = ""
        case_sensitive = False


_settings: DynamoDBSettings | None = None


def get_dynamodb_settings() -> DynamoDBSettings:
    """Get DynamoDB settings (cached)."""
    global _settings
    if _settings is None:
        _settings = DynamoDBSettings()
    return _settings


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get DynamoDB resource."""
    settings = get_dynamodb_settings()
    kwargs = {"region_name": settings.aws_region}
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def get_registrations_table() -> "Table":
    """Get the registrations DynamoDB table."""
    settings = get_dynamodb_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-registrations")


def get_events_table() -> "Table":
    """Get the events DynamoDB table."""
    settings = get_dynamodb_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-events")


def _generate_registration_token() -> str:
    """Generate a unique token for cancellation/confirmation links."""
    return secrets.token_urlsafe(32)


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
        "entity_type": "Registration",
        # GSI fields are already included: event_id, email, registration_token
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

    if registration.ttl:
        item["ttl"] = registration.ttl

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
        status=RegistrationStatus(item["status"]),
        waitlist_position=item.get("waitlist_position"),
        registration_token=item["registration_token"],
        registered_at=datetime.fromisoformat(item["registered_at"]),
        responded_at=(
            datetime.fromisoformat(item["responded_at"])
            if item.get("responded_at")
            else None
        ),
        promoted_from_waitlist=item.get("promoted_from_waitlist", False),
        ttl=item.get("ttl"),
    )


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

    async def _get_confirmed_count(self, event_id: UUID) -> int:
        """Get total confirmed spots (sum of group_size for confirmed registrations)."""
        try:
            response = self.registrations_table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
                FilterExpression="#status = :confirmed",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":confirmed": RegistrationStatus.CONFIRMED.value},
                ProjectionExpression="group_size",
            )

            items = response.get("Items", [])
            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.registrations_table.query(
                    KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
                    FilterExpression="#status = :confirmed",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":confirmed": RegistrationStatus.CONFIRMED.value},
                    ProjectionExpression="group_size",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            return sum(item.get("group_size", 1) for item in items)

        except ClientError as e:
            logger.error("Failed to get confirmed count", extra={"error": str(e)})
            return 0

    async def _get_max_waitlist_position(self, event_id: UUID) -> int:
        """Get the maximum waitlist position for an event."""
        try:
            response = self.registrations_table.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
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

        All registrations start with REGISTERED status. Status changes to
        CONFIRMED or WAITLISTED/CANCELLED after deadline passes (auto-confirm
        if under capacity) or after lottery is run.

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

        # Check event status
        if event.status != EventStatus.OPEN:
            return None, "Registration is not open for this event"

        # Check deadline
        if datetime.now(timezone.utc) >= event.registration_deadline.replace(tzinfo=timezone.utc):
            return None, "Registration deadline has passed"

        # Normalize email
        email = registration_data.email.lower().strip()

        # Check for duplicate email
        if await self._check_duplicate_email(event.id, email):
            return None, "Email already registered for this event"

        # Validate group size
        if registration_data.group_size > 10:
            return None, "Group size cannot exceed 10"

        # Create registration with REGISTERED status
        # Capacity check happens after deadline or during lottery
        registration = Registration(
            id=uuid4(),
            event_id=event.id,
            name=registration_data.name,
            email=email,
            phone=registration_data.phone,
            notes=registration_data.notes,
            group_size=registration_data.group_size,
            status=RegistrationStatus.REGISTERED,
            waitlist_position=None,
            registration_token=_generate_registration_token(),
            registered_at=datetime.now(timezone.utc),
        )

        item = _registration_to_item(registration)

        try:
            # Use conditional write to prevent race conditions
            self.registrations_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
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
                "KeyConditionExpression": Key("pk").eq(f"EVENT#{event_id}"),
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

        was_confirmed = registration.status == RegistrationStatus.CONFIRMED
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
                    "was_confirmed": was_confirmed,
                },
            )

            # If was confirmed, trigger waitlist promotion
            if was_confirmed:
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

        if not event or not event.autopromote_waitlist:
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
                    ":responded_at": datetime.now(timezone.utc).isoformat(),
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

            # If declined (cancelled), trigger waitlist promotion
            if not participating:
                await self._promote_from_waitlist(registration.event_id, group_size)

            return updated_registration, None

        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None, "Attendance response has already been recorded"
            logger.error("Failed to set attendance response", extra={"error": str(e)})
            return None, "Failed to record attendance response"

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


# Singleton instance
_registration_service: RegistrationService | None = None


def get_registration_service() -> RegistrationService:
    """Get or create RegistrationService instance."""
    global _registration_service
    if _registration_service is None:
        _registration_service = RegistrationService()
    return _registration_service

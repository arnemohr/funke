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

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models import (
    Event,
    EventStatus,
    Registration,
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

    if registration.group_members is not None:
        item["group_members"] = registration.group_members

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
        promoted_from_waitlist=item.get("promoted_from_waitlist", False),
        promoted=item.get("promoted", False),
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
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
                ProjectionExpression="group_size, #status",
                ExpressionAttributeNames={"#status": "status"},
            )

            items = response.get("Items", [])
            while "LastEvaluatedKey" in response:
                response = self.registrations_table.query(
                    KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}"),
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
            status=initial_status,
            waitlist_position=waitlist_position,
            registration_token=_generate_registration_token(),
            registered_at=datetime.now(timezone.utc),
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

            # If held a spot (CONFIRMED or PARTICIPATING), trigger waitlist promotion
            if held_spot:
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
            expr_values[":responded_at"] = datetime.now(timezone.utc).isoformat()

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
    ) -> tuple[int, int]:
        """Discard all unacknowledged (CONFIRMED) registrations for an event.

        Transitions CONFIRMED registrations to CANCELLED and sends notification emails.
        Triggers waitlist promotion for freed spots.

        Args:
            event_id: Event ID.

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
                        await email_service.send_cancellation_confirmation(event, cancelled_reg)
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
                    ":responded_at": datetime.now(timezone.utc).isoformat(),
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

    async def admin_update_group_members(
        self,
        event_id: UUID,
        registration_id: UUID,
        group_members: list[str],
    ) -> Registration | None:
        """Admin: update group member names for a registration.

        Only edits names — does not change group_size.

        Args:
            event_id: Event ID.
            registration_id: Registration ID.
            group_members: Updated list of group member names.

        Returns:
            Updated registration, or None on failure.
        """
        registration = await self.get_registration(event_id, registration_id)
        if not registration:
            return None

        if len(group_members) > registration.group_size:
            return None

        stripped = [name.strip() for name in group_members]
        if any(not name for name in stripped):
            return None

        try:
            response_data = self.registrations_table.update_item(
                Key={
                    "pk": f"EVENT#{event_id}",
                    "sk": f"REG#{registration_id}",
                },
                UpdateExpression="SET group_members = :group_members",
                ExpressionAttributeValues={
                    ":group_members": stripped,
                },
                ReturnValues="ALL_NEW",
            )
            return _item_to_registration(response_data["Attributes"])

        except ClientError as e:
            logger.error(
                "Failed to admin-update group members",
                extra={"error": str(e), "registration_id": str(registration_id)},
            )
            return None

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

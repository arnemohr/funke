"""Admin event API endpoints.

Provides:
- Create event (DRAFT)
- Publish event (DRAFT -> OPEN)
- Clone event
- Get/List events
- Update event (DRAFT only)
- Cancel event
"""

import csv
import io
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...models import (
    CustomMessageRequest,
    Event,
    EventCreate,
    EventStatus,
    EventUpdate,
    Registration,
    RegistrationStatus,
)
from ...services.auth import AdminRole, CurrentUser, require_role
from ...services.email_service import get_email_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger, log_admin_action
from ...services.registration_service import get_registration_service

logger = get_logger(__name__)

router = APIRouter()


class CloneEventRequest(BaseModel):
    """Request body for cloning an event."""

    start_at: datetime = Field(..., description="Start date/time for the cloned event")


class EventResponse(BaseModel):
    """Event response with registration stats."""

    id: UUID
    name: str
    description: str | None
    location: str | None
    start_at: datetime
    capacity: int
    registration_deadline: datetime
    status: EventStatus
    reminder_schedule_days: list[int]
    autopromote_waitlist: bool
    registration_link_token: str | None
    created_at: datetime
    published_at: datetime | None
    cancelled_at: datetime | None
    registration_count: int = 0
    registration_spots: int = 0
    confirmed_spots: int = 0
    waitlist_count: int = 0
    waitlist_spots: int = 0


class EventListResponse(BaseModel):
    """Response for list events endpoint."""

    items: list[EventResponse]
    total: int


def _get_org_id(user: CurrentUser) -> UUID:
    """Extract organization ID from user token."""
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization ID not found in token",
        )
    return UUID(user.org_id)


def _get_admin_id(user: CurrentUser) -> UUID:
    """Convert Auth0 sub to a UUID. Auth0 uses format like 'auth0|123456'."""
    import hashlib
    return UUID(hashlib.md5(user.sub.encode()).hexdigest())


async def _event_to_response(event: Event) -> EventResponse:
    """Convert Event model to response with stats."""
    registration_service = get_registration_service()
    stats = await registration_service.get_registration_stats(event.id)

    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        capacity=event.capacity,
        registration_deadline=event.registration_deadline,
        status=event.status,
        reminder_schedule_days=event.reminder_schedule_days,
        autopromote_waitlist=event.autopromote_waitlist,
        registration_link_token=event.registration_link_token,
        created_at=event.created_at,
        published_at=event.published_at,
        cancelled_at=event.cancelled_at,
        registration_count=stats.get("total_registrations", 0),
        registration_spots=stats.get("total_registration_spots", 0),
        confirmed_spots=stats.get("confirmed_spots", 0),
        waitlist_count=stats.get("waitlist_registrations", 0),
        waitlist_spots=stats.get("waitlist_spots", 0),
    )


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def create_event(
    event_data: EventCreate,
    user: CurrentUser,
) -> EventResponse:
    """Create a new event in DRAFT status.

    Returns the created event with a shareable registration link token.
    """
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)

    event_service = get_event_service()
    event = await event_service.create_event(org_id, event_data, admin_id)

    log_admin_action("event.create", user.email, str(event.id), {"event_name": event.name})

    return await _event_to_response(event)


@router.get(
    "",
    response_model=EventListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_events(
    user: CurrentUser,
    status_filter: Annotated[EventStatus | None, Query(alias="status")] = None,
) -> EventListResponse:
    """List all events for the organization.

    Optionally filter by status.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    events = await event_service.list_events(org_id, status_filter)

    # Convert to responses with stats
    items = []
    for event in events:
        items.append(await _event_to_response(event))

    return EventListResponse(items=items, total=len(items))


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def get_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Get event details by ID."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    return await _event_to_response(event)


@router.patch(
    "/{event_id}",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def update_event(
    event_id: UUID,
    update_data: EventUpdate,
    user: CurrentUser,
) -> EventResponse:
    """Update event details (only allowed in DRAFT or OPEN status)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.update_event(org_id, event_id, update_data)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be updated (must be in DRAFT or OPEN status)",
        )

    log_admin_action("event.update", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/publish",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def publish_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Publish an event (DRAFT -> OPEN).

    After publishing, the event accepts registrations via the public link.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.publish_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be published (not in DRAFT status)",
        )

    log_admin_action("event.publish", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/clone",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def clone_event(
    event_id: UUID,
    clone_data: CloneEventRequest,
    user: CurrentUser,
) -> EventResponse:
    """Clone an existing event with a new start date.

    Creates a new DRAFT event with the same settings but updated dates.
    """
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)

    event_service = get_event_service()
    new_event = await event_service.clone_event(
        org_id,
        event_id,
        clone_data.start_at,
        admin_id,
    )

    if not new_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source event not found",
        )

    log_admin_action(
        "event.clone", user.email, str(new_event.id),
        {"source_event_id": str(event_id)},
    )

    return await _event_to_response(new_event)


@router.post(
    "/{event_id}/close-registration",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def close_registration(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Manually close registration for an event (OPEN -> REGISTRATION_CLOSED)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.close_registration(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot close registration (not in OPEN status)",
        )

    log_admin_action("event.close_registration", user.email, str(event_id))

    return await _event_to_response(event)


@router.post(
    "/{event_id}/cancel",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def cancel_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Cancel an event.

    Cancellation is final and cannot be undone.
    All registrants will be notified via email.
    """
    org_id = _get_org_id(user)
    registration_service = get_registration_service()
    email_service = get_email_service()

    # Fetch active registrations BEFORE cancelling (so we have their details for notifications)
    active_registrations = [
        r
        for r in await registration_service.list_registrations(event_id)
        if r.status != RegistrationStatus.CANCELLED
    ]

    # Cancel the event
    event_service = get_event_service()
    event = await event_service.cancel_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be cancelled",
        )

    log_admin_action("event.cancel", user.email, str(event_id))

    # Cancel all registrations for this event
    cancelled_count = await registration_service.cancel_all_registrations_for_event(event_id)
    logger.info(
        "All registrations cancelled for event",
        extra={
            "event_id": str(event_id),
            "cancelled_count": cancelled_count,
        },
    )

    # Notify using pre-fetched list (registrations already cancelled in DB)
    notified_count = 0
    failed_count = 0

    for registration in active_registrations:
        try:
            await email_service.send_event_cancellation(event, registration)
            notified_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                "Failed to send event cancellation email",
                extra={
                    "registration_id": str(registration.id),
                    "email": registration.email,
                    "error": str(e),
                },
            )

    logger.info(
        "Event cancellation notifications sent",
        extra={
            "event_id": str(event_id),
            "notified_count": notified_count,
            "failed_count": failed_count,
        },
    )

    return await _event_to_response(event)


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def delete_event(
    event_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete an event (only allowed for CANCELLED events).

    Deletion is permanent and cannot be undone.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    deleted = await event_service.delete_event(org_id, event_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be deleted (must be in CANCELLED status)",
        )

    log_admin_action("event.delete", user.email, str(event_id))


class RegistrationResponse(BaseModel):
    """Registration response for admin view."""

    id: UUID
    event_id: UUID
    name: str
    email: str
    phone: str | None
    notes: str | None
    group_size: int
    status: RegistrationStatus
    waitlist_position: int | None
    registration_token: str
    registered_at: datetime
    responded_at: datetime | None
    promoted_from_waitlist: bool


class RegistrationListResponse(BaseModel):
    """Response for list registrations endpoint."""

    items: list[RegistrationResponse]
    total: int


def _registration_to_response(registration: Registration) -> RegistrationResponse:
    """Convert Registration model to response."""
    return RegistrationResponse(
        id=registration.id,
        event_id=registration.event_id,
        name=registration.name,
        email=registration.email,
        phone=registration.phone,
        notes=registration.notes,
        group_size=registration.group_size,
        status=registration.status,
        waitlist_position=registration.waitlist_position,
        registration_token=registration.registration_token,
        registered_at=registration.registered_at,
        responded_at=registration.responded_at,
        promoted_from_waitlist=registration.promoted_from_waitlist,
    )


@router.get(
    "/{event_id}/registrations",
    response_model=RegistrationListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_registrations(
    event_id: UUID,
    user: CurrentUser,
    status_filter: Annotated[RegistrationStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query()] = None,
) -> RegistrationListResponse:
    """List all registrations for an event.

    Supports filtering by status and searching by name/email.
    """
    org_id = _get_org_id(user)

    # Verify event belongs to org
    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(
        event_id, status_filter, search,
    )

    return RegistrationListResponse(
        items=[_registration_to_response(r) for r in registrations],
        total=len(registrations),
    )


@router.get(
    "/{event_id}/registrations/export",
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def export_registrations_csv(
    event_id: UUID,
    user: CurrentUser,
) -> StreamingResponse:
    """Export registrations as CSV with BOM for Excel/German umlaut compatibility."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(event_id)

    # Build CSV with BOM for Excel compatibility
    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Name", "E-Mail", "Telefon", "Gruppengröße", "Status",
        "Wartelistenplatz", "Angemeldet am", "Bestätigt am", "Notizen",
    ])

    for reg in registrations:
        writer.writerow([
            reg.name,
            reg.email,
            reg.phone or "",
            reg.group_size,
            reg.status.value,
            reg.waitlist_position or "",
            reg.registered_at.isoformat() if reg.registered_at else "",
            reg.responded_at.isoformat() if reg.responded_at else "",
            reg.notes or "",
        ])

    log_admin_action("registrations.export", user.email, str(event_id))

    output.seek(0)
    filename = f"anmeldungen_{event.name.replace(' ', '_')}_{event_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class CustomMessageResponse(BaseModel):
    """Response for custom message sending."""

    sent: int
    failed: int
    total: int


@router.post(
    "/{event_id}/messages",
    response_model=CustomMessageResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def send_custom_message(
    event_id: UUID,
    message_data: CustomMessageRequest,
    user: CurrentUser,
) -> CustomMessageResponse:
    """Send a custom message to selected registrations."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    email_service = get_email_service()

    sent = 0
    failed = 0

    for reg_id in message_data.registration_ids:
        registration = await registration_service.get_registration(event_id, reg_id)
        if not registration:
            failed += 1
            continue

        try:
            success = await email_service.send_custom_message(
                event, registration, message_data.subject, message_data.body,
            )
            if success:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error(
                "Failed to send custom message",
                extra={"registration_id": str(reg_id), "error": str(e)},
            )

    log_admin_action(
        "message.send_custom",
        user.email,
        str(event_id),
        {"sent": sent, "failed": failed, "total": len(message_data.registration_ids)},
    )

    return CustomMessageResponse(
        sent=sent,
        failed=failed,
        total=len(message_data.registration_ids),
    )


class MessageLogEntry(BaseModel):
    """Single message in the log."""

    id: str | None
    type: str | None
    subject: str | None
    recipient_email: str | None
    status: str | None
    sent_at: str | None


class MessageListResponse(BaseModel):
    """Response for messages list endpoint."""

    items: list[MessageLogEntry]
    total: int


@router.get(
    "/{event_id}/messages",
    response_model=MessageListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_messages(
    event_id: UUID,
    user: CurrentUser,
) -> MessageListResponse:
    """List sent messages for an event."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    email_service = get_email_service()
    messages = await email_service.list_messages_for_event(event_id)

    return MessageListResponse(
        items=[MessageLogEntry(**m) for m in messages],
        total=len(messages),
    )

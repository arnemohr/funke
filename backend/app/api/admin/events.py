"""Admin event API endpoints.

Provides:
- Create event (DRAFT)
- Publish event (DRAFT -> OPEN)
- Clone event
- Get/List events
- Update event (DRAFT only)
- Cancel event
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...models import (
    Event,
    EventCreate,
    EventPublic,
    EventStatus,
    EventUpdate,
    Registration,
    RegistrationStatus,
)
from ...services.auth import AdminRole, CurrentUser, require_role
from ...services.email_service import get_email_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger
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
    confirmed_spots: int = 0
    waitlist_count: int = 0


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
        confirmed_spots=stats.get("confirmed_spots", 0),
        waitlist_count=stats.get("waitlist_registrations", 0),
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

    logger.info(
        "Event created via API",
        extra={
            "event_id": str(event.id),
            "admin_email": user.email,
        },
    )

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

    logger.info(
        "Event updated via API",
        extra={
            "event_id": str(event_id),
            "admin_email": user.email,
        },
    )

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

    logger.info(
        "Event published via API",
        extra={
            "event_id": str(event_id),
            "admin_email": user.email,
        },
    )

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

    logger.info(
        "Event cloned via API",
        extra={
            "source_event_id": str(event_id),
            "new_event_id": str(new_event.id),
            "admin_email": user.email,
        },
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

    logger.info(
        "Event registration closed via API",
        extra={
            "event_id": str(event_id),
            "admin_email": user.email,
        },
    )

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

    event_service = get_event_service()
    event = await event_service.cancel_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be cancelled",
        )

    logger.info(
        "Event cancelled via API",
        extra={
            "event_id": str(event_id),
            "admin_email": user.email,
        },
    )

    # Notify all registrants about the cancellation
    registration_service = get_registration_service()
    email_service = get_email_service()

    registrations = await registration_service.list_registrations(event_id)
    notified_count = 0
    failed_count = 0

    for registration in registrations:
        # Skip already-cancelled registrations
        if registration.status == RegistrationStatus.CANCELLED:
            continue

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

    logger.info(
        "Event deleted via API",
        extra={
            "event_id": str(event_id),
            "admin_email": user.email,
        },
    )


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
        event_id, status_filter, search
    )

    return RegistrationListResponse(
        items=[_registration_to_response(r) for r in registrations],
        total=len(registrations),
    )

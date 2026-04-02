"""Admin event API endpoints.

Provides:
- Create event (DRAFT)
- Publish event (DRAFT -> OPEN)
- Clone event
- Get/List events
- Update event (DRAFT only)
- Cancel event
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo
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
    promoted_count: int = 0
    promoted_spots: int = 0


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
        promoted_count=stats.get("promoted_count", 0),
        promoted_spots=stats.get("promoted_spots", 0),
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
    "/{event_id}/complete",
    response_model=EventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def complete_event(
    event_id: UUID,
    user: CurrentUser,
) -> EventResponse:
    """Mark event as completed (CONFIRMED -> COMPLETED)."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.complete_event(org_id, event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be completed (not in CONFIRMED status)",
        )

    log_admin_action("event.complete", user.email, str(event_id))

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


@router.delete(
    "/{event_id}/registrations/{registration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def delete_registration(
    event_id: UUID,
    registration_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete a registration permanently."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    deleted = await registration_service.delete_registration(event_id, registration_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    log_admin_action(
        "registration.delete",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id), "name": deleted.name},
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
    group_members: list[str] | None = None
    status: RegistrationStatus
    waitlist_position: int | None
    registration_token: str
    registered_at: datetime
    responded_at: datetime | None
    page_viewed_at: datetime | None = None
    promoted_from_waitlist: bool
    promoted: bool


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
        group_members=registration.group_members,
        status=registration.status,
        waitlist_position=registration.waitlist_position,
        registration_token=registration.registration_token,
        registered_at=registration.registered_at,
        responded_at=registration.responded_at,
        page_viewed_at=registration.page_viewed_at,
        promoted_from_waitlist=registration.promoted_from_waitlist,
        promoted=registration.promoted,
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
    "/{event_id}/registrations/unacknowledged",
    response_model=RegistrationListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_unacknowledged(
    event_id: UUID,
    user: CurrentUser,
) -> RegistrationListResponse:
    """List unacknowledged (CONFIRMED) registrations for preview before discard."""
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(
        event_id, status_filter=RegistrationStatus.CONFIRMED,
    )

    return RegistrationListResponse(
        items=[_registration_to_response(r) for r in registrations],
        total=len(registrations),
    )


class DiscardRequest(BaseModel):
    """Request body for discarding unacknowledged registrations."""

    registration_ids: list[UUID] | None = None
    reason: str | None = None
    subject: str | None = None


class DiscardResponse(BaseModel):
    """Response for discard unacknowledged endpoint."""

    discarded_count: int
    discarded_spots: int


@router.post(
    "/{event_id}/registrations/discard-unacknowledged",
    response_model=DiscardResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def discard_unacknowledged(
    event_id: UUID,
    user: CurrentUser,
    body: DiscardRequest = DiscardRequest(),
) -> DiscardResponse:
    """Discard unacknowledged (CONFIRMED) registrations.

    Cancels selected (or all) registrations and sends notification emails.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    discarded_count, discarded_spots = await registration_service.discard_unacknowledged(
        event_id, body.registration_ids, body.reason, body.subject,
    )

    log_admin_action(
        "registrations.discard_unacknowledged",
        user.email,
        str(event_id),
        {"discarded_count": discarded_count, "discarded_spots": discarded_spots},
    )

    return DiscardResponse(
        discarded_count=discarded_count,
        discarded_spots=discarded_spots,
    )


class PromoteFromWaitlistRequest(BaseModel):
    """Request body for manual waitlist promotion."""

    target_status: str = "CONFIRMED"  # "CONFIRMED" or "PARTICIPATING"


@router.post(
    "/{event_id}/registrations/{registration_id}/promote-from-waitlist",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def promote_from_waitlist(
    event_id: UUID,
    registration_id: UUID,
    body: PromoteFromWaitlistRequest,
    user: CurrentUser,
) -> RegistrationResponse:
    """Manually promote a waitlisted registration.

    target_status can be CONFIRMED (user must acknowledge) or PARTICIPATING (direct).
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    target = RegistrationStatus(body.target_status)
    if target not in (RegistrationStatus.CONFIRMED, RegistrationStatus.PARTICIPATING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_status must be CONFIRMED or PARTICIPATING",
        )

    registration_service = get_registration_service()

    # Check capacity before promoting
    reg = await registration_service.get_registration(event_id, registration_id)
    if not reg or reg.status != RegistrationStatus.WAITLISTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or not in WAITLISTED status",
        )
    stats = await registration_service.get_registration_stats(event_id)
    remaining = event.capacity - stats["confirmed_spots"]
    if reg.group_size > remaining:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Nicht genügend Plätze: {remaining} frei, {reg.group_size} benötigt",
        )

    registration = await registration_service.promote_single_from_waitlist(
        event_id, registration_id, target,
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or not in WAITLISTED status",
        )

    log_admin_action(
        "registration.promote_from_waitlist",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id), "target_status": body.target_status},
    )

    return _registration_to_response(registration)


class TogglePromotedRequest(BaseModel):
    """Request body for toggling promoted flag."""

    promoted: bool


@router.patch(
    "/{event_id}/registrations/{registration_id}/promote",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def toggle_promoted(
    event_id: UUID,
    registration_id: UUID,
    body: TogglePromotedRequest,
    user: CurrentUser,
) -> RegistrationResponse:
    """Toggle the promoted flag on a registration.

    Only allowed when event is OPEN or REGISTRATION_CLOSED.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    if event.status not in (EventStatus.OPEN, EventStatus.REGISTRATION_CLOSED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Promoted flag can only be changed when event is OPEN or REGISTRATION_CLOSED",
        )

    registration_service = get_registration_service()
    registration = await registration_service.set_promoted(
        event_id, registration_id, body.promoted,
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or not in REGISTERED status",
        )

    log_admin_action(
        "registration.toggle_promoted",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id), "promoted": body.promoted},
    )

    return _registration_to_response(registration)


class AdminUpdateGroupMembersRequest(BaseModel):
    """Request body for admin group member name editing."""

    group_members: list[str]


@router.put(
    "/{event_id}/registrations/{registration_id}/group-members",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def admin_update_group_members(
    event_id: UUID,
    registration_id: UUID,
    body: AdminUpdateGroupMembersRequest,
    user: CurrentUser,
) -> RegistrationResponse:
    """Admin: edit group member names for a registration.

    Only edits names — does not change group_size.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    registration_service = get_registration_service()
    registration = await registration_service.admin_update_group_members(
        event_id, registration_id, body.group_members,
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration not found or invalid group member names",
        )

    log_admin_action(
        "registration.update_group_members",
        user.email,
        str(event_id),
        {"registration_id": str(registration_id)},
    )

    return _registration_to_response(registration)


@router.get(
    "/{event_id}/registrations/export",
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def export_registrations_pdf(
    event_id: UUID,
    user: CurrentUser,
) -> StreamingResponse:
    """Export boarding list as PDF with guest names and signature column."""
    from fpdf import FPDF

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

    # Collect all guest names (one per person, not per registration)
    guests: list[str] = []
    for reg in registrations:
        if reg.status.value != "PARTICIPATING":
            continue
        if reg.group_members and len(reg.group_members) > 0:
            guests.extend(reg.group_members)
        elif reg.group_size == 1:
            guests.append(reg.name)
        else:
            guests.append(reg.name)
            guests.extend(f"(Gast {i + 2} von {reg.name})" for i in range(reg.group_size - 1))

    # Build PDF
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Boardingzettel", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, event.name, new_x="LMARGIN", new_y="NEXT", align="C")
    event_date = event.start_at.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")
    location = event.location or ""
    subtitle = f"{event_date}  {location}".strip() if location else event_date
    pdf.cell(0, 7, subtitle, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 4, f"{len(guests)} Passagiere", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Table header
    col_nr = 12
    col_name = 108
    col_sig = 50
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(col_nr, 8, "#", border=1, fill=True, align="C")
    pdf.cell(col_name, 8, "Name", border=1, fill=True)
    pdf.cell(col_sig, 8, "Unterschrift", border=1, fill=True)
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 10)
    row_height = 10
    for i, name in enumerate(guests, 1):
        # Check if we need a new page
        if pdf.get_y() + row_height > pdf.h - 20:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_fill_color(230, 230, 230)
            pdf.cell(col_nr, 8, "#", border=1, fill=True, align="C")
            pdf.cell(col_name, 8, "Name", border=1, fill=True)
            pdf.cell(col_sig, 8, "Unterschrift", border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 10)

        pdf.cell(col_nr, row_height, str(i), border=1, align="C")
        pdf.cell(col_name, row_height, name, border=1)
        pdf.cell(col_sig, row_height, "", border=1)
        pdf.ln()

    log_admin_action("registrations.export", user.email, str(event_id))

    pdf_bytes = pdf.output()
    umlaut_map = str.maketrans({'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss'})
    safe_name = event.name.translate(umlaut_map).replace(' ', '_').encode('ascii', 'replace').decode('ascii')
    filename = f"boardingzettel_{safe_name}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
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
                include_links=message_data.include_links,
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

"""Public registration API endpoints.

Provides:
- Get event info for registration form
- Submit registration (no auth required)
- Registration management (confirm with names, update group members)
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...models import (
    EventPublic,
    RegistrationCreate,
    RegistrationResponse,
)
from ...services.email_service import get_email_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger
from ...services.registration_service import get_registration_service

logger = get_logger(__name__)

router = APIRouter()


class RegistrationSubmitResponse(BaseModel):
    """Response for successful registration submission."""

    registration: RegistrationResponse
    message: str


@router.get(
    "/events/{link_token}",
    response_model=EventPublic,
)
async def get_event_info(link_token: str) -> EventPublic:
    """Get public event info for the registration form.

    Uses the registration link token (not the event ID).
    Returns 410 Gone if event is closed or cancelled.
    """
    event_service = get_event_service()
    event = await event_service.get_event_by_link_token(link_token)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    # Return 410 if event is not accepting any registrations
    accepting_statuses = {"OPEN", "REGISTRATION_CLOSED", "LOTTERY_PENDING", "CONFIRMED"}
    if event.status.value not in accepting_statuses:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Event registration is closed (status: {event.status.value})",
        )

    # Return limited public info
    return EventPublic(
        name=event.name,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        capacity=event.capacity,
        registration_deadline=event.registration_deadline,
        status=event.status.value,
        autopromote_waitlist=event.autopromote_waitlist,
    )


@router.post(
    "/events/{link_token}/registrations",
    response_model=RegistrationSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_registration(
    link_token: str,
    registration_data: RegistrationCreate,
) -> RegistrationSubmitResponse:
    """Submit a registration for an event.

    All registrations start as REGISTERED. Capacity enforcement is
    deferred to the lottery phase after registration closes.

    Returns 409 Conflict if email is already registered for this event.
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.create_registration(
        link_token,
        registration_data,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error,
            )
        if "already registered" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error,
            )
        if "deadline" in error.lower() or "not open" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    logger.info(
        "Registration submitted via public API",
        extra={
            "registration_id": str(registration.id),
            "event_id": str(registration.event_id),
            "status": registration.status.value,
        },
    )

    # Send appropriate email based on registration status
    try:
        event_service = get_event_service()
        event = await event_service.get_event_by_link_token(link_token)
        if event:
            email_service = get_email_service()
            if registration.status.value == "WAITLISTED":
                await email_service.send_waitlist_notification(event, registration)
            else:
                await email_service.send_registration_confirmation(event, registration)
        else:
            logger.warning(
                "Could not send email: event not found by link token",
                extra={"link_token": link_token, "registration_id": str(registration.id)},
            )
    except Exception as e:
        # Don't fail the registration if email fails
        logger.error(
            "Failed to send registration email",
            extra={"error": str(e), "registration_id": str(registration.id)},
        )

    if registration.status.value == "WAITLISTED":
        message = "Du stehst auf der Warteliste. Sobald ein Platz frei wird, melden wir uns bei dir."
    else:
        message = "Deine Anmeldung ist eingegangen! Du erhältst in Kürze eine Bestätigungsmail."

    return RegistrationSubmitResponse(
        registration=RegistrationResponse(
            id=registration.id,
            event_id=registration.event_id,
            name=registration.name,
            email=registration.email,
            group_size=registration.group_size,
            status=registration.status,
            waitlist_position=registration.waitlist_position,
            registration_token=registration.registration_token,
            registered_at=registration.registered_at,
            responded_at=registration.responded_at,
            promoted=registration.promoted,
        ),
        message=message,
    )


# --- Registration Management Endpoints ---


class EventInfo(BaseModel):
    """Minimal event info for the management page."""

    name: str
    start_at: str
    location: str | None


class ManageRegistrationResponse(BaseModel):
    """Response for registration management page."""

    registration: RegistrationResponse
    event: EventInfo | None = None
    group_members: list[str]
    original_group_size: int
    message: str


class ConfirmWithNamesRequest(BaseModel):
    """Request to confirm participation with group member names."""

    group_members: list[str] = Field(..., min_length=1)


class UpdateGroupMembersRequest(BaseModel):
    """Request to update group member names."""

    group_members: list[str] = Field(..., min_length=1)


@router.get(
    "/registrations/{registration_id}/manage",
)
async def get_registration_manage(
    registration_id: UUID,
    token: str,
) -> ManageRegistrationResponse:
    """Get registration info for the management page.

    Returns registration details including group member names.
    Derives group_members from registrant name if not yet collected.
    """
    registration_service = get_registration_service()

    registration = await registration_service.get_registration_by_token(token)

    if not registration or registration.id != registration_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found or invalid token",
        )

    # Record page view (fire-and-forget, never breaks page load)
    try:
        await registration_service.record_page_view(registration.event_id, registration.id)
    except Exception:
        pass

    # Fetch event details for display
    event_info = None
    try:
        event_svc = get_event_service()
        event = await event_svc.get_event_by_id(registration.event_id)
        if event:
            from ...services.email_service import _format_date
            event_info = EventInfo(
                name=event.name,
                start_at=_format_date(event.start_at),
                location=event.location,
            )
    except Exception:
        pass  # Non-critical — page still works without event info

    # Derive group_members if not yet collected
    if registration.group_members is not None:
        group_members = registration.group_members
    elif registration.group_size == 1:
        group_members = [registration.name]
    else:
        # Group registration without names yet: first slot is registrant, rest empty
        group_members = [registration.name] + [""] * (registration.group_size - 1)

    # Build status message
    messages = {
        "REGISTERED": "Deine Anmeldung ist bei uns eingegangen. Nach Anmeldeschluss wird per Los entschieden — du hörst von uns!",
        "CONFIRMED": "Du hast einen Platz bekommen! Bitte bestätige kurz, dass du dabei bist.",
        "PARTICIPATING": "Du bist dabei!",
        "WAITLISTED": "Du stehst auf der Warteliste. Sobald ein Platz frei wird, melden wir uns bei dir.",
        "CANCELLED": "Deine Anmeldung wurde storniert.",
        "CHECKED_IN": "Du bist eingecheckt. Viel Spaß an Bord!",
    }
    message = messages.get(registration.status.value, f"Status: {registration.status.value}")

    return ManageRegistrationResponse(
        event=event_info,
        registration=RegistrationResponse(
            id=registration.id,
            event_id=registration.event_id,
            name=registration.name,
            email=registration.email,
            group_size=registration.group_size,
            group_members=registration.group_members,
            status=registration.status,
            waitlist_position=registration.waitlist_position,
            registration_token=registration.registration_token,
            registered_at=registration.registered_at,
            responded_at=registration.responded_at,
            promoted=registration.promoted,
        ),
        group_members=group_members,
        original_group_size=registration.group_size,
        message=message,
    )


@router.post(
    "/registrations/{registration_id}/confirm-with-names",
)
async def confirm_with_names(
    registration_id: UUID,
    token: str,
    request_body: ConfirmWithNamesRequest,
) -> ManageRegistrationResponse:
    """Confirm participation and provide group member names.

    Transitions CONFIRMED → PARTICIPATING. Group size may be reduced
    by providing fewer names than the original group_size.
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.confirm_with_names(
        registration_id,
        token,
        request_body.group_members,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return ManageRegistrationResponse(
        registration=RegistrationResponse(
            id=registration.id,
            event_id=registration.event_id,
            name=registration.name,
            email=registration.email,
            group_size=registration.group_size,
            group_members=registration.group_members,
            status=registration.status,
            waitlist_position=registration.waitlist_position,
            registration_token=registration.registration_token,
            registered_at=registration.registered_at,
            responded_at=registration.responded_at,
            promoted=registration.promoted,
        ),
        group_members=registration.group_members or [registration.name],
        original_group_size=registration.group_size,
        message="Danke für deine Bestätigung! Wir freuen uns auf dich.",
    )


@router.put(
    "/registrations/{registration_id}/group-members",
)
async def update_group_members(
    registration_id: UUID,
    token: str,
    request_body: UpdateGroupMembersRequest,
) -> ManageRegistrationResponse:
    """Update group member names or reduce group size.

    Only allowed for PARTICIPATING registrations.
    Group size may decrease but never increase.
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.update_group_members(
        registration_id,
        token,
        request_body.group_members,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return ManageRegistrationResponse(
        registration=RegistrationResponse(
            id=registration.id,
            event_id=registration.event_id,
            name=registration.name,
            email=registration.email,
            group_size=registration.group_size,
            group_members=registration.group_members,
            status=registration.status,
            waitlist_position=registration.waitlist_position,
            registration_token=registration.registration_token,
            registered_at=registration.registered_at,
            responded_at=registration.responded_at,
            promoted=registration.promoted,
        ),
        group_members=registration.group_members or [registration.name],
        original_group_size=registration.group_size,
        message="Änderungen gespeichert.",
    )

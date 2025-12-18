"""Public confirmation API endpoints.

Provides:
- Confirm or decline attendance via unique token (no auth required)
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...models import RegistrationResponse, RegistrationStatus
from ...services.logging import get_logger
from ...services.registration_service import get_registration_service

logger = get_logger(__name__)

router = APIRouter()


class AttendanceResponse(BaseModel):
    """Response for successful attendance confirmation."""

    registration: RegistrationResponse
    message: str


@router.post(
    "/registrations/{registration_id}/confirm",
    response_model=AttendanceResponse,
)
async def confirm_attendance(
    registration_id: UUID,
    token: str,
    response: str,
) -> AttendanceResponse:
    """Confirm or decline attendance using the registration token.

    The token is provided in the confirmation request email.
    Response should be 'yes' or 'no'.

    - YES: Status changes from CONFIRMED to PARTICIPATING
    - NO: Status changes from CONFIRMED to CANCELLED, waitlist is promoted
    """
    # Validate response parameter
    response_lower = response.lower()
    if response_lower not in ("yes", "no"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Response must be 'yes' or 'no'",
        )

    participating = response_lower == "yes"

    registration_service = get_registration_service()

    registration, error = await registration_service.set_attendance_response(
        registration_id,
        token,
        participating,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registration not found or invalid token",
            )
        if "already recorded" in error.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    # Determine response message
    if participating:
        message = "Thank you for confirming your attendance! We look forward to seeing you."
    else:
        message = "Your registration has been cancelled. Thank you for letting us know."

    logger.info(
        "Attendance response received via public API",
        extra={
            "registration_id": str(registration_id),
            "event_id": str(registration.event_id),
            "participating": participating,
            "new_status": registration.status.value,
        },
    )

    return AttendanceResponse(
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
        ),
        message=message,
    )


@router.get(
    "/registrations/{registration_id}/attendance-status",
)
async def get_attendance_status(
    registration_id: UUID,
    token: str,
) -> AttendanceResponse:
    """Get the current attendance status for a registration.

    Used to show the appropriate UI state when user revisits the confirmation link.
    """
    registration_service = get_registration_service()

    registration = await registration_service.get_registration_by_token(token)

    if not registration or registration.id != registration_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found or invalid token",
        )

    # Build message based on status
    if registration.status == RegistrationStatus.CONFIRMED:
        message = "Please confirm your attendance."
    elif registration.status == RegistrationStatus.PARTICIPATING:
        message = "You have confirmed your attendance."
    elif registration.status == RegistrationStatus.CANCELLED:
        message = "You have declined attendance."
    else:
        message = f"Your registration status is: {registration.status.value}"

    return AttendanceResponse(
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
        ),
        message=message,
    )

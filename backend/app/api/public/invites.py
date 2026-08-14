"""Public festival invite API endpoints (spec 019 — festival sidetrack).

A festival event has no public registration link (Ä3, Ä7, Ä11); every
festival registration happens by redeeming an invite through this router.

Provides:
- Invite form-boot info (event + slots, for the registration page)
- Festival registration creation (redeems the invite)
- Self-service festival attendance edit (until the registration deadline)
"""

import re
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...models import (
    EventStatus,
    FestivalAttendancePatch,
    FestivalRegistrationCreate,
    RegistrationResponse,
    RegistrationStatus,
)
from ...services.config import get_settings
from ...services.event_service import get_event_service
from ...services.invite_service import get_invite_service
from ...services.logging import get_logger, token_hint
from ...services.registration_service import compute_very_full_slots, get_registration_service

logger = get_logger(__name__)

router = APIRouter()

_CONTACT_HINT_SUFFIX = " Frag die Person, von der du den Link hast, oder schreib an {contact_hint}."


def _with_contact_hint(base_message: str, contact_hint: str | None) -> str:
    """Append the contact-hint sentence when the event configured one."""
    if contact_hint:
        return base_message + _CONTACT_HINT_SUFFIX.format(contact_hint=contact_hint)
    return base_message


# Guest-facing German copy for the service layer's machine-readable English
# error strings (T108/T109 contract). Keyed by a lowercase fragment; checked
# in order, first match wins. Dynamic numbers are re-inserted below.
_GERMAN_ERROR_COPY: list[tuple[str, str]] = [
    ("group size cannot exceed", "Deine Gruppe darf höchstens {n} Personen umfassen."),
    ("invite not found", "Dieser Einladungslink ist ungültig."),
    ("invite revoked", "Dieser Einladungslink ist ungültig."),
    ("event not found", "Dieser Einladungslink ist ungültig."),
    ("registration is not open", "Die Anmeldung ist für dieses Event nicht geöffnet."),
    ("registration deadline has passed", "Die Anmeldung ist leider geschlossen."),
    ("invite has expired", "Dieser Einladungslink ist abgelaufen."),
    ("exhausted", "Dieser Einladungslink ist bereits vollständig eingelöst."),
    ("unknown attendance slot", "Ungültiger Zeitraum ausgewählt."),
    (
        "phone number is required",
        "Bitte gib deine Telefonnummer für die Stellplatz-Planung an.",
    ),
    ("already registered", "Mit dieser E-Mail-Adresse gibt es schon eine Anmeldung."),
    (
        "group_members must list exactly",
        "Die Anzahl der Begleitungen passt nicht zur Gruppengröße.",
    ),
    ("failed to create registration", "Anmeldung fehlgeschlagen. Bitte versuche es erneut."),
    ("registration not found", "Anmeldung nicht gefunden. Schau nochmal in deiner E-Mail nach."),
    ("invalid token", "Ungültiger Link für diese Anmeldung."),
    ("cancelled registration", "Eine stornierte Anmeldung kann nicht mehr geändert werden."),
    ("not a festival registration", "Diese Anmeldung gehört zu keinem Festival."),
    ("editing deadline has passed", "Die Frist für Änderungen ist leider abgelaufen."),
    ("at least one attendance slot", "Bitte wähle mindestens einen Zeitraum aus."),
    (
        "cannot be removed",
        "Begleitungen können nicht gelöscht werden — bitte lade die Seite neu.",
    ),
    ("exceeds group_size", "Mehr Begleitungen als Plätze in der Gruppe."),
    (
        "tent_count_exceeds_group",
        "Es können nicht mehr Zelte als Personen sein.",
    ),
    (
        "camper_count_exceeds_group",
        "Es können nicht mehr Camper als Personen sein.",
    ),
    (
        "failed to update festival attendance",
        "Speichern hat nicht geklappt. Bitte versuche es erneut.",
    ),
]


def _to_german_detail(error: str, lowered: str) -> str:
    """Translate a service error string into guest-facing German copy.

    Unknown strings pass through unchanged (better a precise English
    message than a wrong German one).
    """
    for fragment, german in _GERMAN_ERROR_COPY:
        if fragment in lowered:
            if "{n}" in german:
                match = re.search(r"(\d+)", error)
                return (
                    german.format(n=match.group(1))
                    if match
                    else "Deine Gruppe ist zu groß für diesen Einladungslink."
                )
            return german
    return error


def _map_festival_error(error: str) -> HTTPException:
    """Map a festival service error string to an HTTPException.

    Mirrors the status branching in `public/registrations.py:99-118`,
    extended with the invite-specific "revoked"/"expired"/"exhausted"
    reasons (T108/T109's error-string contract). The detail is translated
    to German — the status branching still matches on the English
    machine-readable service strings.
    """
    lowered = error.lower()
    detail = _to_german_detail(error, lowered)
    if "not found" in lowered or "revoked" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if "already registered" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if any(keyword in lowered for keyword in ("deadline", "not open", "expired", "exhausted")):
        return HTTPException(status_code=status.HTTP_410_GONE, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class InviteSlotInfo(BaseModel):
    """A selectable festival slot, as shown on the invite form-boot.

    `very_full` (Ä4, if-time) is a soft-warning boolean only — never the
    counts/caps/percentages behind it (those stay admin-only, spec 019
    §invite-boot rule).
    """

    key: str
    label: str
    date: date
    is_night: bool
    very_full: bool


class InviteInfoResponse(BaseModel):
    """Form-boot info for a festival invite link.

    Deliberately has no `valid: bool` field: every invalid state (unknown
    token, revoked, exhausted, expired, deadline passed) already answers
    with 404/410 below, so a 200 response IS the "valid" signal — a
    separate boolean would just be dead weight on the happy path.

    Never exposes `use_count`/`max_uses` — invite redemption counts are
    admin-only (spec 019 §Invite chase view).
    """

    event_name: str
    start_at: datetime
    end_at: datetime | None
    registration_deadline: datetime
    contact_hint: str | None
    participation_hint: str | None
    slots: list[InviteSlotInfo]
    max_group_size: int


class GuestlistSlot(BaseModel):
    """A slot key/label pair, for rendering attendance days on the guestlist."""

    key: str
    label: str


class GuestlistRegistrationRow(BaseModel):
    """One registration on the public guestlist view.

    Deliberately name-only: no emails, phone numbers, or manage tokens —
    the page is shared within the invite group.
    """

    name: str
    group_size: int
    attendance_slots: list[str]


class InviteGuestlistResponse(BaseModel):
    """Public guestlist view for a (contingent) invite link.

    Unlike the form-boot endpoint this deliberately DOES expose
    `use_count`/`max_uses` — the whole point of the page is that the
    contingent owner can watch their allotment fill up. It also stays
    readable when the link is exhausted or the deadline has passed
    (`can_register` flips to False instead of a 410).
    """

    invite_label: str
    event_name: str
    start_at: datetime
    end_at: datetime | None
    max_uses: int
    use_count: int
    max_group_size: int
    can_register: bool
    slots: list[GuestlistSlot]
    registrations: list[GuestlistRegistrationRow]


class FestivalRegistrationSubmitResponse(RegistrationResponse):
    """Successful festival registration: the registration plus a manage URL.

    The success screen shows `manage_url` with a copy button (spec 019
    §Public API).
    """

    manage_url: str


@router.get(
    "/invites/{invite_token}",
    response_model=InviteInfoResponse,
)
async def get_invite_info(invite_token: str) -> InviteInfoResponse:
    """Get form-boot info for a festival invite link.

    Error branching (three DISTINCT 410 states — never shared copy):
    - Unknown token or revoked -> 404
    - Exhausted (`use_count >= max_uses`) -> 410
    - Expired (the invite's own `expires_at` passed) -> 410
    - Registration deadline passed -> 410

    Each 410 gets its own German message, with the contact-hint sentence
    appended when `event.contact_hint` is set.
    """
    invite_service = get_invite_service()
    invite = await invite_service.get_invite_by_token(invite_token)

    if not invite or invite.revoked_at is not None:
        logger.info(
            "Festival invite boot rejected",
            extra={
                "flow": "festival",
                "step": "invite_boot",
                "outcome": "rejected",
                "reason": "revoked" if invite else "not_found",
                "invite_token_hint": token_hint(invite_token),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dieser Einladungslink ist ungültig.",
        )

    event_service = get_event_service()
    event = await event_service.get_event(invite.org_id, invite.event_id)
    if not event:
        logger.warning(
            "Festival invite boot rejected — event missing",
            extra={
                "flow": "festival",
                "step": "invite_boot",
                "outcome": "rejected",
                "reason": "event_not_found",
                "invite_id": str(invite.id),
                "event_id": str(invite.event_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dieser Einladungslink ist ungültig.",
        )

    def _reject_boot(reason: str, detail: str) -> HTTPException:
        logger.info(
            "Festival invite boot rejected",
            extra={
                "flow": "festival",
                "step": "invite_boot",
                "outcome": "rejected",
                "reason": reason,
                "invite_id": str(invite.id),
                "invite_label": invite.label,
                "event_id": str(event.id),
            },
        )
        return HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=_with_contact_hint(detail, event.contact_hint),
        )

    if invite.use_count >= invite.max_uses:
        raise _reject_boot("exhausted", "Dieser Einladungslink ist bereits vollständig eingelöst.")

    now = datetime.now(timezone.utc)

    if invite.expires_at is not None:
        expires_at = invite.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now >= expires_at:
            raise _reject_boot("expired", "Dieser Einladungslink ist abgelaufen.")

    deadline = event.registration_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if now >= deadline:
        raise _reject_boot("deadline_passed", "Die Anmeldung ist leider geschlossen.")

    # Status gate — the SECOND lever, independent of the deadline. New
    # registrations need `OPEN`; `create_festival_registration` already enforces
    # exactly that (registration_service.py:734), so without this check the
    # guest would fill in the whole form and only be rejected on submit.
    #
    # Deliberately NOT applied to editing an existing registration: those paths
    # accept OPEN / REGISTRATION_CLOSED / CONFIRMED on purpose, so closing
    # registration never takes the manage page or the companion ticket page
    # away from people who are already signed up. That separation is the whole
    # point of having a status as well as a deadline — close the door without
    # locking in the people already inside.
    if event.status != EventStatus.OPEN:
        raise _reject_boot("not_open", "Die Anmeldung ist leider geschlossen.")

    # Ä4 (if-time): per-slot "very_full" soft warning, computed from the
    # same headcount aggregation as the admin board (T201) — booleans
    # only, no counts/caps leak into this public payload.
    registration_service = get_registration_service()
    headcount = await registration_service.get_headcount(event)
    very_full_by_key = compute_very_full_slots(headcount)

    logger.info(
        "Festival invite boot served",
        extra={
            "flow": "festival",
            "step": "invite_boot",
            "outcome": "ok",
            "invite_id": str(invite.id),
            "invite_label": invite.label,
            "event_id": str(event.id),
            "use_count": invite.use_count,
            "max_uses": invite.max_uses,
        },
    )

    return InviteInfoResponse(
        event_name=event.name,
        start_at=event.start_at,
        end_at=event.end_at,
        registration_deadline=event.registration_deadline,
        contact_hint=event.contact_hint,
        participation_hint=event.participation_hint,
        slots=[
            InviteSlotInfo(
                key=slot.key,
                label=slot.label,
                date=slot.date,
                is_night=slot.is_night,
                very_full=very_full_by_key.get(slot.key, False),
            )
            for slot in (event.festival_slots or [])
        ],
        max_group_size=invite.max_group_size,
    )


@router.get(
    "/invites/{invite_token}/guestlist",
    response_model=InviteGuestlistResponse,
)
async def get_invite_guestlist(invite_token: str) -> InviteGuestlistResponse:
    """Public guestlist view for an invite link.

    The contingent owner (and anyone they forwarded the link to) sees how
    many registrations their allotment has left and who has registered —
    names and attendance days only, never contact data.

    Unknown or revoked tokens answer 404; every other state (exhausted,
    expired, deadline passed) still renders the list with
    `can_register=False` — checking the status of a full list is the
    page's main job.
    """
    invite_service = get_invite_service()
    invite = await invite_service.get_invite_by_token(invite_token)

    if not invite or invite.revoked_at is not None:
        logger.info(
            "Festival guestlist view rejected",
            extra={
                "flow": "festival",
                "step": "guestlist",
                "outcome": "rejected",
                "reason": "revoked" if invite else "not_found",
                "invite_token_hint": token_hint(invite_token),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dieser Einladungslink ist ungültig.",
        )

    event_service = get_event_service()
    event = await event_service.get_event(invite.org_id, invite.event_id)
    if not event:
        logger.warning(
            "Festival guestlist view rejected — event missing",
            extra={
                "flow": "festival",
                "step": "guestlist",
                "outcome": "rejected",
                "reason": "event_not_found",
                "invite_id": str(invite.id),
                "event_id": str(invite.event_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dieser Einladungslink ist ungültig.",
        )

    can_register = invite.use_count < invite.max_uses and not invite.is_expired(
        event.registration_deadline
    )

    registration_service = get_registration_service()
    all_registrations = await registration_service.list_registrations(event.id)
    rows = [
        GuestlistRegistrationRow(
            name=reg.name,
            group_size=reg.group_size,
            attendance_slots=reg.attendance_slots or [],
        )
        for reg in sorted(all_registrations, key=lambda r: r.registered_at)
        if reg.invite_id == invite.id and reg.status != RegistrationStatus.CANCELLED
    ]

    logger.info(
        "Festival guestlist view served",
        extra={
            "flow": "festival",
            "step": "guestlist",
            "outcome": "ok",
            "invite_id": str(invite.id),
            "invite_label": invite.label,
            "event_id": str(event.id),
            "can_register": can_register,
            "use_count": invite.use_count,
            "max_uses": invite.max_uses,
            "registrations_shown": len(rows),
        },
    )

    return InviteGuestlistResponse(
        invite_label=invite.label,
        event_name=event.name,
        start_at=event.start_at,
        end_at=event.end_at,
        max_uses=invite.max_uses,
        use_count=invite.use_count,
        max_group_size=invite.max_group_size,
        can_register=can_register,
        slots=[GuestlistSlot(key=slot.key, label=slot.label) for slot in (event.festival_slots or [])],
        registrations=rows,
    )


@router.post(
    "/invites/{invite_token}/registrations",
    response_model=FestivalRegistrationSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_festival_registration(
    invite_token: str,
    registration_data: FestivalRegistrationCreate,
) -> FestivalRegistrationSubmitResponse:
    """Redeem an invite and create a festival registration.

    Registrations start directly in PARTICIPATING — festivals have no
    lottery/waitlist. F2 is sent by the service (never-fail).
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.create_festival_registration(
        invite_token,
        registration_data,
    )

    if error:
        logger.info(
            "Festival registration rejected",
            extra={
                "flow": "festival",
                "step": "register",
                "outcome": "rejected",
                "reason": error,
                "invite_token_hint": token_hint(invite_token),
                "group_size": registration_data.group_size,
            },
        )
        raise _map_festival_error(error)

    logger.info(
        "Festival registration submitted via public API",
        extra={
            "flow": "festival",
            "step": "register",
            "outcome": "ok",
            "registration_id": str(registration.id),
            "event_id": str(registration.event_id),
            "invite_id": str(registration.invite_id) if registration.invite_id else None,
            "invite_label": registration.invite_label,
            "tier": registration.tier,
            "group_size": registration.group_size,
            "attendance_slots": registration.attendance_slots or [],
            "tent_count": registration.tent_count,
            "camper_count": registration.camper_count,
        },
    )

    settings = get_settings()
    manage_url = f"{settings.base_url}/registration/{registration.id}?token={registration.registration_token}"

    base = RegistrationResponse.model_validate(registration)
    return FestivalRegistrationSubmitResponse(**base.model_dump(), manage_url=manage_url)


@router.patch(
    "/registrations/{registration_id}/festival-attendance",
    response_model=RegistrationResponse,
)
async def update_festival_attendance(
    registration_id: UUID,
    token: str,
    patch: FestivalAttendancePatch,
) -> RegistrationResponse:
    """Self-service edit of a festival registration's attendance.

    Allowed until the registration deadline (= festival end, Ä14). Sends
    F3 (never-fail) on success. `overnight_approved` can never be set here
    (Ä17) — `FestivalAttendancePatch` forbids the field outright.
    """
    registration_service = get_registration_service()

    registration, error = await registration_service.update_festival_attendance(
        registration_id,
        token,
        patch,
    )

    if error:
        logger.info(
            "Festival attendance edit rejected",
            extra={
                "flow": "festival",
                "step": "edit",
                "outcome": "rejected",
                "reason": error,
                "registration_id": str(registration_id),
                "fields": sorted(patch.model_dump(exclude_unset=True).keys()),
            },
        )
        raise _map_festival_error(error)

    logger.info(
        "Festival attendance edited via public API",
        extra={
            "flow": "festival",
            "step": "edit",
            "outcome": "ok",
            "registration_id": str(registration.id),
            "event_id": str(registration.event_id),
            "group_size": registration.group_size,
            "attendance_slots": registration.attendance_slots or [],
            "tent_count": registration.tent_count,
            "camper_count": registration.camper_count,
        },
    )

    return RegistrationResponse.model_validate(registration)

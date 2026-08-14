"""Public registration API endpoints.

Provides:
- Get event info for registration form
- Submit registration (no auth required)
- Registration management (confirm with names, update group members)
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ...models import (
    EventPublic,
    EventType,
    Registration,
    RegistrationCreate,
    RegistrationResponse,
    RegistrationStatus,
)
from ...services.email_service import _format_date_range, get_email_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger
from ...services.registration_service import get_registration_service
from ...services.ticket_signing import build_person_tickets, verify_person_page_token

logger = get_logger(__name__)


def _format_event_period(event) -> str:
    """German event period for the companion ticket page (spec 020).

    Reuses the email formatter so the page and F5 never disagree about the
    festival's dates.
    """
    return _format_date_range(event.start_at, event.end_at)


def _festival_edit_open(event) -> bool:
    """Whether festival self-service edits are still allowed (spec 021).

    Same lifecycle gate `update_festival_attendance` enforces on save — mirrored
    here so a companion's page can hide controls it would refuse anyway rather
    than letting them tick boxes into a rejection.
    """
    from datetime import UTC, datetime

    from ...models import EventStatus

    if event.status not in {
        EventStatus.OPEN,
        EventStatus.REGISTRATION_CLOSED,
        EventStatus.CONFIRMED,
    }:
        return False
    deadline = event.registration_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return datetime.now(UTC) < deadline


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


class FestivalSlotInfo(BaseModel):
    """A selectable festival slot, as shown on the manage page."""

    key: str
    label: str
    date: date
    is_night: bool


class EventInfo(BaseModel):
    """Minimal event info for the management page."""

    name: str
    start_at: str
    location: str | None
    # Festival sidetrack (spec 019) — additive optional fields
    event_type: str = EventType.SINGLE.value
    contact_hint: str | None = None
    participation_hint: str | None = None
    festival_slots: list[FestivalSlotInfo] | None = None


class QrPayload(BaseModel):
    """A freshly-signed per-person check-in QR payload (spec 019 §P3)."""

    person_index: int
    name: str
    code: str


class ManageRegistrationResponse(BaseModel):
    """Response for registration management page."""

    registration: RegistrationResponse
    event: EventInfo | None = None
    # `None` entries are tombstones for removed festival members (T109) —
    # indices never shift; SINGLE flows never contain None.
    group_members: list[str | None]
    # Spec 020 — index-aligned with `group_members` above. Only ever populated
    # for FESTIVAL registrations, where the derived list equals the stored
    # `registration.group_members` exactly, so the indices match. Lets the
    # manage page show per-companion „Code geschickt" vs „QR weiterleiten".
    group_member_emails: list[str | None] | None = None
    original_group_size: int
    message: str
    # Festival sidetrack (spec 019) — additive optional fields
    attendance_slots: list[str] | None = None
    tent_count: int | None = None
    camper_count: int | None = None
    phone: str | None = None
    # Ä17: read-only for guests — drives the „angefragt"/„zugesagt" display;
    # no public endpoint ever accepts this field.
    overnight_approved: bool = False
    # F9, also read-only: without it a refused guest would keep reading
    # „angefragt" on their own page forever, even though they were told no.
    overnight_declined: bool = False
    # Registration deadline isoformat for FESTIVAL events, None for SINGLE.
    editable_until: str | None = None
    # Effective group allowance for FESTIVAL registrations: the invite's
    # `max_group_size`, floored by the group's CURRENT size so the
    # grandfathering rule holds (lowering an invite's allowance never
    # invalidates a bigger existing group). Companions allowed = this minus 1,
    # so `1` means "no companions" and the UI hides the add-person control.
    max_group_size: int | None = None
    # T308: freshly signed on every GET — never cached/persisted. None for
    # non-FESTIVAL events and CANCELLED registrations (no entry codes).
    qr_payloads: list[QrPayload] | None = None


def _build_qr_payloads(secret: str, registration: Registration) -> list[QrPayload]:
    """Build freshly-signed per-person check-in QR payloads (spec 019 §P3, T308).

    Signed fresh every call so slot/group/overnight edits always show up on
    the next render. Delegates to `build_person_tickets`, shared with the
    confirmation email's QR image generation.
    """
    tickets = build_person_tickets(
        secret,
        registration.id,
        registration.name,
        registration.group_members,
        registration.attendance_slots,
        registration.overnight_approved,
        registration.member_slots,
    )
    return [QrPayload(person_index=t.person_index, name=t.name, code=t.code) for t in tickets]


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
    editable_until = None
    max_group_size: int | None = None
    qr_payloads: list[QrPayload] | None = None
    try:
        event_svc = get_event_service()
        event = await event_svc.get_event_by_id(registration.event_id)
        if event:
            is_festival = event.event_type == EventType.FESTIVAL
            event_info = EventInfo(
                name=event.name,
                start_at=event.start_at.isoformat(),
                location=event.location,
                event_type=event.event_type.value,
                contact_hint=event.contact_hint,
                participation_hint=event.participation_hint,
                festival_slots=(
                    [
                        FestivalSlotInfo(
                            key=slot.key, label=slot.label, date=slot.date, is_night=slot.is_night,
                        )
                        for slot in (event.festival_slots or [])
                    ]
                    if is_festival
                    else None
                ),
            )
            if is_festival:
                editable_until = event.registration_deadline.isoformat()

                # Effective group allowance, so the page knows whether "add a
                # person" is even possible. Floored by the CURRENT group size to
                # honour grandfathering (spec 019 §Invite): lowering an invite's
                # allowance never invalidates a bigger existing group. Mirrors
                # `update_festival_attendance`'s `allowed_max_group_size`, which
                # is what actually enforces this on save.
                max_group_size = registration.group_size
                if registration.invite_id is not None:
                    try:
                        from ...services.invite_service import get_invite_service

                        invite = await get_invite_service().get_invite(
                            event.id, registration.invite_id,
                        )
                        if invite is not None:
                            max_group_size = max(
                                registration.group_size, invite.max_group_size,
                            )
                    except Exception:
                        pass  # Non-critical — fall back to the current size.

                # T308: freshly signed per-person QR payloads for the entry
                # codes section. Signed fresh on every GET (never cached) so
                # slot/group/overnight edits always show up on next render.
                if registration.status != RegistrationStatus.CANCELLED:
                    credentialed_event = await event_svc.ensure_gate_credentials(
                        event.org_id, event.id,
                    )
                    if credentialed_event is not None and credentialed_event.ticket_secret:
                        qr_payloads = _build_qr_payloads(
                            credentialed_event.ticket_secret, registration,
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
            group_member_emails=registration.group_member_emails,
            # Spec 021: LOAD-BEARING. The manage page seeds its editable
            # per-person day map from this field and sends the whole map back
            # on save, so omitting it here does not merely hide the days — it
            # makes the next save send `{}` and DELETE every override a
            # companion set on their own ticket page. Keep it in this kwarg
            # list; do not "clean up" by dropping it.
            member_slots=registration.member_slots,
            status=registration.status,
            waitlist_position=registration.waitlist_position,
            registration_token=registration.registration_token,
            registered_at=registration.registered_at,
            responded_at=registration.responded_at,
            promoted=registration.promoted,
        ),
        group_members=group_members,
        group_member_emails=registration.group_member_emails,
        original_group_size=registration.group_size,
        message=message,
        attendance_slots=registration.attendance_slots,
        tent_count=registration.tent_count,
        camper_count=registration.camper_count,
        phone=registration.phone,
        overnight_approved=registration.overnight_approved,
        overnight_declined=registration.overnight_declined,
        editable_until=editable_until,
        max_group_size=max_group_size,
        qr_payloads=qr_payloads,
    )


class PersonTicketResponse(BaseModel):
    """One companion's own ticket page payload (spec 020, extended by 021).

    Deliberately minimal. Absent by design: the group's `registration_token`,
    every other member's name, phone numbers, e-mail addresses, and the
    tent/camper request. A companion may read and edit exactly one person's
    data — their own — and nothing else in the group.
    """

    person_index: int
    name: str
    event_name: str
    event_period: str
    slot_labels: list[str]
    group_size: int
    contact_name: str
    contact_hint: str | None = None
    participation_hint: str | None = None
    # Freshly signed on every GET, so a rename or slot edit never leaves the
    # companion holding a code the gate rejects. Empty when cancelled.
    ticket_code: str = ""
    cancelled: bool = False
    # Spec 021 — the editable surface: every slot the event offers, plus the
    # keys THIS person is currently coming on.
    all_slots: list[FestivalSlotInfo] = Field(default_factory=list)
    own_slots: list[str] = Field(default_factory=list)
    editable: bool = False


class PersonSlotsPatch(BaseModel):
    """A companion setting their own attendance days (spec 021 E2)."""

    model_config = ConfigDict(extra="forbid")

    attendance_slots: list[str] = Field(..., min_length=1)


@router.get(
    "/tickets/{event_id}/{registration_id}/{person_index}",
)
async def get_person_ticket(
    event_id: UUID,
    registration_id: UUID,
    person_index: int,
    token: str,
) -> PersonTicketResponse:
    """Read-only ticket page for one companion (spec 020).

    Authenticated by a `person_page_token` — an HMAC over the group's
    registration token scoped to this one `person_index`. That token is
    read-only by construction: there is no write endpoint that accepts it, and
    it cannot be reversed into the group token that could cancel everyone.

    `event_id` is in the path because registrations are keyed
    `pk=EVENT#{event_id}` / `sk=REG#{id}` — without it this would need a table
    scan on a public, unauthenticated endpoint. The URL is only ever clicked
    from a mail, so the extra segment costs nothing.

    Every rejection returns the same bare 404 — unknown registration, wrong
    token, index 0 (the contact, who uses the manage page), out of range, or a
    tombstoned member. Distinguishing them would turn this into an oracle for
    probing group sizes and membership.
    """
    registration_service = get_registration_service()
    registration = await registration_service.get_registration(event_id, registration_id)

    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Eintritts-Code nicht gefunden",
    )

    if not registration:
        raise not_found

    # person_index 0 is the contact person — they have the manage page, and
    # issuing them a read-only view here would only confuse.
    if person_index < 1:
        raise not_found

    # Verified against the address CURRENTLY stored at this index, so replacing
    # the occupant (a different person, a different address) invalidates the old
    # link rather than showing the newcomer's name and gate-valid QR to whoever
    # held the previous one.
    stored_emails = registration.group_member_emails or []
    current_email = (
        stored_emails[person_index - 1] if person_index - 1 < len(stored_emails) else None
    )
    if not verify_person_page_token(
        registration.registration_token, person_index, current_email, token,
    ):
        logger.info(
            "Person ticket access denied",
            extra={
                "flow": "festival", "step": "person_ticket", "outcome": "invalid",
                "reason": "bad_token", "registration_id": str(registration_id),
                "person_index": person_index,
            },
        )
        raise not_found

    members = registration.group_members or []
    if person_index > len(members) or members[person_index - 1] is None:
        raise not_found

    event_svc = get_event_service()
    event = await event_svc.get_event_by_id(event_id)
    if not event or event.event_type != EventType.FESTIVAL:
        raise not_found

    # Spec 021: this person's own days, not the group's.
    slot_keys = set(registration.effective_member_slots(person_index))
    slot_labels = [slot.label for slot in (event.festival_slots or []) if slot.key in slot_keys]

    cancelled = registration.status == RegistrationStatus.CANCELLED
    ticket_code = ""
    if not cancelled:
        # Signed fresh, exactly like the manage page — a rename or slot edit
        # must never leave this page showing a code the gate would reject.
        credentialed_event = await event_svc.ensure_gate_credentials(event.org_id, event.id)
        if credentialed_event is not None and credentialed_event.ticket_secret:
            ticket = next(
                (
                    t
                    for t in build_person_tickets(
                        credentialed_event.ticket_secret,
                        registration.id,
                        registration.name,
                        registration.group_members,
                        registration.attendance_slots,
                        registration.overnight_approved,
                        registration.member_slots,
                    )
                    if t.person_index == person_index
                ),
                None,
            )
            if ticket is not None:
                ticket_code = ticket.code

    logger.info(
        "Person ticket served",
        extra={
            "flow": "festival", "step": "person_ticket", "outcome": "ok",
            "registration_id": str(registration_id), "person_index": person_index,
            "cancelled": cancelled,
        },
    )

    return PersonTicketResponse(
        person_index=person_index,
        name=members[person_index - 1],
        event_name=event.name,
        event_period=_format_event_period(event),
        slot_labels=slot_labels,
        group_size=registration.group_size,
        contact_name=registration.name,
        contact_hint=event.contact_hint,
        participation_hint=event.participation_hint,
        ticket_code=ticket_code,
        cancelled=cancelled,
        # Spec 021 — the page renders every slot and ticks this person's own.
        all_slots=[
            FestivalSlotInfo(
                key=slot.key, label=slot.label, date=slot.date, is_night=slot.is_night,
            )
            for slot in (event.festival_slots or [])
        ],
        own_slots=registration.effective_member_slots(person_index),
        editable=not cancelled and _festival_edit_open(event),
    )


@router.patch(
    "/tickets/{event_id}/{registration_id}/{person_index}",
)
async def update_person_slots(
    event_id: UUID,
    registration_id: UUID,
    person_index: int,
    token: str,
    request_body: PersonSlotsPatch,
) -> PersonTicketResponse:
    """A companion sets their own attendance days (spec 021 E2).

    Scoped by the per-person token to exactly one index — it cannot reach
    another person's days, the group's grid, any name, or the group's status.
    Sends no mail: a day change is low signal, and notifying the contact on
    every tick would make the feature a nuisance.
    """
    registration_service = get_registration_service()
    updated, error = await registration_service.set_person_slots(
        event_id, registration_id, person_index, token, request_body.attendance_slots,
    )
    if error:
        raise _person_ticket_error(error)

    return await get_person_ticket(
        event_id=event_id,
        registration_id=registration_id,
        person_index=person_index,
        token=token,
    )


@router.post(
    "/tickets/{event_id}/{registration_id}/{person_index}/cancel",
)
async def cancel_person_ticket(
    event_id: UUID,
    registration_id: UUID,
    person_index: int,
    token: str,
) -> dict:
    """A companion removes themselves from the group (spec 021 E3).

    Tombstones their entry so everyone else's `person_index` — and therefore
    every already-issued QR — stays valid, clears their address (which also
    retires this very page), and tells the contact via F7.
    """
    registration_service = get_registration_service()
    updated, error = await registration_service.cancel_person(
        event_id, registration_id, person_index, token,
    )
    if error:
        raise _person_ticket_error(error)

    return {
        "cancelled": True,
        "group_size": updated.group_size,
        "message": "Du bist abgemeldet. Dein Eintritts-Code gilt nicht mehr.",
    }


def _person_ticket_error(error: str) -> HTTPException:
    """Map a companion self-service error onto a response.

    "not found" stays a bare 404 with the same wording as the read path — the
    endpoint must not become an oracle for who is in a group. The deadline and
    cancelled branches are distinguishable because the holder is, by then, a
    verified companion and needs to know why their save was refused.
    """
    if error == "deadline":
        return HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Änderungen sind nicht mehr möglich — melde dich bei der Person, die dich angemeldet hat.",
        )
    if error == "cancelled":
        return HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Diese Anmeldung ist storniert.",
        )
    if error == "not found":
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Eintritts-Code nicht gefunden",
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)


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

"""Admin festival API endpoints (spec 019 — festival sidetrack).

Provides:
- Festival event CRUD (this is the only UI for creating/editing FESTIVAL
  events — the regular events admin never sees them, Ä-isolation)
- Invite batch create / list / patch / send-email / mark-sent (Ä7)

Guards: writes require OWNER/ADMIN, reads also allow VIEWER (pattern:
`admin/events.py`). A dedicated FESTIVAL role is deferred (Ä1).

Declaration-order trap (same as the CSV export route in `events.py:1113`):
the literal `/events` routes are declared BEFORE the parameterized
`GET /{event_id}` below — otherwise a request to `GET /events` would be
swallowed as `GET /{event_id}` with `event_id="events"` (and 422 on the
UUID parse) instead of hitting the list handler.
"""

import csv
import io
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...models import (
    Event,
    EventCreate,
    EventStatus,
    EventType,
    EventUpdate,
    FestivalSlot,
    Invite,
    InviteBatchCreate,
    InviteUpdate,
    RegistrationResponse,
    RegistrationStatus,
)
from ...services.auth import AdminRole, CurrentUser, require_role
from ...services.checkin_service import get_checkin_service
from ...services.config import get_settings
from ...services.email_service import get_email_service
from ...services.event_service import _event_to_item, _generate_link_token, get_event_service
from ...services.invite_service import get_invite_service
from ...services.logging import get_logger, log_admin_action
from ...services.registration_service import (
    build_gate_rows,
    get_registration_service,
)

logger = get_logger(__name__)

router = APIRouter()


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


# --- Festival event CRUD ---


class FestivalEventResponse(BaseModel):
    """Festival event settings, as shown in the festival admin section."""

    id: UUID
    name: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime | None
    capacity: int
    registration_deadline: datetime
    status: EventStatus
    event_type: EventType
    festival_slots: list[FestivalSlot] | None
    contact_hint: str | None
    participation_hint: str | None
    created_at: datetime
    published_at: datetime | None
    cancelled_at: datetime | None


class FestivalEventListResponse(BaseModel):
    """Response for the festival events list."""

    items: list[FestivalEventResponse]
    total: int


class EventStatusUpdate(BaseModel):
    """Request body for a festival event status transition."""

    status: EventStatus


def _event_to_response(event: Event) -> FestivalEventResponse:
    """Convert an Event model to a FestivalEventResponse."""
    return FestivalEventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        end_at=event.end_at,
        capacity=event.capacity,
        registration_deadline=event.registration_deadline,
        status=event.status,
        event_type=event.event_type,
        festival_slots=event.festival_slots,
        contact_hint=event.contact_hint,
        participation_hint=event.participation_hint,
        created_at=event.created_at,
        published_at=event.published_at,
        cancelled_at=event.cancelled_at,
    )


async def _get_festival_event_or_404(org_id: UUID, event_id: UUID) -> Event:
    """Fetch an event and 404 unless it exists and is a FESTIVAL event.

    Keeps this router scoped strictly to festival events (Ä-isolation) —
    a SINGLE event ID (or one from another org) is treated as not found.
    """
    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event or event.event_type != EventType.FESTIVAL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Festival event not found",
        )
    return event


@router.post(
    "/events",
    response_model=FestivalEventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def create_festival_event(
    event_data: EventCreate,
    user: CurrentUser,
) -> FestivalEventResponse:
    """Create a new festival event (DRAFT status).

    Forces `event_type=FESTIVAL` regardless of what the client sent —
    `create_event` (T103) then suppresses the registration link token and
    disables `autopromote_waitlist` for it.
    """
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)

    forced = event_data.model_copy(update={"event_type": EventType.FESTIVAL})

    event_service = get_event_service()
    event = await event_service.create_event(org_id, forced, admin_id)

    log_admin_action("festival.event.create", user.email, str(event.id), {"event_name": event.name})

    return _event_to_response(event)


@router.get(
    "/events",
    response_model=FestivalEventListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_festival_events(user: CurrentUser) -> FestivalEventListResponse:
    """List all festival events for the organization.

    See module docstring — this MUST stay declared before `GET /{event_id}`.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    events = await event_service.list_events(org_id)
    festivals = [event for event in events if event.event_type == EventType.FESTIVAL]

    items = [_event_to_response(event) for event in festivals]
    return FestivalEventListResponse(items=items, total=len(items))


@router.get(
    "/{event_id}",
    response_model=FestivalEventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def get_festival_event(event_id: UUID, user: CurrentUser) -> FestivalEventResponse:
    """Get a festival event's settings by ID."""
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)
    return _event_to_response(event)


@router.put(
    "/{event_id}",
    response_model=FestivalEventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def update_festival_event(
    event_id: UUID,
    update_data: EventUpdate,
    user: CurrentUser,
) -> FestivalEventResponse:
    """Update a festival event's settings (only in DRAFT or OPEN status).

    Covers `festival_slots`, `end_at`, `contact_hint`, `participation_hint`,
    `registration_deadline`, `capacity` — the Ä8 capacity cap and the slot
    / required-deadline / end_at validators (T102) apply here too, via
    `EventUpdate`'s own model validator.
    """
    org_id = _get_org_id(user)
    await _get_festival_event_or_404(org_id, event_id)

    event_service = get_event_service()
    try:
        event = await event_service.update_event(org_id, event_id, update_data)
    except ValueError as e:
        # Ä8: capacity exceeds the persisted event type's cap
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    if not event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event not found or cannot be updated (must be in DRAFT or OPEN status)",
        )

    log_admin_action("festival.event.update", user.email, str(event_id))

    return _event_to_response(event)


@router.post(
    "/{event_id}/status",
    response_model=FestivalEventResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def set_festival_event_status(
    event_id: UUID,
    body: EventStatusUpdate,
    user: CurrentUser,
) -> FestivalEventResponse:
    """Transition a festival event's status.

    Uses the domain model's own `can_transition_to`/`transition_to`
    (event.py:107-129); 409 on an invalid transition.
    """
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    if not event.can_transition_to(body.status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition from {event.status.value} to {body.status.value}",
        )

    updated = event.transition_to(body.status)

    event_service = get_event_service()
    event_service.table.put_item(Item=_event_to_item(updated))

    log_admin_action(
        "festival.event.status",
        user.email,
        str(event_id),
        {"from": event.status.value, "to": updated.status.value},
    )

    return _event_to_response(updated)


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def delete_festival_event(
    event_id: UUID,
    user: CurrentUser,
) -> None:
    """Delete a festival event (only allowed for CANCELLED status).

    Mirrors `DELETE /api/admin/events/{event_id}`'s CANCELLED-only guard,
    but deletion here additionally purges every co-located row the
    festival owns — invites, registrations, check-in scans, and messages
    (see `EventService.delete_festival_event`). Permanent, cannot be undone.
    """
    org_id = _get_org_id(user)
    await _get_festival_event_or_404(org_id, event_id)

    event_service = get_event_service()
    try:
        deleted = await event_service.delete_festival_event(org_id, event_id)
    except ValueError as e:
        # Wrong status (not CANCELLED) — German detail, mirrors the
        # invalid-transition 409 above.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Festival event not found",
        )

    log_admin_action("festival.delete", user.email, str(event_id))


# --- Invites ---


class InviteBatchRow(BaseModel):
    """One created invite, as returned right after a batch create."""

    id: UUID
    label: str
    batch_label: str | None
    email: str | None
    tier: str
    max_uses: int
    max_group_size: int
    token: str
    url: str


class InviteBatchResponse(BaseModel):
    """Response for a batch invite create."""

    items: list[InviteBatchRow]
    emailed_count: int = 0  # How many F1 invitations were auto-sent on create.


class InviteStatusRow(BaseModel):
    """One invite's chase-view status row."""

    id: UUID
    label: str
    batch_label: str | None
    tier: str
    email: str | None
    max_uses: int
    use_count: int
    max_group_size: int
    sent_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None
    expired: bool
    last_registered_at: datetime | None
    url: str


class InviteListResponse(BaseModel):
    """Response for the invite chase-view list."""

    items: list[InviteStatusRow]


class InvitePatchRequest(InviteUpdate):
    """PATCH body: partial `InviteUpdate` fields, or `{"revoked": true}`.

    Inherits `InviteUpdate`'s `extra="forbid"`. There is no rotate endpoint
    (Ä3) — revocation is the only lifecycle action besides field edits.
    """

    revoked: bool | None = None


def _invite_to_row(invite: Invite, event: Event) -> InviteStatusRow:
    """Convert an Invite model to a chase-view status row."""
    settings = get_settings()
    return InviteStatusRow(
        id=invite.id,
        label=invite.label,
        batch_label=invite.batch_label,
        tier=invite.tier,
        email=invite.email,
        max_uses=invite.max_uses,
        use_count=invite.use_count,
        max_group_size=invite.max_group_size,
        sent_at=invite.sent_at,
        revoked_at=invite.revoked_at,
        expires_at=invite.expires_at,
        expired=invite.is_expired(event.registration_deadline),
        last_registered_at=invite.last_registered_at,
        url=f"{settings.base_url}/invite/{invite.token}",
    )


@router.post(
    "/{event_id}/invites",
    response_model=InviteBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def create_invites(
    event_id: UUID,
    batch: InviteBatchCreate,
    user: CurrentUser,
) -> InviteBatchResponse:
    """Batch-create invites (a Kontingent) for a festival event."""
    org_id = _get_org_id(user)
    admin_id = _get_admin_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    invite_service = get_invite_service()
    invites = await invite_service.create_invites_batch(org_id, event_id, batch, admin_id)

    # Optional auto-send (create-modal checkbox): fire F1 to every invite that
    # has an email and stamp `sent_at`. Resilient — a single failed send never
    # fails the whole create; the row simply stays "offen" for a manual retry.
    emailed_count = 0
    if batch.send_emails:
        email_service = get_email_service()
        for invite in invites:
            if not invite.email:
                continue
            try:
                sent = await email_service.send_festival_invitation(event, invite)
                if sent:
                    await invite_service.mark_sent(event_id, invite.id)
                    emailed_count += 1
            except Exception:
                logger.warning(
                    "Auto-send of festival invitation failed",
                    extra={
                        "flow": "festival", "step": "invite_send", "outcome": "error",
                        "event_id": str(event_id), "invite_id": str(invite.id),
                    },
                )

    log_admin_action(
        "festival.invites.create",
        user.email,
        str(event_id),
        {"count": len(invites), "batch_label": batch.batch_label, "emailed": emailed_count},
    )

    settings = get_settings()
    items = [
        InviteBatchRow(
            id=invite.id,
            label=invite.label,
            batch_label=invite.batch_label,
            email=invite.email,
            tier=invite.tier,
            max_uses=invite.max_uses,
            max_group_size=invite.max_group_size,
            token=invite.token,
            url=f"{settings.base_url}/invite/{invite.token}",
        )
        for invite in invites
    ]
    return InviteBatchResponse(items=items, emailed_count=emailed_count)


@router.get(
    "/{event_id}/invites",
    response_model=InviteListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_invites(event_id: UUID, user: CurrentUser) -> InviteListResponse:
    """List all invites for a festival event (chase view)."""
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    invite_service = get_invite_service()
    invites = await invite_service.list_invites(event_id)

    return InviteListResponse(items=[_invite_to_row(invite, event) for invite in invites])


@router.patch(
    "/{event_id}/invites/{invite_id}",
    response_model=InviteStatusRow,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def patch_invite(
    event_id: UUID,
    invite_id: UUID,
    body: InvitePatchRequest,
    user: CurrentUser,
) -> InviteStatusRow:
    """Edit an invite, or revoke it with `{"revoked": true}`.

    No rotate endpoint (Ä3).
    """
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    invite_service = get_invite_service()

    if body.revoked:
        invite = await invite_service.revoke_invite(event_id, invite_id)
        action = "festival.invites.revoke"
    else:
        update_fields = body.model_dump(exclude_unset=True, exclude={"revoked"})
        invite = await invite_service.update_invite(event_id, invite_id, InviteUpdate(**update_fields))
        action = "festival.invites.update"

    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    log_admin_action(action, user.email, str(invite_id), {"event_id": str(event_id)})

    return _invite_to_row(invite, event)


@router.post(
    "/{event_id}/invites/{invite_id}/send-email",
    response_model=InviteStatusRow,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def send_invite_email(
    event_id: UUID,
    invite_id: UUID,
    user: CurrentUser,
) -> InviteStatusRow:
    """Send the festival invitation email (F1) and stamp `sent_at`.

    The greeting always uses the invite label (the addressee). Single-use
    invites get the "persönlich, nicht weiterleiten" sentence; contingent
    invites (`max_uses > 1`) instead get their numbers and the guestlist
    link — `send_festival_invitation` derives all of it from the invite.
    """
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    invite_service = get_invite_service()
    invite = await invite_service.get_invite(event_id, invite_id)
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if not invite.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite has no email address",
        )

    email_service = get_email_service()
    await email_service.send_festival_invitation(event, invite)

    updated = await invite_service.mark_sent(event_id, invite_id)

    log_admin_action("festival.invites.send_email", user.email, str(invite_id), {"event_id": str(event_id)})

    return _invite_to_row(updated, event)


@router.post(
    "/{event_id}/invites/{invite_id}/mark-sent",
    response_model=InviteStatusRow,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def mark_invite_sent(
    event_id: UUID,
    invite_id: UUID,
    user: CurrentUser,
) -> InviteStatusRow:
    """Lightweight `sent_at` stamp for the copy-row action (Ä7).

    Idempotent — a second call leaves the first timestamp untouched.
    """
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    invite_service = get_invite_service()
    updated = await invite_service.mark_sent(event_id, invite_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    log_admin_action("festival.invites.mark_sent", user.email, str(invite_id), {"event_id": str(event_id)})

    return _invite_to_row(updated, event)


# --- Headcount board (Ä15/Ä17) ---


@router.get(
    "/{event_id}/headcount",
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def get_festival_headcount(event_id: UUID, user: CurrentUser) -> dict:
    """Slot x tier headcount board (T201): per-slot totals with `by_tier`,
    caps/`overbooked`, `accommodation_totals` split into requested/approved
    (Ä17), and the `unknown_slots` diagnostic bucket. CANCELLED
    registrations are excluded everywhere. Read-only — VIEWER may call it.

    Delegates verbatim to `RegistrationService.get_headcount`, additively
    extended (T313) with an `arrivals` block from the check-in log —
    `{"total": <distinct persons ever checked in>, "per_day": {...}}`,
    via `CheckinService.get_arrivals_summary`. Only present when there is
    at least one scan; a SINGLE event never reaches this route (404
    above) so the check-in log is never queried for non-festival events.
    """
    org_id = _get_org_id(user)

    event_service = get_event_service()
    event = await event_service.get_event(org_id, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.event_type != EventType.FESTIVAL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kein Festival-Event")

    registration_service = get_registration_service()
    headcount = await registration_service.get_headcount(event)

    checkin_service = get_checkin_service()
    arrivals = await checkin_service.get_arrivals_summary(event_id)
    if arrivals["total"]:
        headcount["arrivals"] = arrivals

    return headcount


# --- Gate token (Einlass / scanner link, spec 019 §P3) ---


class GateTokenResponse(BaseModel):
    """The check-in scanner link for a festival event.

    Never includes `ticket_secret` — that stays server-side only, exposed
    solely via the gate-token-authenticated boot call (T307).
    """

    gate_url: str


@router.get(
    "/{event_id}/gate-token",
    response_model=GateTokenResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def get_gate_token(event_id: UUID, user: CurrentUser) -> GateTokenResponse:
    """Lazily generate (if missing) and return the scanner gate link.

    Idempotent — a second call returns the same URL (`ensure_gate_credentials`
    only fills in fields that are still None).
    """
    org_id = _get_org_id(user)
    await _get_festival_event_or_404(org_id, event_id)

    event_service = get_event_service()
    event = await event_service.ensure_gate_credentials(org_id, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Festival event not found")

    settings = get_settings()
    return GateTokenResponse(gate_url=f"{settings.base_url}/checkin/{event.gate_token}")


@router.post(
    "/{event_id}/gate-token/rotate",
    response_model=GateTokenResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def rotate_gate_token(event_id: UUID, user: CurrentUser) -> GateTokenResponse:
    """Rotate the gate token — the old scanner link dies immediately.

    `ticket_secret` is left untouched: rotating it would invalidate every
    QR code already handed out to guests.
    """
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    updated = event.model_copy(update={"gate_token": _generate_link_token()})

    event_service = get_event_service()
    event_service.table.put_item(Item=_event_to_item(updated))

    log_admin_action("festival.gate_token.rotate", user.email, str(event_id))

    settings = get_settings()
    return GateTokenResponse(gate_url=f"{settings.base_url}/checkin/{updated.gate_token}")


# --- Gate CSV export (Ä9 floor, Ä14) ---


def _sanitize_filename_slug(name: str) -> str:
    """ASCII-safe filename slug (mirror events.py:1084-1093).

    Content-Disposition filenames must stay ASCII-safe — umlauts get
    transliterated rather than percent-escaped or dropped.
    """
    filename_map = str.maketrans(
        {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"},
    )
    return (
        name.translate(filename_map)
        .replace(" ", "_")
        .encode("ascii", "replace")
        .decode("ascii")
    )


@router.get(
    "/{event_id}/registrations/export-csv",
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def export_gate_csv(
    event_id: UUID,
    user: CurrentUser,
    view: str = "gate",
) -> StreamingResponse:
    """Export the printable gate list (``view=gate``) as CSV.

    **Declaration-order trap** (same shape as the boarding-list export at
    `events.py:1113-1114`): this literal route MUST stay declared before any
    ``/{event_id}/registrations/{registration_id}`` route added to this
    router (see `list_festival_registrations` / `cancel_festival_registration`
    below) — otherwise the UUID path param would swallow "export-csv" as a
    registration_id (422 on the UUID parse) instead of reaching this handler.

    Any ``view`` other than ``gate`` is a 400.

    Ä14 runbook note: registration runs until the festival's end, so the
    list is **reprinted/re-pulled on demand** — it always reflects the live
    state, never a cached snapshot.
    """
    if view == "gate":
        org_id = _get_org_id(user)
        event = await _get_festival_event_or_404(org_id, event_id)

        registration_service = get_registration_service()
        registrations = await registration_service.list_registrations(event_id)
        rows = build_gate_rows(registrations, event)

        fieldnames = ["Name", "Kontaktperson", "Kontingent", "Tier", "Schlafplatz", "Telefon"]
        fieldnames += [slot.label for slot in (event.festival_slots or [])]
        fieldnames += ["Angekommen", "Bändchen"]

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(fieldnames)
        for row in rows:
            writer.writerow([row[field] for field in fieldnames])

        log_admin_action("festival.gate_export", user.email, str(event_id))

        filename = f"gate_{_sanitize_filename_slug(event.name)}.csv"

        # utf-8-sig, not a manually prepended BOM — Excel needs the sig
        # marker to detect UTF-8 and render umlauts correctly.
        data = buffer.getvalue().encode("utf-8-sig")
        return StreamingResponse(
            io.BytesIO(data),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown export view: {view!r} (supported: 'gate')",
    )


# --- Festival registrations list + admin cancel (T203) ---
#
# Route-ordering trap (see the export-csv docstring above and
# events.py:1113): these parameterized routes MUST stay declared AFTER the
# literal `/registrations/export-csv` route — otherwise a request for
# "export-csv" could be swallowed here as a registration_id.


class FestivalRegistrationListResponse(BaseModel):
    """Response for the festival registrations admin list (T203)."""

    items: list[RegistrationResponse]
    total: int


@router.get(
    "/{event_id}/registrations",
    response_model=FestivalRegistrationListResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))],
)
async def list_festival_registrations(
    event_id: UUID,
    user: CurrentUser,
    status_filter: Annotated[RegistrationStatus | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> FestivalRegistrationListResponse:
    """List non-deleted registrations for a festival event.

    Each item carries the festival fields additively (`attendance_slots`,
    `accommodation`, `tier`, `invite_label`) — `RegistrationResponse`
    already has them (T106); this endpoint returns it verbatim, no
    festival-specific response model duplication.
    """
    org_id = _get_org_id(user)
    await _get_festival_event_or_404(org_id, event_id)

    registration_service = get_registration_service()
    registrations = await registration_service.list_registrations(event_id, status_filter, search)

    items = [RegistrationResponse.model_validate(r) for r in registrations]
    return FestivalRegistrationListResponse(items=items, total=len(items))


class OvernightNotificationResult(BaseModel):
    """Outcome of the F8 catch-up run (one mail per approved group)."""

    sent: int
    skipped: int
    failed: int


@router.post(
    "/{event_id}/overnight-notifications",
    response_model=OvernightNotificationResult,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def notify_overnight_approvals(
    event_id: UUID,
    user: CurrentUser,
) -> OvernightNotificationResult:
    """Mail every approved group that has not been told yet (F8 catch-up).

    The backfill for approvals granted before the automatic mail existed —
    from here on, approving via the toggle sends F8 by itself. Safe to press
    twice: `notify_overnight_approval` claims `overnight_notified_at` with a
    conditional write, so an already-notified group is skipped, not mailed
    again. No email logic lives in this router — the service is the only send
    site (same rule as the cancel route below).
    """
    org_id = _get_org_id(user)
    event = await _get_festival_event_or_404(org_id, event_id)

    registration_service = get_registration_service()
    result = await registration_service.notify_pending_overnight_approvals(event)

    log_admin_action(
        "festival.overnight_notifications",
        user.email,
        str(event_id),
        result,
    )

    return OvernightNotificationResult(**result)


@router.post(
    "/{event_id}/registrations/{registration_id}/cancel",
    response_model=RegistrationResponse,
    dependencies=[Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))],
)
async def cancel_festival_registration(
    event_id: UUID,
    registration_id: UUID,
    user: CurrentUser,
) -> RegistrationResponse:
    """Admin cancel for a festival registration.

    Delegates to `registration_service.cancel_registration` — the exact
    same festival cancel branch (T109) used by the public cancel flow: it
    flips status to CANCELLED, releases the invite `use_count`, and sends
    F4 itself (never-fail). No email logic lives in this router — the
    service is the only send site.
    """
    org_id = _get_org_id(user)
    await _get_festival_event_or_404(org_id, event_id)

    registration_service = get_registration_service()
    registration = await registration_service.get_registration(event_id, registration_id)
    if not registration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")

    # We don't have the guest's cancellation token here, only the ID — look
    # it up so we can call the very same `cancel_registration` the public
    # cancel flow uses (error mapping mirrors cancellations.py:50-64).
    cancelled, error = await registration_service.cancel_registration(
        registration_id, registration.registration_token,
    )

    if error:
        if "not found" in error.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    log_admin_action("festival.registration_cancel", user.email, str(registration_id))

    return RegistrationResponse.model_validate(cancelled)

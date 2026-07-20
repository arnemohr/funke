"""Public check-in / scanner API endpoints (spec 019 §P3).

No auth dependency anywhere in this router — **the gate token IS the
auth** (spec.md:336). Every route resolves the event via
`event_service.get_event_by_gate_token` first: unknown token -> 404,
gate not currently open -> 410. All check-in *semantics* (scan/override/
undo/search) live in `checkin_service` (T306) — this router is a thin
HTTP shim over it, so it stays covered by that module's service-level
tests without needing its own TestClient suite.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ...models import Event, EventStatus
from ...services.checkin_service import get_checkin_service
from ...services.event_service import get_event_service
from ...services.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Festivals never run a lottery (FestivalPage excludes LOTTERY_PENDING from
# its transition UI) so the gate's "open" window is OPEN (per Ä14 the
# registration deadline is the festival's END — the event stays OPEN through
# the gate days while invite links keep working, so the scanner must run in
# OPEN too; decided 19.7., see spec journal) through REGISTRATION_CLOSED and
# CONFIRMED — never DRAFT (too early) or COMPLETED/CANCELLED (too late).
_GATE_OPEN_STATUSES = {EventStatus.OPEN, EventStatus.REGISTRATION_CLOSED, EventStatus.CONFIRMED}


async def _load_gate_event(gate_token: str) -> Event:
    """Resolve and gate an event by its scanner gate token.

    404 on an unknown/rotated-away token, 410 while the gate isn't active
    for this event's current status.
    """
    event_service = get_event_service()
    event = await event_service.get_event_by_gate_token(gate_token)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unbekannter Scanner-Link.")
    if event.status not in _GATE_OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Der Einlass ist für dieses Event nicht aktiv.",
        )
    return event


class BootSlot(BaseModel):
    """One selectable festival slot, as cached by the offline scanner."""

    key: str
    label: str
    date: str
    is_night: bool


class BootResponse(BaseModel):
    """Boot payload the scanner PWA caches for offline use (T310/T311).

    Includes `verification_secret` — the event's `ticket_secret` — so the
    client can verify tickets locally without network. Accepted risk
    (spec.md Risk 6): this is the ONLY place `ticket_secret` is ever
    exposed, gated by the gate token itself. Do not "fix" this by removing
    it — offline verification depends on it.
    """

    event_name: str
    start_at: datetime
    end_at: datetime | None
    festival_slots: list[BootSlot]
    verification_secret: str


class ScanRequest(BaseModel):
    """Body for a QR scan."""

    code: str


class OverrideRequest(BaseModel):
    """Body for an override check-in — either a ticket `code` (yellow-card
    "Trotzdem einchecken") or an explicit name-search target
    (`registration_id` + `person_index`, spec.md:313 — check-in always
    addresses a specific person, never a bare name)."""

    code: str | None = None
    registration_id: UUID | None = None
    person_index: int | None = None


class UndoRequest(BaseModel):
    """Body for an undo request."""

    scan_id: str


class SearchResponse(BaseModel):
    """Name-search results, with disambiguation context per match."""

    matches: list[dict]


@router.get("/checkin/{gate_token}", response_model=BootResponse)
async def get_checkin_boot(gate_token: str) -> BootResponse:
    """Boot payload for the scanner PWA: event info, slot labels, and the
    verification secret. Lazily generates `ticket_secret` (and `gate_token`,
    harmlessly, since it's already known) if this event has never had its
    gate link opened before."""
    event = await _load_gate_event(gate_token)

    event_service = get_event_service()
    ensured = await event_service.ensure_gate_credentials(event.org_id, event.id)
    if ensured is not None:
        event = ensured

    return BootResponse(
        event_name=event.name,
        start_at=event.start_at,
        end_at=event.end_at,
        festival_slots=[
            BootSlot(key=slot.key, label=slot.label, date=slot.date.isoformat(), is_night=slot.is_night)
            for slot in (event.festival_slots or [])
        ],
        verification_secret=event.ticket_secret,
    )


@router.post("/checkin/{gate_token}/scan")
async def post_checkin_scan(gate_token: str, body: ScanRequest) -> dict:
    """One-tap QR scan. Always 200 with a structured result — the one-tap
    UI branches on `result`/`reason`/`already_checked_in`, never on an
    HTTP error status (spec.md §Ä6/Ä13)."""
    event = await _load_gate_event(gate_token)
    checkin_service = get_checkin_service()
    return await checkin_service.scan_ticket(event, body.code)


@router.post("/checkin/{gate_token}/override")
async def post_checkin_override(gate_token: str, body: OverrideRequest) -> dict:
    """Override check-in — "Trotzdem einchecken" (by ticket code) or the
    name-search check-in target (by `registration_id` + `person_index`)."""
    event = await _load_gate_event(gate_token)
    checkin_service = get_checkin_service()

    if body.code is not None:
        return await checkin_service.scan_ticket(event, body.code, override=True)

    if body.registration_id is not None and body.person_index is not None:
        return await checkin_service.checkin_person(event, body.registration_id, body.person_index)

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Entweder 'code' oder 'registration_id' + 'person_index' angeben.",
    )


@router.post("/checkin/{gate_token}/undo")
async def post_checkin_undo(gate_token: str, body: UndoRequest) -> dict:
    """Undo a scan within its ~60s window. `ok: false` covers both an
    expired window and an unknown scan_id — the UI shows the same
    "Rückgängig nicht mehr möglich" copy for both."""
    event = await _load_gate_event(gate_token)
    checkin_service = get_checkin_service()
    ok = await checkin_service.undo_scan(event.id, body.scan_id)
    return {"ok": ok}


@router.get("/checkin/{gate_token}/search", response_model=SearchResponse)
async def get_checkin_search(
    gate_token: str,
    q: Annotated[str, Query(min_length=2)],
) -> SearchResponse:
    """Name-search fallback (no QR). `q` shorter than 2 chars is a 422
    (enforced by the `Query` constraint)."""
    event = await _load_gate_event(gate_token)
    checkin_service = get_checkin_service()
    matches = await checkin_service.search_names(event, q)
    return SearchResponse(matches=matches)

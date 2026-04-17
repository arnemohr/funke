"""Fahrbericht model — per-Event trip report (spec 014).

Direct child of an Event. Autosaves as DRAFT; submit transitions to SUBMITTED
and mutates Bar catalog + Ship state. Editable post-submission via `reopen` —
re-submissions use delta semantics and bump `version`.

Absorbs the crew roster + trip-shape fields that used to live on the now-deleted
Tour entity.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .ship_state import ShipStatusSnapshot


class FahrberichtStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class ExpenseLine(BaseModel):
    description: str = Field(..., min_length=1, max_length=200)
    amount: Decimal = Field(..., ge=0)


class CrewRef(BaseModel):
    """Reference to a crew member slot.

    Always carries a display name for rendering. Optionally carries the id of
    an AdminUser profile when the crew slot was filled via the autocomplete
    picker. A stale `admin_user_id` (profile deleted later) is tolerated —
    the display_name is authoritative.
    """

    display_name: str = Field(..., min_length=1, max_length=120)
    admin_user_id: UUID | None = None


class FahrberichtBase(BaseModel):
    boarding_fee: Decimal = Decimal("0")
    bar_surcharge: Decimal = Decimal("0")
    kiosk_tally: dict[UUID, int] = Field(default_factory=dict)
    crew_tally: dict[UUID, int] = Field(default_factory=dict)
    ship_status: ShipStatusSnapshot = Field(default_factory=ShipStatusSnapshot)
    new_notes: list[str] = Field(default_factory=list)
    new_todos: list[str] = Field(default_factory=list)
    cash_amount: Decimal | None = None
    cash_handed_to: str | None = Field(None, max_length=120)
    expenses: list[ExpenseLine] = Field(default_factory=list)
    # Trip-shape fields (absorbed from the deleted Tour model, spec 014)
    duration_hours: Decimal | None = Field(None, ge=0, le=48)
    guest_count: int | None = Field(None, ge=0, le=500)
    charterer: str | None = Field(None, max_length=200)
    funker: CrewRef | None = None
    skipper: CrewRef | None = None
    crew: list[CrewRef] = Field(default_factory=list)


class FahrberichtPatch(BaseModel):
    """Partial update for the PUT endpoint. version/applied_* are server-only."""

    boarding_fee: Decimal | None = None
    bar_surcharge: Decimal | None = None
    kiosk_tally: dict[UUID, int] | None = None
    crew_tally: dict[UUID, int] | None = None
    ship_status: ShipStatusSnapshot | None = None
    new_notes: list[str] | None = None
    new_todos: list[str] | None = None
    cash_amount: Decimal | None = None
    cash_handed_to: str | None = Field(None, max_length=120)
    expenses: list[ExpenseLine] | None = None
    duration_hours: Decimal | None = Field(None, ge=0, le=48)
    guest_count: int | None = Field(None, ge=0, le=500)
    charterer: str | None = Field(None, max_length=200)
    funker: CrewRef | None = None
    skipper: CrewRef | None = None
    crew: list[CrewRef] | None = None


class Fahrbericht(FahrberichtBase):
    """Full Fahrbericht record."""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    status: FahrberichtStatus = FahrberichtStatus.DRAFT
    version: int = 0

    # Delta-bookkeeping fields (server-only)
    applied_kiosk_tally: dict[UUID, int] = Field(default_factory=dict)
    applied_crew_tally: dict[UUID, int] = Field(default_factory=dict)
    applied_ship_notes_ids: list[UUID] = Field(default_factory=list)
    applied_ship_todos_ids: list[UUID] = Field(default_factory=list)

    submitted_at: datetime | None = None
    submitted_by: str | None = None
    report_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ComputedTotals(BaseModel):
    kiosk_total: Decimal = Decimal("0")
    crew_cost: Decimal = Decimal("0")
    expenses_total: Decimal = Decimal("0")
    soll: Decimal = Decimal("0")
    cash_diff: Decimal = Decimal("0")


class FahrberichtResponse(Fahrbericht):
    """Response with computed totals appended."""

    computed: ComputedTotals = Field(default_factory=ComputedTotals)


class SubmitResult(BaseModel):
    fahrbericht: FahrberichtResponse
    warnings: list[str] = Field(default_factory=list)
    report_id: UUID | None = None
    bar_ok: bool = False
    ship_ok: bool = False
    report_ok: bool = False

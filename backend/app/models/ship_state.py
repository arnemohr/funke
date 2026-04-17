"""Ship state (singleton) — Schaluppe vessel status (spec 011)."""

from datetime import date as date_type
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Co2Level(str, Enum):
    VOLL = "VOLL"
    DREIVIERTEL = "DREIVIERTEL"
    HALB = "HALB"
    VIERTEL = "VIERTEL"
    LEER = "LEER"


class KloLevel(str, Enum):
    LEER = "LEER"
    VIERTEL = "VIERTEL"
    HALB = "HALB"
    DREIVIERTEL = "DREIVIERTEL"
    VOLL = "VOLL"


class PersennigStatus(str, Enum):
    VOLLSTAENDIG = "VOLLSTAENDIG"
    TEILWEISE = "TEILWEISE"
    OFFEN = "OFFEN"


class Note(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    text: str = Field(..., min_length=1, max_length=2000)
    author: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Todo(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    text: str = Field(..., min_length=1, max_length=500)
    author: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    done: bool = False
    done_at: datetime | None = None
    done_by: str | None = None


class NoteInput(BaseModel):
    id: UUID | None = None
    text: str = Field(..., min_length=1, max_length=2000)


class TodoInput(BaseModel):
    id: UUID | None = None
    text: str = Field(..., min_length=1, max_length=500)


class ShipStatusSnapshot(BaseModel):
    """Scalar ship-status fields captured at a single moment.

    Used both as embedded data on a Fahrbericht and as input to
    `apply_ship_status` (spec 011). All fields are optional because a new
    deployment starts empty and partial updates are allowed.
    """

    tank1_pct: int | None = Field(None, ge=0, le=100)
    tank2_pct: int | None = Field(None, ge=0, le=100)
    kanister_aboard: int | None = Field(None, ge=0)
    kanister_garage: int | None = Field(None, ge=0)
    water_filled_at: date_type | None = None
    co2_level: Co2Level | None = None
    battery_pct: int | None = Field(None, ge=0, le=100)
    klo1_level: KloLevel | None = None
    klo2_level: KloLevel | None = None
    persennig_status: PersennigStatus | None = None


class ShipState(BaseModel):
    """Full ship state — singleton persisted at SHIP#schaluppe / STATE."""

    model_config = ConfigDict(from_attributes=True)

    tank1_pct: int | None = None
    tank2_pct: int | None = None
    kanister_aboard: int | None = None
    kanister_garage: int | None = None
    water_filled_at: date_type | None = None
    co2_level: Co2Level | None = None
    battery_pct: int | None = None
    klo1_level: KloLevel | None = None
    klo2_level: KloLevel | None = None
    persennig_status: PersennigStatus | None = None
    general_notes: list[Note] = Field(default_factory=list)
    open_todos: list[Todo] = Field(default_factory=list)
    last_updated_from_event_id: UUID | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ShipStatePatch(BaseModel):
    tank1_pct: int | None = Field(None, ge=0, le=100)
    tank2_pct: int | None = Field(None, ge=0, le=100)
    kanister_aboard: int | None = Field(None, ge=0)
    kanister_garage: int | None = Field(None, ge=0)
    water_filled_at: date_type | None = None
    co2_level: Co2Level | None = None
    battery_pct: int | None = Field(None, ge=0, le=100)
    klo1_level: KloLevel | None = None
    klo2_level: KloLevel | None = None
    persennig_status: PersennigStatus | None = None

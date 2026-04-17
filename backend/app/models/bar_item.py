"""BarItem model — Schaluppe bar catalog (spec 011).

Bar items carry two inventory units: a **serving unit** (Becher, Flasche, Glas,
Shot — what the Fahrbericht counts) and an optional **package unit** (Kiste,
Faß — how the bar is restocked). Stock is always stored in serving units; the
package layer is for display and restock entry.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BarItemCategory(str, Enum):
    BIER_FASS = "BIER_FASS"
    BIER_FLASCHE = "BIER_FLASCHE"
    ALKOHOLFREI = "ALKOHOLFREI"
    SEKT_WEIN = "SEKT_WEIN"
    SOFTES = "SOFTES"
    HARTES = "HARTES"
    SHOTS = "SHOTS"


class BarItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: BarItemCategory
    serving_unit: str = Field(..., min_length=1, max_length=80)
    package_unit: str | None = Field(None, max_length=80)
    servings_per_package: int | None = Field(None, ge=1, le=10_000)
    ek: Decimal = Field(..., ge=0)
    kb: Decimal = Field(..., ge=0)
    note: str | None = Field(None, max_length=400)
    expected_amount: int = Field(0, ge=0)
    current_amount: int = 0  # may go negative with a warning — spec 011
    active: bool = True
    sort_order: int = 0

    @model_validator(mode="after")
    def _check_package(self) -> "BarItemBase":
        if self.package_unit and self.servings_per_package is None:
            raise ValueError("servings_per_package is required when package_unit is set")
        if self.package_unit is None and self.servings_per_package is not None:
            raise ValueError("servings_per_package must be None when package_unit is not set")
        return self


class BarItemCreate(BarItemBase):
    """Create payload. `id` is generated server-side."""


class BarItemPatch(BaseModel):
    """Partial update — every field optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    category: BarItemCategory | None = None
    serving_unit: str | None = Field(None, min_length=1, max_length=80)
    package_unit: str | None = Field(None, max_length=80)
    servings_per_package: int | None = Field(None, ge=1, le=10_000)
    ek: Decimal | None = Field(None, ge=0)
    kb: Decimal | None = Field(None, ge=0)
    note: str | None = Field(None, max_length=400)
    expected_amount: int | None = Field(None, ge=0)
    current_amount: int | None = None
    active: bool | None = None
    sort_order: int | None = None


class BarItem(BarItemBase):
    """Full bar item record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def current_packages(self) -> int | None:
        if not self.servings_per_package:
            return None
        return self.current_amount // self.servings_per_package

    @property
    def current_singles(self) -> int | None:
        if not self.servings_per_package:
            return None
        return self.current_amount % self.servings_per_package

    def is_low_stock(self, threshold: Decimal = Decimal("0.25")) -> bool:
        if self.expected_amount <= 0:
            return False
        return Decimal(self.current_amount) < Decimal(self.expected_amount) * threshold


class BarItemResponse(BarItem):
    """API response with optional derived fields."""

    current_packages_hint: int | None = None
    current_singles_hint: int | None = None
    low_stock: bool = False

    @classmethod
    def from_bar_item(cls, item: BarItem) -> "BarItemResponse":
        return cls(
            **item.model_dump(),
            current_packages_hint=item.current_packages,
            current_singles_hint=item.current_singles,
            low_stock=item.is_low_stock(),
        )


class StockAdjustmentRequest(BaseModel):
    delta_packages: int = 0
    delta_servings: int = 0
    reason: str = Field(..., min_length=1, max_length=500)


class BarItemStockChange(BaseModel):
    id: UUID
    name: str
    delta: int
    new_current: int
    went_negative: bool


class ConsumptionResult(BaseModel):
    updated_items: list[BarItemStockChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

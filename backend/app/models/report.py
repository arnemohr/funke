"""Closing report model (spec 013).

A Report has a stable id per Tour and one or more **versions**. Every
Fahrbericht (re-)submission produces a new immutable VERSION row; the META
row tracks aggregate state (current_version, email status).
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EmailStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED_NO_RECIPIENT = "SKIPPED_NO_RECIPIENT"


class LineItem(BaseModel):
    bar_item_id: UUID
    bar_item_name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal


class ExpenseLine(BaseModel):
    description: str
    amount: Decimal


class ReportTotals(BaseModel):
    kiosk_total: Decimal = Decimal("0")
    crew_cost: Decimal = Decimal("0")
    expenses_total: Decimal = Decimal("0")
    bar_surcharge: Decimal = Decimal("0")
    soll: Decimal = Decimal("0")
    cash_amount: Decimal | None = None
    cash_diff: Decimal = Decimal("0")


class ReportVersion(BaseModel):
    """Immutable per-submission snapshot."""

    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    version: int
    event_id: UUID
    fahrbericht_snapshot: dict
    event_snapshot: dict
    bar_catalog_snapshot: dict  # {bar_item_id: {...}}
    kiosk_summary: list[LineItem] = Field(default_factory=list)
    crew_summary: list[LineItem] = Field(default_factory=list)
    expenses_summary: list[ExpenseLine] = Field(default_factory=list)
    totals: ReportTotals = Field(default_factory=ReportTotals)
    booking_text: str = ""
    pdf_s3_key: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReportMeta(BaseModel):
    """Aggregate state — overwritten each time current_version advances."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    current_version: int = 0
    finance_recipient: str | None = None
    email_status: EmailStatus = EmailStatus.PENDING
    email_attempts: int = 0
    email_last_error: str | None = None
    email_last_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReportResponse(ReportMeta):
    """List / detail response — META + list of version numbers."""

    versions: list[int] = Field(default_factory=list)

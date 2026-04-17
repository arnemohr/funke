"""Fahrbericht service (spec 012).

Owns the DRAFT→SUBMITTED lifecycle and the versioned submission pipeline that
applies consumption to the bar catalog, updates ship state, and hands off to
the report service. SUBMITTED reports can be reopened for editing.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from botocore.exceptions import ClientError

from ..models import (
    BarItem,
    ComputedTotals,
    Fahrbericht,
    FahrberichtPatch,
    FahrberichtResponse,
    FahrberichtStatus,
    NoteInput,
    ShipStatusSnapshot,
    SubmitResult,
    Tour,
    TourStatus,
)
from ..models.fahrbericht import ExpenseLine
from ..models.ship_state import TodoInput
from .bar_service import get_bar_service
from .config import (
    TOUR_PK_PREFIX,
    TOUR_SK_FAHRBERICHT,
    get_tours_table,
)
from .logging import get_logger
from .ship_service import get_ship_service
from .tour_service import get_tour_service

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _fahrbericht_to_item(bericht: Fahrbericht) -> dict:
    def _dec(d: Decimal | None) -> str | None:
        return str(d) if d is not None else None

    return {
        "pk": f"{TOUR_PK_PREFIX}{bericht.tour_id}",
        "sk": TOUR_SK_FAHRBERICHT,
        "entity_type": "Fahrbericht",
        "tour_id": str(bericht.tour_id),
        "status": bericht.status.value,
        "version": bericht.version,
        "boarding_fee": _dec(bericht.boarding_fee),
        "bar_surcharge": _dec(bericht.bar_surcharge),
        "kiosk_tally": {str(k): v for k, v in bericht.kiosk_tally.items()},
        "crew_tally": {str(k): v for k, v in bericht.crew_tally.items()},
        "applied_kiosk_tally": {str(k): v for k, v in bericht.applied_kiosk_tally.items()},
        "applied_crew_tally": {str(k): v for k, v in bericht.applied_crew_tally.items()},
        "applied_ship_notes_ids": [str(i) for i in bericht.applied_ship_notes_ids],
        "applied_ship_todos_ids": [str(i) for i in bericht.applied_ship_todos_ids],
        "ship_status": bericht.ship_status.model_dump(mode="json"),
        "new_notes": bericht.new_notes,
        "new_todos": bericht.new_todos,
        "cash_amount": _dec(bericht.cash_amount),
        "cash_handed_to": bericht.cash_handed_to,
        "expenses": [e.model_dump(mode="json") for e in bericht.expenses],
        "submitted_at": bericht.submitted_at.isoformat() if bericht.submitted_at else None,
        "submitted_by": bericht.submitted_by,
        "report_id": str(bericht.report_id) if bericht.report_id else None,
        "created_at": bericht.created_at.isoformat(),
        "updated_at": bericht.updated_at.isoformat(),
    }


def _item_to_fahrbericht(item: dict) -> Fahrbericht:
    def _dec(v) -> Decimal | None:
        if v is None:
            return None
        return Decimal(v)

    def _required_dec(v) -> Decimal:
        return Decimal(v) if v is not None else Decimal("0")

    return Fahrbericht(
        tour_id=UUID(item["tour_id"]),
        status=FahrberichtStatus(item["status"]),
        version=int(item.get("version", 0)),
        boarding_fee=_required_dec(item.get("boarding_fee")),
        bar_surcharge=_required_dec(item.get("bar_surcharge")),
        kiosk_tally={UUID(k): int(v) for k, v in (item.get("kiosk_tally") or {}).items()},
        crew_tally={UUID(k): int(v) for k, v in (item.get("crew_tally") or {}).items()},
        applied_kiosk_tally={
            UUID(k): int(v) for k, v in (item.get("applied_kiosk_tally") or {}).items()
        },
        applied_crew_tally={
            UUID(k): int(v) for k, v in (item.get("applied_crew_tally") or {}).items()
        },
        applied_ship_notes_ids=[UUID(i) for i in item.get("applied_ship_notes_ids") or []],
        applied_ship_todos_ids=[UUID(i) for i in item.get("applied_ship_todos_ids") or []],
        ship_status=ShipStatusSnapshot(**(item.get("ship_status") or {})),
        new_notes=list(item.get("new_notes") or []),
        new_todos=list(item.get("new_todos") or []),
        cash_amount=_dec(item.get("cash_amount")),
        cash_handed_to=item.get("cash_handed_to"),
        expenses=[ExpenseLine(**e) for e in item.get("expenses") or []],
        submitted_at=datetime.fromisoformat(item["submitted_at"]) if item.get("submitted_at") else None,
        submitted_by=item.get("submitted_by"),
        report_id=UUID(item["report_id"]) if item.get("report_id") else None,
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def _compute(bericht: Fahrbericht, catalog: dict[UUID, BarItem]) -> ComputedTotals:
    kiosk_total = sum(
        (Decimal(q) * catalog[bid].kb for bid, q in bericht.kiosk_tally.items() if bid in catalog and q),
        Decimal("0"),
    )
    crew_cost = sum(
        (Decimal(q) * catalog[bid].ek for bid, q in bericht.crew_tally.items() if bid in catalog and q),
        Decimal("0"),
    )
    expenses_total = sum((e.amount for e in bericht.expenses), Decimal("0"))
    soll = kiosk_total + bericht.boarding_fee + bericht.bar_surcharge
    cash = bericht.cash_amount or Decimal("0")
    return ComputedTotals(
        kiosk_total=kiosk_total,
        crew_cost=crew_cost,
        expenses_total=expenses_total,
        soll=soll,
        cash_diff=cash - soll,
    )


class FahrberichtService:
    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_tours_table()
        return self._table

    async def get(self, tour_id: UUID) -> Fahrbericht | None:
        resp = self.table.get_item(
            Key={"pk": f"{TOUR_PK_PREFIX}{tour_id}", "sk": TOUR_SK_FAHRBERICHT},
        )
        item = resp.get("Item")
        return _item_to_fahrbericht(item) if item else None

    async def create_draft(self, tour_id: UUID) -> Fahrbericht:
        existing = await self.get(tour_id)
        if existing:
            raise ValueError("fahrbericht_exists")
        bericht = Fahrbericht(tour_id=tour_id)
        self.table.put_item(Item=_fahrbericht_to_item(bericht))
        return bericht

    async def upsert_draft(self, tour_id: UUID, patch: FahrberichtPatch) -> Fahrbericht:
        existing = await self.get(tour_id)
        if existing is None:
            existing = Fahrbericht(tour_id=tour_id)
        if existing.status == FahrberichtStatus.SUBMITTED:
            raise ValueError("fahrbericht_submitted")
        fields = patch.model_dump(exclude_none=True)
        if fields:
            fields["updated_at"] = datetime.now(timezone.utc)
            existing = existing.model_copy(update=fields)
        self.table.put_item(Item=_fahrbericht_to_item(existing))
        return existing

    async def delete_draft(self, tour_id: UUID) -> None:
        existing = await self.get(tour_id)
        if not existing:
            return
        if existing.status == FahrberichtStatus.SUBMITTED:
            raise ValueError("fahrbericht_submitted")
        self.table.delete_item(
            Key={"pk": f"{TOUR_PK_PREFIX}{tour_id}", "sk": TOUR_SK_FAHRBERICHT},
        )

    async def reopen(self, tour_id: UUID) -> Fahrbericht:
        existing = await self.get(tour_id)
        if not existing:
            raise ValueError("fahrbericht_not_found")
        if existing.status != FahrberichtStatus.SUBMITTED:
            raise ValueError("fahrbericht_not_submitted")
        updated = existing.model_copy(
            update={
                "status": FahrberichtStatus.DRAFT,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_fahrbericht_to_item(updated))
        return updated

    async def submit(self, tour_id: UUID, submitted_by: str | None) -> SubmitResult:
        existing = await self.get(tour_id)
        if not existing:
            raise ValueError("fahrbericht_not_found")
        if existing.status == FahrberichtStatus.SUBMITTED:
            raise ValueError("fahrbericht_already_submitted")

        # Validation
        has_content = (
            any(existing.kiosk_tally.values())
            or any(existing.crew_tally.values())
            or existing.expenses
            or existing.cash_amount is not None
        )
        if not has_content:
            raise ValueError("fahrbericht_empty")
        if existing.cash_amount is not None and not existing.cash_handed_to:
            raise ValueError("fahrbericht_cash_needs_recipient")

        tour_service = get_tour_service()
        tour = await tour_service.get_tour(tour_id)
        if not tour:
            raise ValueError("tour_not_found")

        bar_service = get_bar_service()
        catalog_list = await bar_service.list_bar_items()
        catalog = {b.id: b for b in catalog_list}

        # Unknown bar_item_id → reject.
        for bid in set(existing.kiosk_tally) | set(existing.crew_tally):
            if bid not in catalog:
                raise ValueError(f"unknown_bar_item:{bid}")

        new_version = (existing.version or 0) + 1
        first_submit = existing.version == 0

        now = datetime.now(timezone.utc)
        updated = existing.model_copy(
            update={
                "status": FahrberichtStatus.SUBMITTED,
                "version": new_version,
                "submitted_at": now,
                "submitted_by": submitted_by,
                "updated_at": now,
            },
        )
        self.table.put_item(Item=_fahrbericht_to_item(updated))

        if first_submit:
            await tour_service.transition_to_completed(tour_id)

        # Side effects — best-effort.
        warnings: list[str] = []
        bar_ok = ship_ok = report_ok = False

        try:
            if first_submit:
                bar_result = await bar_service.apply_consumption(
                    tour_id=tour_id,
                    version=new_version,
                    kiosk_tally=existing.kiosk_tally,
                    crew_tally=existing.crew_tally,
                )
            else:
                combined_prev = dict(existing.applied_kiosk_tally)
                for k, v in existing.applied_crew_tally.items():
                    combined_prev[k] = combined_prev.get(k, 0) + v
                combined_next = dict(existing.kiosk_tally)
                for k, v in existing.crew_tally.items():
                    combined_next[k] = combined_next.get(k, 0) + v
                bar_result = await bar_service.apply_consumption_delta(
                    tour_id=tour_id,
                    version=new_version,
                    previous=combined_prev,
                    next=combined_next,
                )
            warnings.extend(bar_result.warnings)
            bar_ok = True
        except Exception as exc:  # noqa: BLE001 — pipeline best-effort
            logger.exception("fahrbericht.submit.bar_failed", extra={"tour_id": str(tour_id)})
            warnings.append(f"Bar-Update fehlgeschlagen: {exc}")

        try:
            ship_service = get_ship_service()
            note_inputs = [NoteInput(text=t) for t in updated.new_notes]
            todo_inputs = [TodoInput(text=t) for t in updated.new_todos]
            if first_submit:
                _, new_note_ids, new_todo_ids = await ship_service.apply_ship_status(
                    tour_id=tour_id,
                    version=new_version,
                    snapshot=updated.ship_status,
                    new_notes=note_inputs,
                    new_todos=todo_inputs,
                )
            else:
                _, new_note_ids, new_todo_ids = await ship_service.apply_ship_status_versioned(
                    tour_id=tour_id,
                    version=new_version,
                    snapshot=updated.ship_status,
                    previously_applied_note_ids=existing.applied_ship_notes_ids,
                    previously_applied_todo_ids=existing.applied_ship_todos_ids,
                    new_notes=note_inputs,
                    new_todos=todo_inputs,
                )
            ship_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.exception("fahrbericht.submit.ship_failed", extra={"tour_id": str(tour_id)})
            warnings.append(f"Schiff-Update fehlgeschlagen: {exc}")
            new_note_ids = []
            new_todo_ids = []

        report_id = existing.report_id
        try:
            from .report_service import get_report_service

            report_service = get_report_service()
            meta = await report_service.create_or_update_report(tour_id, new_version)
            report_id = meta.id
            report_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.exception("fahrbericht.submit.report_failed", extra={"tour_id": str(tour_id)})
            warnings.append(f"Berichterstellung fehlgeschlagen: {exc}")

        # Persist applied_* + report_id.
        applied_kiosk = dict(existing.kiosk_tally)
        applied_crew = dict(existing.crew_tally)
        updated = updated.model_copy(
            update={
                "applied_kiosk_tally": applied_kiosk,
                "applied_crew_tally": applied_crew,
                "applied_ship_notes_ids": new_note_ids,
                "applied_ship_todos_ids": new_todo_ids,
                "report_id": report_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        self.table.put_item(Item=_fahrbericht_to_item(updated))

        response = FahrberichtResponse(
            **updated.model_dump(),
            computed=_compute(updated, catalog),
        )
        return SubmitResult(
            fahrbericht=response,
            warnings=warnings,
            report_id=report_id,
            bar_ok=bar_ok,
            ship_ok=ship_ok,
            report_ok=report_ok,
        )

    async def reapply_side_effects(self, tour_id: UUID) -> SubmitResult:
        existing = await self.get(tour_id)
        if not existing or existing.status != FahrberichtStatus.SUBMITTED:
            raise ValueError("fahrbericht_not_submitted")

        bar_service = get_bar_service()
        ship_service = get_ship_service()
        catalog_list = await bar_service.list_bar_items()
        catalog = {b.id: b for b in catalog_list}

        warnings: list[str] = []
        # Bar
        combined_prev = dict(existing.applied_kiosk_tally)
        for k, v in existing.applied_crew_tally.items():
            combined_prev[k] = combined_prev.get(k, 0) + v
        combined_next = dict(existing.kiosk_tally)
        for k, v in existing.crew_tally.items():
            combined_next[k] = combined_next.get(k, 0) + v
        try:
            if existing.version <= 1 and combined_prev == combined_next:
                bar_result = await bar_service.apply_consumption(
                    tour_id=tour_id,
                    version=existing.version,
                    kiosk_tally=existing.kiosk_tally,
                    crew_tally=existing.crew_tally,
                )
            else:
                bar_result = await bar_service.apply_consumption_delta(
                    tour_id=tour_id,
                    version=existing.version,
                    previous=combined_prev,
                    next=combined_next,
                )
            warnings.extend(bar_result.warnings)
            bar_ok = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Bar-Update fehlgeschlagen: {exc}")
            bar_ok = False

        try:
            note_inputs = [NoteInput(text=t) for t in existing.new_notes]
            todo_inputs = [TodoInput(text=t) for t in existing.new_todos]
            await ship_service.apply_ship_status_versioned(
                tour_id=tour_id,
                version=existing.version,
                snapshot=existing.ship_status,
                previously_applied_note_ids=existing.applied_ship_notes_ids,
                previously_applied_todo_ids=existing.applied_ship_todos_ids,
                new_notes=note_inputs,
                new_todos=todo_inputs,
            )
            ship_ok = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Schiff-Update fehlgeschlagen: {exc}")
            ship_ok = False

        try:
            from .report_service import get_report_service

            report_service = get_report_service()
            await report_service.create_or_update_report(tour_id, existing.version)
            await report_service.send_report_email(existing.report_id) if existing.report_id else None
            report_ok = True
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Berichterstellung fehlgeschlagen: {exc}")
            report_ok = False

        response = FahrberichtResponse(
            **existing.model_dump(),
            computed=_compute(existing, catalog),
        )
        return SubmitResult(
            fahrbericht=response,
            warnings=warnings,
            report_id=existing.report_id,
            bar_ok=bar_ok,
            ship_ok=ship_ok,
            report_ok=report_ok,
        )

    async def build_response(self, tour_id: UUID) -> FahrberichtResponse | None:
        bericht = await self.get(tour_id)
        if not bericht:
            return None
        bar_service = get_bar_service()
        catalog_list = await bar_service.list_bar_items()
        catalog = {b.id: b for b in catalog_list}
        return FahrberichtResponse(
            **bericht.model_dump(),
            computed=_compute(bericht, catalog),
        )


_service: FahrberichtService | None = None


def get_fahrbericht_service() -> FahrberichtService:
    global _service
    if _service is None:
        _service = FahrberichtService()
    return _service

"""Bar catalog service (spec 011).

Admin-managed catalog of Schaluppe drinks with two inventory units (serving +
package). Owns the versioned consumption ledger used by spec 012's Fahrbericht
submission pipeline.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from ..models import (
    BarItem,
    BarItemCategory,
    BarItemCreate,
    BarItemPatch,
    BarItemStockChange,
    ConsumptionResult,
)
from .config import (
    BAR_ADJUSTMENT_SK_PREFIX,
    BAR_CONSUMPTION_SK_PREFIX,
    BAR_PK_PREFIX,
    BAR_SK_META,
    get_bar_items_table,
)
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _bar_item_to_item(bar: BarItem) -> dict:
    item = {
        "pk": f"{BAR_PK_PREFIX}{bar.id}",
        "sk": BAR_SK_META,
        "entity_type": "BarItem",
        "id": str(bar.id),
        "name": bar.name,
        "category": bar.category.value,
        "serving_unit": bar.serving_unit,
        "ek": str(bar.ek),
        "kb": str(bar.kb),
        "expected_amount": bar.expected_amount,
        "current_amount": bar.current_amount,
        "active": bar.active,
        "sort_order": bar.sort_order,
        "created_at": bar.created_at.isoformat(),
        "updated_at": bar.updated_at.isoformat(),
    }
    if bar.package_unit:
        item["package_unit"] = bar.package_unit
        item["servings_per_package"] = bar.servings_per_package
    if bar.note:
        item["note"] = bar.note
    return item


def _item_to_bar_item(item: dict) -> BarItem:
    return BarItem(
        id=UUID(item["id"]),
        name=item["name"],
        category=BarItemCategory(item["category"]),
        serving_unit=item["serving_unit"],
        package_unit=item.get("package_unit"),
        servings_per_package=int(item["servings_per_package"]) if item.get("servings_per_package") is not None else None,
        ek=Decimal(item["ek"]),
        kb=Decimal(item["kb"]),
        note=item.get("note"),
        expected_amount=int(item["expected_amount"]),
        current_amount=int(item["current_amount"]),
        active=bool(item["active"]),
        sort_order=int(item.get("sort_order", 0)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


class BarService:
    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_bar_items_table()
        return self._table

    # ------------------------------------------------------------------ CRUD
    async def create_bar_item(self, data: BarItemCreate) -> BarItem:
        bar = BarItem(**data.model_dump())
        self.table.put_item(Item=_bar_item_to_item(bar))
        return bar

    async def get_bar_item(self, bar_item_id: UUID) -> BarItem | None:
        resp = self.table.get_item(
            Key={"pk": f"{BAR_PK_PREFIX}{bar_item_id}", "sk": BAR_SK_META},
        )
        item = resp.get("Item")
        return _item_to_bar_item(item) if item else None

    async def list_bar_items(
        self,
        *,
        active: bool | None = None,
        category: BarItemCategory | None = None,
    ) -> list[BarItem]:
        filter_expr = Attr("entity_type").eq("BarItem")
        if active is not None:
            filter_expr = filter_expr & Attr("active").eq(active)
        if category:
            filter_expr = filter_expr & Attr("category").eq(category.value)
        resp = self.table.scan(FilterExpression=filter_expr)
        items = [_item_to_bar_item(i) for i in resp.get("Items", [])]
        items.sort(key=lambda b: (b.category.value, b.sort_order, b.name))
        return items

    async def patch_bar_item(self, bar_item_id: UUID, patch: BarItemPatch) -> BarItem | None:
        existing = await self.get_bar_item(bar_item_id)
        if not existing:
            return None
        fields = patch.model_dump(exclude_none=True)
        if not fields:
            return existing
        fields["updated_at"] = datetime.now(timezone.utc)
        updated = existing.model_copy(update=fields)
        # Re-run the validator to catch package/servings mismatch.
        updated.model_validate(updated.model_dump())
        self.table.put_item(Item=_bar_item_to_item(updated))
        return updated

    async def delete_bar_item(self, bar_item_id: UUID) -> None:
        # Block delete when any ledger rows exist (consumption or adjustment).
        resp = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"{BAR_PK_PREFIX}{bar_item_id}"),
            Limit=2,
        )
        items = resp.get("Items", [])
        if any(i.get("sk", "").startswith(BAR_CONSUMPTION_SK_PREFIX) for i in items) or any(
            i.get("sk", "").startswith(BAR_ADJUSTMENT_SK_PREFIX) for i in items
        ):
            raise ValueError("bar_item_has_ledger")
        self.table.delete_item(Key={"pk": f"{BAR_PK_PREFIX}{bar_item_id}", "sk": BAR_SK_META})

    # -------------------------------------------------------------- Stock ops
    async def adjust_stock(
        self,
        bar_item_id: UUID,
        *,
        delta_packages: int,
        delta_servings: int,
        reason: str,
        author: str | None,
    ) -> BarItem:
        existing = await self.get_bar_item(bar_item_id)
        if not existing:
            raise ValueError("bar_item_not_found")
        if delta_packages and not existing.servings_per_package:
            raise ValueError("bar_item_has_no_package_unit")

        per_pack = existing.servings_per_package or 0
        delta = delta_packages * per_pack + delta_servings
        if delta == 0:
            return existing

        ts = datetime.now(timezone.utc).isoformat()
        # Ledger row
        self.table.put_item(
            Item={
                "pk": f"{BAR_PK_PREFIX}{bar_item_id}",
                "sk": f"{BAR_ADJUSTMENT_SK_PREFIX}{ts}",
                "entity_type": "BarAdjustment",
                "bar_item_id": str(bar_item_id),
                "delta_packages": delta_packages,
                "delta_servings": delta_servings,
                "delta": delta,
                "reason": reason,
                "author": author,
                "applied_at": ts,
            },
        )
        # Atomic adjustment
        self.table.update_item(
            Key={"pk": f"{BAR_PK_PREFIX}{bar_item_id}", "sk": BAR_SK_META},
            UpdateExpression="ADD current_amount :d SET updated_at = :u",
            ExpressionAttributeValues={":d": delta, ":u": ts},
        )
        return await self.get_bar_item(bar_item_id)  # type: ignore[return-value]

    # --------------------------------------------------------- Consumption
    async def apply_consumption(
        self,
        *,
        event_id: UUID,
        version: int,
        kiosk_tally: dict[UUID, int],
        crew_tally: dict[UUID, int],
    ) -> ConsumptionResult:
        """First-time consumption application for (event_id, version)."""
        combined: dict[UUID, int] = defaultdict(int)
        for bid, q in kiosk_tally.items():
            if q:
                combined[bid] += q
        for bid, q in crew_tally.items():
            if q:
                combined[bid] += q

        return await self._apply_delta(
            event_id=event_id,
            version=version,
            per_item_delta={bid: -q for bid, q in combined.items()},
            ledger_payload={
                "kiosk": {str(k): v for k, v in kiosk_tally.items() if v},
                "crew": {str(k): v for k, v in crew_tally.items() if v},
            },
        )

    async def apply_consumption_delta(
        self,
        *,
        event_id: UUID,
        version: int,
        previous: dict[UUID, int],
        next: dict[UUID, int],
    ) -> ConsumptionResult:
        """Re-submission: apply only the delta vs what was already applied."""
        ids = set(previous) | set(next)
        per_item = {
            bid: -(next.get(bid, 0) - previous.get(bid, 0)) for bid in ids
        }
        per_item = {bid: d for bid, d in per_item.items() if d != 0}
        return await self._apply_delta(
            event_id=event_id,
            version=version,
            per_item_delta=per_item,
            ledger_payload={
                "previous": {str(k): v for k, v in previous.items()},
                "next": {str(k): v for k, v in next.items()},
            },
        )

    async def _apply_delta(
        self,
        *,
        event_id: UUID,
        version: int,
        per_item_delta: dict[UUID, int],
        ledger_payload: dict,
    ) -> ConsumptionResult:
        result = ConsumptionResult()
        ledger_sk = f"{BAR_CONSUMPTION_SK_PREFIX}{event_id}#v{version}"
        ts = datetime.now(timezone.utc).isoformat()

        for bid, delta in per_item_delta.items():
            # Idempotency: conditional put on the ledger row.
            try:
                self.table.put_item(
                    Item={
                        "pk": f"{BAR_PK_PREFIX}{bid}",
                        "sk": ledger_sk,
                        "entity_type": "BarConsumption",
                        "bar_item_id": str(bid),
                        "event_id": str(event_id),
                        "version": version,
                        "delta": delta,
                        "applied_at": ts,
                        **ledger_payload,
                    },
                    ConditionExpression="attribute_not_exists(pk)",
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # Already applied — skip re-decrement.
                    existing = await self.get_bar_item(bid)
                    if existing:
                        result.updated_items.append(
                            BarItemStockChange(
                                id=existing.id,
                                name=existing.name,
                                delta=delta,
                                new_current=existing.current_amount,
                                went_negative=existing.current_amount < 0,
                            ),
                        )
                    continue
                raise

            # Apply the delta and read the new value.
            try:
                resp = self.table.update_item(
                    Key={"pk": f"{BAR_PK_PREFIX}{bid}", "sk": BAR_SK_META},
                    UpdateExpression="ADD current_amount :d SET updated_at = :u",
                    ExpressionAttributeValues={":d": delta, ":u": ts},
                    ReturnValues="ALL_NEW",
                )
            except ClientError:
                logger.exception("bar.apply_delta.update_failed", extra={"bar_item_id": str(bid)})
                continue

            new_current = int(resp["Attributes"].get("current_amount", 0))
            name = resp["Attributes"].get("name", "")
            went_negative = new_current < 0
            result.updated_items.append(
                BarItemStockChange(
                    id=bid,
                    name=name,
                    delta=delta,
                    new_current=new_current,
                    went_negative=went_negative,
                ),
            )
            if went_negative:
                result.warnings.append(
                    f"{name} wurde negativ ({new_current}). Stock in der Bar-Verwaltung prüfen.",
                )

        return result

    # ---------------------------------------------------------------- Seed
    async def seed_from_data(self, seed: list[dict]) -> dict:
        """Idempotent seed. Puts items with attribute_not_exists condition."""
        inserted = 0
        skipped = 0
        for entry in seed:
            bar = BarItem(**entry)
            item = _bar_item_to_item(bar)
            try:
                self.table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(pk)",
                )
                inserted += 1
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    skipped += 1
                else:
                    raise
        return {"inserted": inserted, "skipped": skipped}


_service: BarService | None = None


def get_bar_service() -> BarService:
    global _service
    if _service is None:
        _service = BarService()
    return _service

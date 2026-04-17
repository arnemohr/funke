"""Tour service (spec 010).

Manages Tours — the Schaluppe crew-facing wrapper around an Event (or a
standalone private charter). Guarantees Event↔Tour uniqueness via a pointer
row + conditional write.
"""

from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable
from uuid import UUID

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from ..models import CrewRef, Tour, TourCreate, TourPatch, TourStatus
from .config import (
    EVENT_TOUR_PK_PREFIX,
    EVENT_TOUR_SK,
    TOUR_PK_PREFIX,
    TOUR_SK_FAHRBERICHT,
    TOUR_SK_META,
    TOURS_LIST_PK,
    get_tours_table,
)
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _crewref_to_item(ref: CrewRef | None) -> dict | None:
    if ref is None:
        return None
    return {
        "display_name": ref.display_name,
        "admin_user_id": str(ref.admin_user_id) if ref.admin_user_id else None,
    }


def _item_to_crewref(raw: dict | None) -> CrewRef | None:
    if not raw:
        return None
    admin_id = raw.get("admin_user_id")
    return CrewRef(
        display_name=raw["display_name"],
        admin_user_id=UUID(admin_id) if admin_id else None,
    )


def _tour_to_item(tour: Tour) -> dict:
    item = {
        "pk": f"{TOUR_PK_PREFIX}{tour.id}",
        "sk": TOUR_SK_META,
        "entity_type": "Tour",
        "id": str(tour.id),
        "org_id": str(tour.org_id),
        "name": tour.name or "",
        "date": tour.date.isoformat(),
        "status": tour.status.value,
        "crew": [_crewref_to_item(c) for c in tour.crew],
        "created_at": tour.created_at.isoformat(),
        "updated_at": tour.updated_at.isoformat(),
        # GSI1: list Tours chronologically
        "list_pk": TOURS_LIST_PK,
        "list_sk": f"{tour.date.isoformat()}#{tour.id}",
    }
    if tour.event_id:
        item["event_id"] = str(tour.event_id)
    if tour.duration_hours is not None:
        item["duration_hours"] = str(tour.duration_hours)
    if tour.guest_count is not None:
        item["guest_count"] = tour.guest_count
    if tour.charterer:
        item["charterer"] = tour.charterer
    funker = _crewref_to_item(tour.funker)
    if funker:
        item["funker"] = funker
    skipper = _crewref_to_item(tour.skipper)
    if skipper:
        item["skipper"] = skipper
    if tour.created_by:
        item["created_by"] = tour.created_by
    return item


def _item_to_tour(item: dict) -> Tour:
    return Tour(
        id=UUID(item["id"]),
        org_id=UUID(item["org_id"]),
        event_id=UUID(item["event_id"]) if item.get("event_id") else None,
        name=item.get("name") or None,
        date=date_type.fromisoformat(item["date"]),
        duration_hours=Decimal(item["duration_hours"]) if item.get("duration_hours") else None,
        guest_count=int(item["guest_count"]) if item.get("guest_count") is not None else None,
        charterer=item.get("charterer"),
        funker=_item_to_crewref(item.get("funker")),
        skipper=_item_to_crewref(item.get("skipper")),
        crew=[_item_to_crewref(c) for c in item.get("crew", []) if c],
        status=TourStatus(item["status"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        created_by=item.get("created_by"),
    )


class TourService:
    """Tour CRUD + status transitions."""

    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_tours_table()
        return self._table

    async def create_tour(
        self,
        data: TourCreate,
        org_id: UUID,
        created_by: str | None = None,
    ) -> Tour:
        """Create a new Tour. Enforces 1:1 with Event via a pointer row."""
        data.validate_requires_name()

        tour = Tour(
            org_id=org_id,
            event_id=data.event_id,
            name=data.name,
            date=data.date,
            duration_hours=data.duration_hours,
            guest_count=data.guest_count,
            charterer=data.charterer,
            funker=data.funker,
            skipper=data.skipper,
            crew=data.crew,
            created_by=created_by,
        )

        if data.event_id:
            # Two-step write: put pointer row with condition, then tour row.
            pointer = {
                "pk": f"{EVENT_TOUR_PK_PREFIX}{data.event_id}",
                "sk": EVENT_TOUR_SK,
                "entity_type": "EventTourPointer",
                "event_id": str(data.event_id),
                "tour_id": str(tour.id),
            }
            try:
                self.table.put_item(
                    Item=pointer,
                    ConditionExpression="attribute_not_exists(pk)",
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    raise ValueError("event_already_has_tour") from exc
                raise

        self.table.put_item(Item=_tour_to_item(tour))
        logger.info("tour.created", extra={"tour_id": str(tour.id), "event_id": str(data.event_id) if data.event_id else None})
        return tour

    async def get_tour(self, tour_id: UUID) -> Tour | None:
        response = self.table.get_item(Key={"pk": f"{TOUR_PK_PREFIX}{tour_id}", "sk": TOUR_SK_META})
        item = response.get("Item")
        return _item_to_tour(item) if item else None

    async def get_tour_for_event(self, event_id: UUID) -> Tour | None:
        pointer = self.table.get_item(
            Key={"pk": f"{EVENT_TOUR_PK_PREFIX}{event_id}", "sk": EVENT_TOUR_SK},
        ).get("Item")
        if not pointer:
            return None
        return await self.get_tour(UUID(pointer["tour_id"]))

    async def list_tours(
        self,
        *,
        status: TourStatus | None = None,
        from_date: date_type | None = None,
        to_date: date_type | None = None,
        limit: int = 100,
    ) -> list[Tour]:
        """List Tours newest first using the GSI-1 (list_pk/list_sk)."""
        kwargs = {
            "IndexName": "list-by-date-index",
            "KeyConditionExpression": Key("list_pk").eq(TOURS_LIST_PK),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if from_date or to_date:
            low = (from_date.isoformat() + "#") if from_date else "0000-00-00"
            high = (to_date.isoformat() + "#~") if to_date else "9999-12-31#~"
            kwargs["KeyConditionExpression"] = Key("list_pk").eq(TOURS_LIST_PK) & Key(
                "list_sk",
            ).between(low, high)
        if status:
            kwargs["FilterExpression"] = Attr("status").eq(status.value)

        try:
            response = self.table.query(**kwargs)
        except ClientError:
            # Fallback: scan the table if the GSI isn't available in this env.
            logger.warning("tour.list.fallback_scan")
            scan = self.table.scan(
                FilterExpression=Attr("entity_type").eq("Tour"),
                Limit=limit,
            )
            items = scan.get("Items", [])
            tours = [_item_to_tour(i) for i in items]
            tours.sort(key=lambda t: t.date, reverse=True)
            return tours

        items = response.get("Items", [])
        return [_item_to_tour(i) for i in items]

    async def update_tour(self, tour_id: UUID, patch: TourPatch) -> Tour | None:
        existing = await self.get_tour(tour_id)
        if not existing:
            return None

        updates: dict = {}
        if patch.event_id is not None:
            updates["event_id"] = patch.event_id
        if patch.name is not None:
            updates["name"] = patch.name
        if patch.date is not None:
            updates["date"] = patch.date
        if patch.duration_hours is not None:
            updates["duration_hours"] = patch.duration_hours
        if patch.guest_count is not None:
            updates["guest_count"] = patch.guest_count
        if patch.charterer is not None:
            updates["charterer"] = patch.charterer
        if patch.funker is not None:
            updates["funker"] = patch.funker
        if patch.skipper is not None:
            updates["skipper"] = patch.skipper
        if patch.crew is not None:
            updates["crew"] = patch.crew

        if patch.status and patch.status != existing.status:
            if not existing.can_transition_to(patch.status):
                raise ValueError(f"illegal_transition:{existing.status}->{patch.status}")
            updates["status"] = patch.status

        updates["updated_at"] = datetime.now(timezone.utc)
        updated = existing.model_copy(update=updates)
        self.table.put_item(Item=_tour_to_item(updated))
        return updated

    async def transition_to_completed(self, tour_id: UUID) -> Tour | None:
        """Called from spec 012 on Fahrbericht first submission."""
        existing = await self.get_tour(tour_id)
        if not existing:
            return None
        if existing.status == TourStatus.COMPLETED:
            return existing
        updated = existing.transition_to(TourStatus.COMPLETED)
        self.table.put_item(Item=_tour_to_item(updated))
        return updated

    async def delete_tour(self, tour_id: UUID) -> None:
        """Delete a Tour. Fails if a Fahrbericht exists."""
        fahrbericht = self.table.get_item(
            Key={"pk": f"{TOUR_PK_PREFIX}{tour_id}", "sk": TOUR_SK_FAHRBERICHT},
        ).get("Item")
        if fahrbericht:
            raise ValueError("tour_has_fahrbericht")

        existing = await self.get_tour(tour_id)
        if existing and existing.event_id:
            self.table.delete_item(
                Key={
                    "pk": f"{EVENT_TOUR_PK_PREFIX}{existing.event_id}",
                    "sk": EVENT_TOUR_SK,
                },
            )
        self.table.delete_item(Key={"pk": f"{TOUR_PK_PREFIX}{tour_id}", "sk": TOUR_SK_META})


_service: TourService | None = None


def get_tour_service() -> TourService:
    global _service
    if _service is None:
        _service = TourService()
    return _service

"""Bar catalog admin routes (spec 011)."""

import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from ...models import (
    BarItemCategory,
    BarItemCreate,
    BarItemPatch,
    BarItemResponse,
    StockAdjustmentRequest,
)
from ...services.auth import CurrentUser
from ...services.bar_service import get_bar_service

router = APIRouter(prefix="/bar-items", tags=["admin.bar"])

_SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "bar_seed.json"


@router.get("")
async def list_bar_items(
    _: CurrentUser,
    active: bool | None = None,
    category: BarItemCategory | None = None,
) -> dict:
    items = await get_bar_service().list_bar_items(active=active, category=category)
    return {"items": [BarItemResponse.from_bar_item(b).model_dump(mode="json") for b in items]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bar_item(data: BarItemCreate, _: CurrentUser) -> BarItemResponse:
    bar = await get_bar_service().create_bar_item(data)
    return BarItemResponse.from_bar_item(bar)


@router.get("/{bar_item_id}")
async def get_bar_item(bar_item_id: UUID, _: CurrentUser) -> BarItemResponse:
    bar = await get_bar_service().get_bar_item(bar_item_id)
    if not bar:
        raise HTTPException(404, "not_found")
    return BarItemResponse.from_bar_item(bar)


@router.patch("/{bar_item_id}")
async def patch_bar_item(
    bar_item_id: UUID,
    patch: BarItemPatch,
    _: CurrentUser,
) -> BarItemResponse:
    bar = await get_bar_service().patch_bar_item(bar_item_id, patch)
    if not bar:
        raise HTTPException(404, "not_found")
    return BarItemResponse.from_bar_item(bar)


@router.delete("/{bar_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bar_item(bar_item_id: UUID, _: CurrentUser) -> None:
    try:
        await get_bar_service().delete_bar_item(bar_item_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/{bar_item_id}/adjust-stock")
async def adjust_stock(
    bar_item_id: UUID,
    body: StockAdjustmentRequest,
    user: CurrentUser,
) -> BarItemResponse:
    try:
        bar = await get_bar_service().adjust_stock(
            bar_item_id,
            delta_packages=body.delta_packages,
            delta_servings=body.delta_servings,
            reason=body.reason,
            author=user.sub,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return BarItemResponse.from_bar_item(bar)


@router.post("/seed")
async def seed_bar_items(_: CurrentUser, file: str | None = Query(None)) -> dict:
    """Idempotent seed from the shipped JSON catalog."""
    path = Path(file) if file else _SEED_PATH
    if not path.exists():
        raise HTTPException(400, f"seed file not found: {path}")
    with path.open() as f:
        entries = json.load(f)
    summary = await get_bar_service().seed_from_data(entries)
    return summary

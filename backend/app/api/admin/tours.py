"""Tour admin routes (spec 010)."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ...models import Tour, TourCreate, TourPatch, TourResponse, TourStatus
from ...services.auth import CurrentUser
from ...services.tour_service import get_tour_service

router = APIRouter(prefix="/tours", tags=["admin.tours"])


def _org_id(user: CurrentUser) -> UUID:
    if not user.org_id:
        raise HTTPException(403, "org_id missing in token")
    return UUID(user.org_id)


def _to_response(tour: Tour) -> TourResponse:
    return TourResponse(**tour.model_dump())


class TourListResponse(BaseModel):
    items: list[TourResponse]


@router.get("", response_model=TourListResponse)
async def list_tours(
    user: CurrentUser,
    status_filter: TourStatus | None = Query(None, alias="status"),
    from_date: date_type | None = None,
    to_date: date_type | None = None,
    limit: int = Query(100, ge=1, le=200),
) -> TourListResponse:
    tours = await get_tour_service().list_tours(
        status=status_filter,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    _org = _org_id(user)  # future scoping — all tours are org-scoped
    tours = [t for t in tours if t.org_id == _org]
    return TourListResponse(items=[_to_response(t) for t in tours])


@router.post("", response_model=TourResponse, status_code=status.HTTP_201_CREATED)
async def create_tour(data: TourCreate, user: CurrentUser) -> TourResponse:
    try:
        tour = await get_tour_service().create_tour(
            data,
            org_id=_org_id(user),
            created_by=user.sub,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _to_response(tour)


@router.get("/{tour_id}", response_model=TourResponse)
async def get_tour(tour_id: UUID, user: CurrentUser) -> TourResponse:
    tour = await get_tour_service().get_tour(tour_id)
    if not tour or tour.org_id != _org_id(user):
        raise HTTPException(404, "not_found")
    return _to_response(tour)


@router.patch("/{tour_id}", response_model=TourResponse)
async def patch_tour(tour_id: UUID, patch: TourPatch, user: CurrentUser) -> TourResponse:
    tour = await get_tour_service().get_tour(tour_id)
    if not tour or tour.org_id != _org_id(user):
        raise HTTPException(404, "not_found")
    try:
        updated = await get_tour_service().update_tour(tour_id, patch)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not updated:
        raise HTTPException(404, "not_found")
    return _to_response(updated)


@router.delete("/{tour_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tour(tour_id: UUID, user: CurrentUser) -> None:
    tour = await get_tour_service().get_tour(tour_id)
    if not tour or tour.org_id != _org_id(user):
        raise HTTPException(404, "not_found")
    try:
        await get_tour_service().delete_tour(tour_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


# ---------------------------------------------------------------------------
# Event convenience routes — hang off /events/{event_id}/tour for ergonomics.
# ---------------------------------------------------------------------------

event_tour_router = APIRouter(prefix="/events", tags=["admin.tours"])


@event_tour_router.get("/{event_id}/tour", response_model=TourResponse)
async def get_tour_for_event(event_id: UUID, user: CurrentUser) -> TourResponse:
    tour = await get_tour_service().get_tour_for_event(event_id)
    if not tour or tour.org_id != _org_id(user):
        raise HTTPException(404, "not_found")
    return _to_response(tour)


class CreateTourForEventRequest(BaseModel):
    date: date_type | None = None
    name: str | None = None


@event_tour_router.post(
    "/{event_id}/tour",
    response_model=TourResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tour_for_event(
    event_id: UUID,
    body: CreateTourForEventRequest,
    user: CurrentUser,
) -> TourResponse:
    from ...services.event_service import get_event_service

    event_service = get_event_service()
    event = await event_service.get_event(_org_id(user), event_id)
    if not event:
        raise HTTPException(404, "event_not_found")
    try:
        tour = await get_tour_service().create_tour(
            TourCreate(
                event_id=event_id,
                name=body.name or event.name,
                date=body.date or event.start_at.date(),
                guest_count=event.capacity,
            ),
            org_id=_org_id(user),
            created_by=user.sub,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _to_response(tour)


# Extra re-export to wire into main.py
routers = [router, event_tour_router]

"""Admin profile routes (spec 010): /me and /crew-suggestions."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...models import AdminUser, CrewRole
from ...services.admin_service import get_admin_service
from ...services.auth import CurrentUser

router = APIRouter(prefix="/me", tags=["admin.profile"])


class ProfileResponse(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    crew_roles: list[CrewRole]


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    crew_roles: list[CrewRole] | None = None


def _to_response(admin: AdminUser) -> ProfileResponse:
    return ProfileResponse(
        id=admin.id,
        email=str(admin.email),
        display_name=admin.display_name,
        crew_roles=sorted(admin.crew_roles, key=lambda r: r.value),
    )


def _org_id(user: CurrentUser) -> UUID:
    if not user.org_id:
        raise HTTPException(403, "org_id missing")
    return UUID(user.org_id)


@router.get("", response_model=ProfileResponse)
async def get_me(user: CurrentUser) -> ProfileResponse:
    admin = await get_admin_service().get_by_auth0_sub(
        _org_id(user), user.sub, email=user.email,
    )
    return _to_response(admin)


@router.patch("", response_model=ProfileResponse)
async def patch_me(patch: ProfileUpdateRequest, user: CurrentUser) -> ProfileResponse:
    admin_service = get_admin_service()
    admin = await admin_service.get_by_auth0_sub(
        _org_id(user), user.sub, email=user.email,
    )
    updated = await admin_service.update_profile(
        admin,
        display_name=patch.display_name,
        crew_roles=set(patch.crew_roles) if patch.crew_roles is not None else None,
    )
    return _to_response(updated)


# ---------------------------------------------------------------- suggestions

suggestions_router = APIRouter(prefix="/crew-suggestions", tags=["admin.profile"])


class CrewSuggestion(BaseModel):
    admin_user_id: UUID
    display_name: str
    email: str
    crew_roles: list[CrewRole]


class CrewSuggestionList(BaseModel):
    items: list[CrewSuggestion]


@suggestions_router.get("", response_model=CrewSuggestionList)
async def list_crew_suggestions(
    user: CurrentUser,
    role: CrewRole | None = Query(None),
    q: str | None = Query(None, max_length=60),
    limit: int = Query(10, ge=1, le=30),
) -> CrewSuggestionList:
    admins = await get_admin_service().list_crew_suggestions(
        org_id=_org_id(user),
        role=role,
        q=q,
        limit=limit,
    )
    return CrewSuggestionList(
        items=[
            CrewSuggestion(
                admin_user_id=a.id,
                display_name=a.display_name or str(a.email),
                email=str(a.email),
                crew_roles=sorted(a.crew_roles, key=lambda r: r.value),
            )
            for a in admins
        ],
    )


routers = [router, suggestions_router]

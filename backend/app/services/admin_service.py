"""Admin user profile service (spec 010 addendum).

Minimal surface: persist & look up AdminUser profiles, including the
self-declared `crew_roles` used by the Tour crew picker. The project didn't
have a first-class admin service yet — this is the new home.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from boto3.dynamodb.conditions import Attr

from ..models import AdminRole, AdminUser, CrewRole
from .config import get_admins_table
from .logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = get_logger(__name__)


def _admin_to_item(admin: AdminUser) -> dict:
    item: dict = {
        "pk": f"ORG#{admin.org_id}",
        "sk": f"ADMIN#{admin.id}",
        "entity_type": "AdminUser",
        "id": str(admin.id),
        "org_id": str(admin.org_id),
        "email": str(admin.email),
        "role": admin.role.value,
        "auth0_user_id": admin.auth0_user_id,
        "display_name": admin.display_name or str(admin.email).split("@")[0],
        "created_at": admin.created_at.isoformat(),
    }
    if admin.crew_roles:
        item["crew_roles"] = sorted(r.value for r in admin.crew_roles)
    if admin.last_login_at:
        item["last_login_at"] = admin.last_login_at.isoformat()
    if admin.invited_at:
        item["invited_at"] = admin.invited_at.isoformat()
    if admin.invited_by_admin_id:
        item["invited_by_admin_id"] = str(admin.invited_by_admin_id)
    return item


def _item_to_admin(item: dict) -> AdminUser:
    return AdminUser(
        id=UUID(item["id"]),
        org_id=UUID(item["org_id"]),
        email=item["email"],
        role=AdminRole(item["role"]),
        auth0_user_id=item.get("auth0_user_id"),
        display_name=item.get("display_name"),
        crew_roles={CrewRole(r) for r in item.get("crew_roles") or []},
        created_at=datetime.fromisoformat(item["created_at"]),
        last_login_at=(
            datetime.fromisoformat(item["last_login_at"]) if item.get("last_login_at") else None
        ),
        invited_at=(
            datetime.fromisoformat(item["invited_at"]) if item.get("invited_at") else None
        ),
        invited_by_admin_id=(
            UUID(item["invited_by_admin_id"]) if item.get("invited_by_admin_id") else None
        ),
    )


class AdminService:
    def __init__(self):
        self._table = None

    @property
    def table(self) -> "Table":
        if self._table is None:
            self._table = get_admins_table()
        return self._table

    async def get_by_auth0_sub(
        self,
        org_id: UUID,
        auth0_sub: str,
        *,
        email: str | None = None,
    ) -> AdminUser:
        """Find-or-bootstrap an admin profile for the current user.

        The Auth0-driven app doesn't strictly require the admin to be
        pre-provisioned in DynamoDB — profile data for spec 010 just needs a
        stable home. If a row is missing, create one with a Viewer role and
        empty crew_roles. Email comes from the JWT when available; otherwise
        we synthesise one from the Auth0 sub using a deliberately simple
        domain shape (`sub-<hash>@funke.app`) so pydantic's email validator
        accepts it. Anything starting with a sensible label + a real TLD works.
        """
        resp = self.table.scan(
            FilterExpression=Attr("org_id").eq(str(org_id))
            & Attr("auth0_user_id").eq(auth0_sub),
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            return _item_to_admin(items[0])

        # Prefer the real email from the JWT. If missing, synthesise a valid
        # placeholder from a hash of the Auth0 sub (no reserved TLDs).
        if email:
            admin_email = email
        else:
            import hashlib

            digest = hashlib.sha1(auth0_sub.encode()).hexdigest()[:12]  # noqa: S324
            admin_email = f"sub-{digest}@funke.app"

        admin = AdminUser(
            id=uuid4(),
            org_id=org_id,
            email=admin_email,
            role=AdminRole.VIEWER,
            auth0_user_id=auth0_sub,
        )
        self.table.put_item(Item=_admin_to_item(admin))
        return admin

    async def update_profile(
        self,
        admin: AdminUser,
        *,
        display_name: str | None = None,
        crew_roles: set[CrewRole] | None = None,
    ) -> AdminUser:
        fields: dict = {}
        if display_name is not None:
            fields["display_name"] = display_name
        if crew_roles is not None:
            fields["crew_roles"] = crew_roles
        if not fields:
            return admin
        updated = admin.model_copy(update=fields)
        self.table.put_item(Item=_admin_to_item(updated))
        return updated

    async def list_crew_suggestions(
        self,
        *,
        org_id: UUID,
        role: CrewRole | None = None,
        q: str | None = None,
        limit: int = 10,
    ) -> list[AdminUser]:
        filter_expr = Attr("entity_type").eq("AdminUser") & Attr("org_id").eq(str(org_id))
        resp = self.table.scan(FilterExpression=filter_expr)
        admins = [_item_to_admin(i) for i in resp.get("Items", [])]

        if role:
            matches = [a for a in admins if role in a.crew_roles]
            others = [a for a in admins if role not in a.crew_roles]
        else:
            matches = list(admins)
            others = []

        if q:
            needle = q.lower()

            def _match(a: AdminUser) -> bool:
                label = (a.display_name or a.email or "").lower()
                return needle in label

            matches = [a for a in matches if _match(a)]
            others = [a for a in others if _match(a)]

        matches.sort(key=lambda a: (a.display_name or a.email or "").lower())
        others.sort(key=lambda a: (a.display_name or a.email or "").lower())
        return (matches + others)[:limit]


_service: AdminService | None = None


def get_admin_service() -> AdminService:
    global _service
    if _service is None:
        _service = AdminService()
    return _service

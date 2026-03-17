"""Admin user domain model and schemas.

Represents admin users with role-based access control
and organization membership.
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AdminRole(str, Enum):
    """Admin role levels."""

    OWNER = "Owner"
    ADMIN = "Admin"
    VIEWER = "Viewer"


class AdminUser(BaseModel):
    """Full admin user model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    org_id: UUID
    email: EmailStr
    role: AdminRole
    auth0_user_id: str | None = None  # Auth0 sub claim
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: datetime | None = None
    invited_at: datetime | None = None
    invited_by_admin_id: UUID | None = None

    def can_manage_admins(self) -> bool:
        """Check if user can manage other admins."""
        return self.role == AdminRole.OWNER

    def can_edit_events(self) -> bool:
        """Check if user can create/edit events."""
        return self.role in [AdminRole.OWNER, AdminRole.ADMIN]

    def can_view_events(self) -> bool:
        """Check if user can view events."""
        return True  # All roles can view


class Organization(BaseModel):
    """Organization model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=200)
    primary_locale: str = "de-DE"
    owner_admin_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InvitationCreate(BaseModel):
    """Schema for creating an admin invitation."""

    email: EmailStr
    role: AdminRole = AdminRole.VIEWER


class Invitation(BaseModel):
    """Admin invitation model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    org_id: UUID
    email: EmailStr
    role: AdminRole
    token: str  # Secure token for accepting invitation
    invited_by_admin_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    accepted_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        """Check if invitation has expired."""
        return lambda: datetime.now(timezone.utc)() > self.expires_at

    @property
    def is_accepted(self) -> bool:
        """Check if invitation has been accepted."""
        return self.accepted_at is not None

    def accept(self) -> "Invitation":
        """Mark invitation as accepted."""
        if self.is_expired:
            raise ValueError("Invitation has expired")
        if self.is_accepted:
            raise ValueError("Invitation already accepted")
        return self.model_copy(update={"accepted_at": lambda: datetime.now(timezone.utc)()})

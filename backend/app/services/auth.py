"""Auth0 JWT validation middleware for admin routes.

Provides:
- JWT token validation against Auth0
- Role-based access control (Owner, Admin, Viewer)
- FastAPI dependency injection for protected routes
"""

from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from ..models.admin import AdminRole


class AuthSettings(BaseSettings):
    """Auth0 configuration settings."""

    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_client_id: str = ""
    auth0_algorithms: list[str] = ["RS256"]

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_auth_settings() -> AuthSettings:
    """Get cached auth settings."""
    return AuthSettings()


class TokenPayload(BaseModel):
    """Decoded JWT token payload."""

    sub: str  # Auth0 user ID
    email: str | None = None
    org_id: str | None = None  # Custom claim for organization
    role: AdminRole | None = None  # Custom claim for role
    permissions: list[str] = []


class JWKSClient:
    """Client for fetching and caching Auth0 JWKS."""

    def __init__(self, domain: str):
        self.domain = domain
        self._jwks: dict | None = None

    async def get_signing_key(self, kid: str) -> dict:
        """Get the signing key for a given key ID."""
        if self._jwks is None:
            await self._fetch_jwks()

        if self._jwks is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to fetch JWKS",
            )

        for key in self._jwks.get("keys", []):
            if key.get("kid") == kid:
                return key

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find signing key",
        )

    async def _fetch_jwks(self) -> None:
        """Fetch JWKS from Auth0."""
        jwks_url = f"https://{self.domain}/.well-known/jwks.json"
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url, timeout=10.0)
            if response.status_code == 200:
                self._jwks = response.json()


# Reusable JWKS client instance (will be initialized on first use)
_jwks_client: JWKSClient | None = None


def get_jwks_client() -> JWKSClient:
    """Get or create JWKS client."""
    global _jwks_client
    settings = get_auth_settings()
    if _jwks_client is None and settings.auth0_domain:
        _jwks_client = JWKSClient(settings.auth0_domain)
    if _jwks_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth0 not configured",
        )
    return _jwks_client


# HTTP Bearer scheme for extracting tokens
bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenPayload:
    """Verify and decode a JWT token from the Authorization header.

    Raises:
        HTTPException: If token is missing, invalid, or expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    settings = get_auth_settings()

    # Skip validation in dev mode without Auth0 configured
    if not settings.auth0_domain:
        # Return a mock payload for development
        return TokenPayload(
            sub="dev-user",
            email="dev@example.com",
            org_id="dev-org",
            role=AdminRole.OWNER,
            permissions=["admin:all"],
        )

    try:
        # Decode header to get key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID",
            )

        # Get signing key from JWKS
        jwks_client = get_jwks_client()
        signing_key = await jwks_client.get_signing_key(kid)

        # Verify and decode the token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=settings.auth0_algorithms,
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )

        # Extract custom claims from token
        # Custom namespace for claims (must match Auth0 Action)
        namespace = "https://claims.mobilemachenschaften.com"

        org_id = payload.get(f"{namespace}/org_id")
        role_claim = payload.get(f"{namespace}/role")
        email = payload.get("email") or payload.get(f"{namespace}/email")

        # Validate required claims for admin access
        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: No organization assigned. Contact your administrator.",
            )

        if not role_claim:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: No admin role assigned. Contact your administrator.",
            )

        # Validate role is a known value
        try:
            role = AdminRole(role_claim)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Invalid role '{role_claim}'.",
            )

        return TokenPayload(
            sub=payload.get("sub", ""),
            email=email,
            org_id=org_id,
            role=role,
            permissions=payload.get("permissions", []),
        )

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e!s}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# Type alias for dependency injection
CurrentUser = Annotated[TokenPayload, Depends(verify_token)]


def require_role(allowed_roles: list[AdminRole]):
    """Create a dependency that requires specific roles.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role([...]))])
        async def admin_endpoint(): ...
    """

    async def role_checker(user: CurrentUser) -> TokenPayload:
        if user.role not in allowed_roles:
            required = [r.value for r in allowed_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {required}",
            )
        return user

    return role_checker


def require_permission(permission: str):
    """Create a dependency that requires a specific permission.

    Usage:
        @router.delete("/event/{id}", dependencies=[Depends(require_permission("events:delete"))])
        async def delete_event(): ...
    """

    async def permission_checker(user: CurrentUser) -> TokenPayload:
        if permission not in user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        return user

    return permission_checker


# Convenience dependencies for common role requirements
RequireOwner = Depends(require_role([AdminRole.OWNER]))
RequireAdmin = Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN]))
RequireViewer = Depends(require_role([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER]))

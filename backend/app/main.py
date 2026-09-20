"""FastAPI application entrypoint for Funke Event Management API.

Configures:
- API routers for admin and public endpoints
- CORS middleware
- Request ID middleware
- Mangum handler for Lambda
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic_settings import BaseSettings

from .services.logging import get_logger, set_request_id, setup_logging

# Initialize logging
setup_logging()
logger = get_logger(__name__)


class AppSettings(BaseSettings):
    """Application settings."""

    env_name: str = "dev"
    cors_origins: list[str] = ["*"]

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = AppSettings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    logger.info("Application starting up", extra={"env": settings.env_name})
    yield
    logger.info("Application shutting down")


app = FastAPI(
    title="Funke Event Management API",
    version="0.1.0",
    description="API for managing funke events, registrations, lotteries, and communications",
    lifespan=lifespan,
)

# Determine CORS origins based on environment
if settings.env_name == "dev":
    cors_allow_origins = settings.cors_origins
else:
    # In production, use configured origins or default to funke.app pattern
    cors_allow_origins = settings.cors_origins if settings.cors_origins != ["*"] else [
        "https://funke.mobilemachenschaften.de",
        "https://*.funke.app",
    ]

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    """Add request ID to all requests for tracing."""
    # Get request ID from header or generate new one
    request_id = request.headers.get("X-Request-ID")
    request_id = set_request_id(request_id)

    # Add to request state
    request.state.request_id = request_id

    # Process request
    response = await call_next(request)

    # Add request ID to response
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "env": settings.env_name}


@app.get("/")
async def root() -> dict:
    """Root endpoint with API info."""
    return {
        "name": "Funke Event Management API",
        "version": "0.1.0",
        "docs": "/docs",
    }


# Import routers
from .api.admin import bar_items as admin_bar_items
from .api.admin import charter as admin_charter
from .api.admin import event_photos as admin_event_photos
from .api.admin import events as admin_events
from .api.admin import fahrbericht as admin_fahrbericht
from .api.admin import festival as admin_festival
from .api.admin import lost_and_found as admin_lost_and_found
from .api.admin import lottery as admin_lottery
from .api.admin import profile as admin_profile
from .api.admin import push as admin_push
from .api.admin import reports as admin_reports
from .api.admin import ship as admin_ship
from .api.public import cancellations as public_cancellations
from .api.public import charter as public_charter
from .api.public import checkin as public_checkin
from .api.public import confirmations as public_confirmations
from .api.public import event_photos as public_event_photos
from .api.public import invites as public_invites
from .api.public import lost_and_found as public_lost_and_found
from .api.public import registrations as public_registrations

# Register admin routers
app.include_router(admin_events.router, prefix="/api/admin/events", tags=["admin-events"])
app.include_router(admin_festival.router, prefix="/api/admin/festival", tags=["admin-festival"])
# Fundsachen (spec 023) — routes hang off /api/admin/events/{event_id}/lostfound, so the
# router shares the events prefix instead of owning one.
app.include_router(
    admin_lost_and_found.router, prefix="/api/admin/events", tags=["admin-lostfound"],
)
# Eventfotos (spec 024) — same story: the routes hang off
# /api/admin/events/{event_id}/photos, so the router shares the events prefix.
app.include_router(
    admin_event_photos.router, prefix="/api/admin/events", tags=["admin-eventphotos"],
)
# Chartervertrag (spec 025) — third one with the same shape: the routes hang off
# /api/admin/events/{event_id}/chartervertrag, so the router shares the events
# prefix. No public counterpart — a charter contract has no public page.
app.include_router(
    admin_charter.router, prefix="/api/admin/events", tags=["admin-charter"],
)
app.include_router(admin_lottery.router, prefix="/api/admin", tags=["admin-lottery"])
app.include_router(admin_push.router, prefix="/api/admin", tags=["admin-push"])

# Schaluppe Fahrbericht (specs 010-014)
for profile_router in admin_profile.routers:
    app.include_router(profile_router, prefix="/api/admin")
app.include_router(admin_bar_items.router, prefix="/api/admin")
app.include_router(admin_ship.router, prefix="/api/admin")
app.include_router(admin_fahrbericht.router, prefix="/api/admin")
for reports_router in admin_reports.routers:
    app.include_router(reports_router, prefix="/api/admin")

# Register public routers
app.include_router(public_registrations.router, prefix="/api/public", tags=["public"])
app.include_router(public_cancellations.router, prefix="/api/public", tags=["public"])
app.include_router(public_confirmations.router, prefix="/api/public", tags=["public"])
app.include_router(public_invites.router, prefix="/api/public", tags=["public"])
app.include_router(public_checkin.router, prefix="/api/public", tags=["public-checkin"])
app.include_router(
    public_lost_and_found.router, prefix="/api/public", tags=["public-lostfound"],
)
# Chartervertrag-Signatur (Spec 025) — der sign_token im Pfad IST die
# Berechtigung, wie bei /lostfound und beim Gate. Kein authGuard.
app.include_router(public_charter.router, prefix="/api/public/vertrag", tags=["public-charter"])
app.include_router(
    public_event_photos.router, prefix="/api/public", tags=["public-eventphotos"],
)

# Placeholder for future routers - will be added in later phases
# from .api.admin import registrations as admin_registrations
# from .api.admin import messages as admin_messages
# from .api.admin import checkins as admin_checkins
# from .api.admin import invitations as admin_invitations

# app.include_router(admin_registrations.router, prefix="/api/admin", tags=["admin-registrations"])
# app.include_router(admin_messages.router, prefix="/api/admin", tags=["admin-messages"])
# app.include_router(admin_checkins.router, prefix="/api/admin", tags=["admin-checkins"])
# app.include_router(admin_invitations.router, prefix="/api/admin", tags=["admin-invitations"])


# Mangum handler for AWS Lambda
handler = Mangum(app, lifespan="off")

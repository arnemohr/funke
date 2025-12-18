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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.env_name == "dev" else ["https://*.funke.app"],
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
from .api.admin import events as admin_events
from .api.admin import lottery as admin_lottery
from .api.public import registrations as public_registrations
from .api.public import cancellations as public_cancellations
from .api.public import confirmations as public_confirmations

# Register admin routers
app.include_router(admin_events.router, prefix="/api/admin/events", tags=["admin-events"])
app.include_router(admin_lottery.router, prefix="/api/admin", tags=["admin-lottery"])

# Register public routers
app.include_router(public_registrations.router, prefix="/api/public", tags=["public"])
app.include_router(public_cancellations.router, prefix="/api/public", tags=["public"])
app.include_router(public_confirmations.router, prefix="/api/public", tags=["public"])

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

"""Services for Funke Event Management System."""

from .auth import (
    AdminRole,
    CurrentUser,
    RequireAdmin,
    RequireOwner,
    RequireViewer,
    TokenPayload,
    require_permission,
    require_role,
    verify_token,
)
from .config import (
    DynamoDBSettings,
    get_dynamodb_resource,
    get_settings,
)
from .email_client import (
    EmailMessage,
    EmailResult,
    SmtpClient,
    get_gmail_client,
)
from .email_service import (
    EmailService,
    get_email_service,
)
from .event_service import (
    EventService,
    get_event_service,
)
from .logging import (
    Timer,
    get_logger,
    set_correlation_id,
    set_request_id,
    setup_logging,
    timed,
)
from .registration_service import (
    RegistrationService,
    get_registration_service,
)

__all__ = [
    # Config
    "DynamoDBSettings",
    "get_dynamodb_resource",
    "get_settings",
    # Auth
    "AdminRole",
    "CurrentUser",
    "RequireAdmin",
    "RequireOwner",
    "RequireViewer",
    "TokenPayload",
    "require_permission",
    "require_role",
    "verify_token",
    # Email Client
    "EmailMessage",
    "EmailResult",
    "SmtpClient",
    "get_gmail_client",
    # Email Service
    "EmailService",
    "get_email_service",
    # Event Service
    "EventService",
    "get_event_service",
    # Logging
    "Timer",
    "get_logger",
    "set_correlation_id",
    "set_request_id",
    "setup_logging",
    "timed",
    # Registration Service
    "RegistrationService",
    "get_registration_service",
]

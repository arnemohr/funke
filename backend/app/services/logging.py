"""Structured logging and observability helpers.

Provides:
- Structured JSON logging for Lambda/CloudWatch
- Request ID propagation
- Correlation ID support
- Performance timing utilities
"""

import contextvars
import logging
import sys
import time
import uuid
from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any

from pydantic_settings import BaseSettings

# Context variables for request tracking
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="",
)
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="",
)


class LogSettings(BaseSettings):
    """Logging configuration settings."""

    log_level: str = "INFO"
    env_name: str = "dev"

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_log_settings() -> LogSettings:
    """Get cached log settings."""
    return LogSettings()


# The set of attributes the stdlib puts on every LogRecord. Anything NOT in
# here that shows up on a record's __dict__ was passed by the caller via
# `extra={...}` (Python spreads those onto the record as attributes — there is
# no `record.extra` dict), so it's a structured field we want in the JSON.
_STANDARD_LOGRECORD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging in CloudWatch."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        import json

        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request context
        request_id = request_id_var.get()
        if request_id:
            log_data["request_id"] = request_id

        correlation_id = correlation_id_var.get()
        if correlation_id:
            log_data["correlation_id"] = correlation_id

        # Add caller-supplied `extra={...}` fields (flow/step/outcome/reason,
        # message_id, etc.). These land as individual record attributes, so
        # emit every non-standard attribute — this is what makes the logs
        # queryable in CloudWatch Insights (`filter flow = "festival"`).
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOGRECORD_ATTRS and not key.startswith("_"):
                log_data.setdefault(key, value)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add location info
        log_data["location"] = f"{record.filename}:{record.lineno}"

        # default=str keeps a stray non-JSON value (UUID, datetime, Enum) from
        # crashing the whole log line.
        return json.dumps(log_data, default=str)


class ContextualLogger(logging.LoggerAdapter):
    """Logger adapter that includes context variables in all log messages."""

    def process(
        self, msg: str, kwargs: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Add context to log messages."""
        # A copy, not the caller's dict: several callers pass the very dict they
        # go on to return (the worker tasks pass their result payload), and
        # writing the ids into it would grow keys their contract does not have.
        extra = dict(kwargs.get("extra", {}))

        # Add request/correlation IDs from context
        request_id = request_id_var.get()
        if request_id:
            extra["request_id"] = request_id

        correlation_id = correlation_id_var.get()
        if correlation_id:
            extra["correlation_id"] = correlation_id

        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging() -> None:
    """Configure logging for the application."""
    settings = get_log_settings()

    # Set log level
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add structured handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def get_logger(name: str) -> ContextualLogger:
    """Get a contextual logger for the given name.

    Args:
        name: Logger name (typically __name__).

    Returns:
        ContextualLogger instance.
    """
    base_logger = logging.getLogger(name)
    return ContextualLogger(base_logger, {})


def token_hint(token: str | None) -> str:
    """Return a short, non-secret prefix of an opaque token for log correlation.

    Enough to correlate a guest's steps across log lines (invite boot ->
    register) and match against an admin's generated link, without ever
    writing the full redeemable secret (invite/registration/gate token) to
    CloudWatch.
    """
    if not token:
        return ""
    return f"{token[:6]}…"


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())[:8]


def set_request_id(request_id: str | None = None) -> str:
    """Set the request ID for the current context.

    Args:
        request_id: Optional request ID. Generated if not provided.

    Returns:
        The request ID that was set.
    """
    rid = request_id or generate_request_id()
    request_id_var.set(rid)
    return rid


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context."""
    correlation_id_var.set(correlation_id)


def timed(logger: ContextualLogger | None = None):
    """Decorator to log function execution time.

    Args:
        logger: Optional logger to use. Creates one if not provided.

    Usage:
        @timed()
        async def my_function():
            ...
    """

    def decorator(func: Callable) -> Callable:
        nonlocal logger
        if logger is None:
            logger = get_logger(func.__module__)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.info(
                    f"{func.__name__} completed",
                    extra={"duration_ms": round(elapsed, 2)},
                )
                return result
            except Exception:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    extra={"duration_ms": round(elapsed, 2)},
                    exc_info=True,
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.info(
                    f"{func.__name__} completed",
                    extra={"duration_ms": round(elapsed, 2)},
                )
                return result
            except Exception:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    extra={"duration_ms": round(elapsed, 2)},
                    exc_info=True,
                )
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def log_admin_action(
    action: str,
    admin_email: str | None,
    event_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an admin action for audit purposes.

    Uses structured logging with `audit_action` field for CloudWatch querying.

    Args:
        action: Action identifier (e.g., 'event.create', 'event.publish').
        admin_email: Email of the admin performing the action.
        event_id: Optional event ID.
        details: Optional additional details.
    """
    audit_logger = get_logger("audit")
    extra: dict[str, Any] = {
        "audit_action": action,
        "admin_email": admin_email or "unknown",
    }
    if event_id:
        extra["event_id"] = event_id
    if details:
        extra.update(details)
    audit_logger.info(f"Admin action: {action}", extra=extra)


class Timer:
    """Context manager for timing code blocks.

    Usage:
        with Timer("operation_name", logger) as t:
            ...
        # Logs duration automatically
    """

    def __init__(self, name: str, logger: ContextualLogger | None = None):
        self.name = name
        self.logger = logger or get_logger(__name__)
        self.start: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000
        if exc_type:
            self.logger.error(
                f"{self.name} failed",
                extra={"duration_ms": round(self.elapsed_ms, 2)},
            )
        else:
            self.logger.info(
                f"{self.name} completed",
                extra={"duration_ms": round(self.elapsed_ms, 2)},
            )

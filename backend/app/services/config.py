"""Shared DynamoDB configuration and table accessors.

Provides:
- DynamoDBSettings for connection configuration
- Shared DynamoDB resource and table accessor functions
"""

from typing import TYPE_CHECKING

import boto3
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table


class DynamoDBSettings(BaseSettings):
    """DynamoDB configuration settings."""

    dynamodb_table_prefix: str = "funke-dev"
    aws_region: str = "eu-central-1"
    dynamodb_endpoint_url: str | None = None  # For local development
    base_url: str = "http://localhost:5173"  # Frontend base URL

    # Spec 013: closing report delivery
    finance_report_inbox: str | None = None
    reports_s3_bucket: str | None = None

    class Config:
        env_prefix = ""
        case_sensitive = False


_settings: DynamoDBSettings | None = None


def get_settings() -> DynamoDBSettings:
    """Get DynamoDB settings (cached)."""
    global _settings
    if _settings is None:
        _settings = DynamoDBSettings()
    return _settings


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get DynamoDB resource."""
    settings = get_settings()
    kwargs = {"region_name": settings.aws_region}
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def get_events_table() -> "Table":
    """Get the events DynamoDB table."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-events")


def get_registrations_table() -> "Table":
    """Get the registrations DynamoDB table."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-registrations")


def get_messages_table() -> "Table":
    """Get the messages DynamoDB table."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-messages")


def get_lottery_runs_table() -> "Table":
    """Get the lottery runs DynamoDB table."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-lottery-runs")


# ---------------------------------------------------------------------------
# Schaluppe Fahrbericht tables (specs 010-013, flattened in spec 014)
# ---------------------------------------------------------------------------


def get_bar_items_table() -> "Table":
    """Bar catalog + consumption + adjustment ledger rows."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-bar-items")


def get_ship_state_table() -> "Table":
    """Ship state (singleton) + per-tour idempotency markers."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-ship-state")


def get_reports_table() -> "Table":
    """Closing reports (META + VERSION rows)."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-reports")


def get_admins_table() -> "Table":
    """Admin users + organization metadata (used by spec 010 profile + crew roles)."""
    settings = get_settings()
    dynamodb = get_dynamodb_resource()
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-admins")


# Key prefixes — centralised so services use the same strings everywhere.
# Spec 014: Fahrbericht + Report pointer co-locate under the Event partition
# in the existing `events` table. No separate Tours table.
EVENT_PK_PREFIX = "EVENT#"
EVENT_SK_FAHRBERICHT = "FAHRBERICHT"
EVENT_SK_REPORT_POINTER = "REPORT"

BAR_PK_PREFIX = "BAR#"
BAR_SK_META = "META"
BAR_CONSUMPTION_SK_PREFIX = "CONSUMPTION#"
BAR_ADJUSTMENT_SK_PREFIX = "ADJUSTMENT#"

SHIP_PK = "SHIP#schaluppe"
SHIP_SK_STATE = "STATE"
# Idempotency marker per Fahrbericht submission — keyed by event_id now.
SHIP_SK_EVENT_MARKER_PREFIX = "STATE#"

REPORT_PK_PREFIX = "REPORT#"
REPORT_SK_META = "META"
REPORT_SK_VERSION_PREFIX = "VERSION#"
REPORTS_LIST_PK = "REPORTS"

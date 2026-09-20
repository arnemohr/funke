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

    # Spec 022: days after an event finishes before the daily sweep
    # pseudonymises its personal data. Counted from `cancelled_at` for a
    # cancelled event, otherwise from `end_at`/`start_at`.
    anonymization_retention_days: int = 90

    # Spec 023: private bucket holding the lost & found photos. Unset locally —
    # the service then refuses to mint upload permissions and serves `None`
    # image URLs instead of failing a whole page.
    lost_and_found_s3_bucket: str | None = None
    # Days a lost & found page stays up, counted from the same event end as the
    # anonymisation sweep. Same default, own knob: a box of jackets follows a
    # different rhythm than a data-protection retention period. Overridable per
    # page (7-365).
    lost_and_found_retention_days: int = 90

    # Spec 024: private bucket holding the event photos guests upload. Its own
    # bucket, not the lost & found one — opposite access direction, different
    # blast radius. Unset locally, in which case the service refuses to mint
    # upload permissions instead of signing against a bucket that isn't there.
    event_photo_s3_bucket: str | None = None
    # Days a photo collection lives, counted from the later of event end and
    # collection creation (same helper as spec 023). Overridable per collection
    # (7-365). The collection is a transfer point, not an archive: holding
    # guests' faces indefinitely is a liability without an upside.
    event_photo_retention_days: int = 90
    # Pepper for `HMAC-SHA256(pepper, ip)` on the uploader's IP — enough to
    # tell "400 photos from 30 people" from "400 photos from one person",
    # without ever storing an address. Unset means NO hash is stored at all:
    # for a privacy field the safe default is nothing, not "unpeppered if need
    # be" — a bare hash over the IPv4 space is reversible in seconds.
    photo_ip_pepper: str | None = None

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
# Spec 025: the charter contract — one bare singleton per event, like FAHRBERICHT.
EVENT_SK_CHARTER = "CHARTER"
EVENT_SK_REPORT_POINTER = "REPORT"
EVENT_SK_INVITE_PREFIX = "INVITE#"
# Spec 023: the lost & found page and its photos, co-located under the same
# EVENT# partition as INVITE# rows.
EVENT_SK_LNF_CONFIG = "LNF#CONFIG"
EVENT_SK_LNF_PHOTO_PREFIX = "LNF#PHOTO#"
# Spec 024: the event photo collection, same partition again. No GSI and no
# timestamp in the sort key — the collection is capped at MAX_PHOTOS, so one
# `begins_with` query plus an in-memory sort beats any index, and `photo_id`
# stays a UUID that GetItem/PATCH/DELETE address directly.
EVENT_SK_PHOTO_CONFIG = "PHOTOS#CONFIG"
EVENT_SK_PHOTO_ITEM_PREFIX = "PHOTOS#ITEM#"
# One row per clock hour, carrying the hourly mint quota. Expires via the
# table's `ttl` attribute, so the counter cleans up after itself.
EVENT_SK_PHOTO_QUOTA_PREFIX = "PHOTOS#QUOTA#"

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

# Spec 019 §P3: check-in scan log rows, co-located in the registrations table
# under the same EVENT# partition as REG# rows (T305's begins_with filter
# keeps them from leaking into registration queries).
CHECKIN_SK_PREFIX = "SCAN#"

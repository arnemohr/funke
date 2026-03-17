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

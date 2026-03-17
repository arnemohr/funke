"""Shared test fixtures for unit tests."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def aws_credentials():
    """Mocked AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "eu-central-1"


@pytest.fixture
def mock_dynamodb(aws_credentials):
    """Create mocked DynamoDB tables matching the CDK schema."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="eu-central-1")

        # Events table
        events_table = dynamodb.create_table(
            TableName="funke-dev-events",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "org_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "registration_link_token", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-index",
                    "KeySchema": [
                        {"AttributeName": "org_id", "KeyType": "HASH"},
                        {"AttributeName": "status", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "link-token-index",
                    "KeySchema": [
                        {"AttributeName": "registration_link_token", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Registrations table
        registrations_table = dynamodb.create_table(
            TableName="funke-dev-registrations",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
                {"AttributeName": "registration_token", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "email-index",
                    "KeySchema": [
                        {"AttributeName": "event_id", "KeyType": "HASH"},
                        {"AttributeName": "email", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "token-index",
                    "KeySchema": [
                        {"AttributeName": "registration_token", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "status-index",
                    "KeySchema": [
                        {"AttributeName": "event_id", "KeyType": "HASH"},
                        {"AttributeName": "status", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Messages table
        messages_table = dynamodb.create_table(
            TableName="funke-dev-messages",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "registration_id", "AttributeType": "S"},
                {"AttributeName": "sent_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "registration-index",
                    "KeySchema": [
                        {"AttributeName": "registration_id", "KeyType": "HASH"},
                        {"AttributeName": "sent_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Admins table
        admins_table = dynamodb.create_table(
            TableName="funke-dev-admins",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "email-index",
                    "KeySchema": [
                        {"AttributeName": "email", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Lottery runs table
        lottery_runs_table = dynamodb.create_table(
            TableName="funke-dev-lottery-runs",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "executed_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "event-index",
                    "KeySchema": [
                        {"AttributeName": "event_id", "KeyType": "HASH"},
                        {"AttributeName": "executed_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        yield {
            "dynamodb": dynamodb,
            "events_table": events_table,
            "registrations_table": registrations_table,
            "messages_table": messages_table,
            "admins_table": admins_table,
            "lottery_runs_table": lottery_runs_table,
        }


@pytest.fixture
def sample_event():
    """Factory fixture for creating sample Event models."""
    from app.models import Event, EventStatus

    def _make_event(**overrides):
        defaults = {
            "id": uuid4(),
            "org_id": uuid4(),
            "name": "Test Event",
            "description": "A test event",
            "location": "Test Location",
            "start_at": datetime.now(timezone.utc) + timedelta(days=30),
            "capacity": 50,
            "registration_deadline": datetime.now(timezone.utc) + timedelta(days=20),
            "status": EventStatus.OPEN,
            "registration_link_token": "test-link-token",
            "created_by_admin_id": uuid4(),
            "created_at": datetime.now(timezone.utc),
            "reminder_schedule_days": [7, 3, 1],
            "autopromote_waitlist": True,
        }
        defaults.update(overrides)
        return Event(**defaults)

    return _make_event


@pytest.fixture
def sample_registration():
    """Factory fixture for creating sample Registration models."""
    from app.models import Registration, RegistrationStatus

    def _make_registration(**overrides):
        defaults = {
            "id": uuid4(),
            "event_id": uuid4(),
            "name": "Test User",
            "email": "test@example.com",
            "group_size": 1,
            "status": RegistrationStatus.REGISTERED,
            "registration_token": "test-token-123",
            "registered_at": datetime.now(timezone.utc),
        }
        defaults.update(overrides)
        return Registration(**defaults)

    return _make_registration

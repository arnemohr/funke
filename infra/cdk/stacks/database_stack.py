"""DynamoDB tables for Funke Event Management System.

Tables:
- events: Event information with TTL
- registrations: Registration records with TTL
- messages: Email communication threads
- admins: Admin users and roles
- lottery_runs: Lottery execution history
"""

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct


class DatabaseStack(Stack):
    """DynamoDB tables stack for the application."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        removal_policy = (
            RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN
        )

        # Events table
        # PK: ORG#{org_id}#EVENT#{event_id}
        # GSI1: status-index for querying by status
        # GSI2: link-token-index for public registration lookup
        self.events_table = dynamodb.Table(
            self,
            "EventsTable",
            table_name=f"funke-{env_name}-events",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
            time_to_live_attribute="ttl",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=env_name != "dev",
            ),
        )

        # GSI for querying events by status within org
        self.events_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="org_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for public event lookup by link token
        self.events_table.add_global_secondary_index(
            index_name="link-token-index",
            partition_key=dynamodb.Attribute(
                name="registration_link_token",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for public festival invite lookup by token (spec 019, T101).
        # NOTE: one GSI change per CloudFormation update — invite-token-index
        # (T101) and gate-token-index (T301) shipped in separate deploys.
        self.events_table.add_global_secondary_index(
            index_name="invite-token-index",
            partition_key=dynamodb.Attribute(
                name="invite_token",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for gate scanner boot by gate token (spec 019, T301 — second
        # separate GSI deploy).
        self.events_table.add_global_secondary_index(
            index_name="gate-token-index",
            partition_key=dynamodb.Attribute(
                name="gate_token",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Registrations table
        # PK: EVENT#{event_id}#REG#{registration_id}
        # GSI1: email-index for duplicate checking per event
        # GSI2: token-index for cancellation/confirmation links
        self.registrations_table = dynamodb.Table(
            self,
            "RegistrationsTable",
            table_name=f"funke-{env_name}-registrations",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
            time_to_live_attribute="ttl",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=env_name != "dev",
            ),
        )

        # GSI for email uniqueness check per event
        self.registrations_table.add_global_secondary_index(
            index_name="email-index",
            partition_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="email",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for token-based lookup (cancellation/confirmation)
        self.registrations_table.add_global_secondary_index(
            index_name="token-index",
            partition_key=dynamodb.Attribute(
                name="registration_token",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for querying by status within event
        self.registrations_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Messages table
        # PK: EVENT#{event_id}#MSG#{message_id}
        # GSI1: registration-index for thread lookup
        # GSI2: message-id-index for reply correlation
        self.messages_table = dynamodb.Table(
            self,
            "MessagesTable",
            table_name=f"funke-{env_name}-messages",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
            time_to_live_attribute="ttl",
        )

        # GSI for registration thread lookup
        self.messages_table.add_global_secondary_index(
            index_name="registration-index",
            partition_key=dynamodb.Attribute(
                name="registration_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sent_at",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for email message-id correlation (replies)
        self.messages_table.add_global_secondary_index(
            index_name="message-id-index",
            partition_key=dynamodb.Attribute(
                name="email_message_id",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Admins table
        # PK: ORG#{org_id}#ADMIN#{admin_id}
        # GSI1: email-index for login lookup
        self.admins_table = dynamodb.Table(
            self,
            "AdminsTable",
            table_name=f"funke-{env_name}-admins",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )

        # GSI for admin lookup by email
        self.admins_table.add_global_secondary_index(
            index_name="email-index",
            partition_key=dynamodb.Attribute(
                name="email",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Lottery runs table
        # PK: EVENT#{event_id}#LOTTERY#{run_id}
        self.lottery_runs_table = dynamodb.Table(
            self,
            "LotteryRunsTable",
            table_name=f"funke-{env_name}-lottery-runs",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
            time_to_live_attribute="ttl",
        )

        # GSI for querying lottery runs by event
        self.lottery_runs_table.add_global_secondary_index(
            index_name="event-index",
            partition_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="executed_at",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ---------------------------------------------------------------
        # Schaluppe Fahrbericht tables (specs 011-014)
        # Spec 014 deprecated the Tours table — Fahrbericht + Report pointer
        # rows now live in events_table. The table resource remains here
        # transiently: CloudFormation can only drop it after all cross-stack
        # importers (api_stack's IAM grant export) are gone. Keep the table
        # but STOP referencing it from api_stack; a follow-up deploy will
        # remove the resource cleanly once the dangling export is cleared.
        # TODO(spec014-cleanup): delete this block in the next deploy cycle.
        # ---------------------------------------------------------------
        self.tours_table = dynamodb.Table(
            self,
            "ToursTable",
            table_name=f"funke-{env_name}-tours",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )

        # Bar items table: catalog + consumption ledger rows + adjustments
        self.bar_items_table = dynamodb.Table(
            self,
            "BarItemsTable",
            table_name=f"funke-{env_name}-bar-items",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )

        # Ship state table (singleton pk = SHIP#schaluppe) + tour markers.
        self.ship_state_table = dynamodb.Table(
            self,
            "ShipStateTable",
            table_name=f"funke-{env_name}-ship-state",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )

        # Reports table: META + VERSION#{n} rows per report
        self.reports_table = dynamodb.Table(
            self,
            "ReportsTable",
            table_name=f"funke-{env_name}-reports",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )

        # GSI for newest-first report listing.
        self.reports_table.add_global_secondary_index(
            index_name="reports-by-date-index",
            partition_key=dynamodb.Attribute(
                name="list_pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="list_sk",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

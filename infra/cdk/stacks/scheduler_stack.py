"""Scheduler stack for Funke Event Management System.

Configures:
- EventBridge rules for scheduled workers
- Confirmation reminder schedule
- Email retry processing
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from constructs import Construct

from .api_stack import ApiStack


class SchedulerStack(Stack):
    """EventBridge scheduler stack for worker triggers."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        api_stack: ApiStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name

        # Confirmation reminder worker - runs every hour
        # Checks for registrations that need confirmation reminders
        self.confirmation_rule = events.Rule(
            self,
            "ConfirmationReminderRule",
            rule_name=f"funke-{env_name}-confirmation-reminder",
            schedule=events.Schedule.rate(Duration.hours(1)),
            enabled=True,
        )

        self.confirmation_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "send_confirmation_reminders",
                }),
                retry_attempts=2,
            )
        )

        # Email retry worker - runs every 5 minutes
        # Processes failed email deliveries
        self.email_retry_rule = events.Rule(
            self,
            "EmailRetryRule",
            rule_name=f"funke-{env_name}-email-retry",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            enabled=True,
        )

        self.email_retry_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "retry_failed_emails",
                }),
                retry_attempts=2,
            )
        )

        # Anonymization sweep - runs daily
        # Pseudonymises the personal data of COMPLETED/CANCELLED events past
        # the retention window (spec 022). Replaces the former hard-delete
        # cleanup; the construct id and rule name are kept so CloudFormation
        # updates the existing rule in place instead of replacing it.
        self.cleanup_rule = events.Rule(
            self,
            "CleanupRule",
            rule_name=f"funke-{env_name}-data-cleanup",
            schedule=events.Schedule.rate(Duration.days(1)),
            enabled=True,
        )

        self.cleanup_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "anonymize_expired_data",
                }),
                retry_attempts=2,
            )
        )

        # Lost & found expiry - runs daily
        # Deletes pages past their retention window (config row, photo rows and
        # S3 objects) and PENDING photo rows left behind by aborted uploads
        # (spec 023). The bucket's 400-day lifecycle rule is the backstop if
        # this ever stops running.
        self.lost_and_found_rule = events.Rule(
            self,
            "LostFoundExpiryRule",
            rule_name=f"funke-{env_name}-lostfound-expiry",
            schedule=events.Schedule.rate(Duration.days(1)),
            enabled=True,
        )

        self.lost_and_found_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "expire_lost_and_found",
                }),
                retry_attempts=2,
            )
        )

        # Event photo expiry - runs daily
        # Deletes collections past their retention window (config row, photo rows
        # and S3 objects), PENDING rows left behind by aborted uploads and stale
        # hourly-quota rows (spec 024 § Aufbewahrung). A rule of its own rather
        # than a shared one because a rule carries exactly one task payload; the
        # bucket's 400-day lifecycle rule is the backstop if this stops running.
        self.event_photos_rule = events.Rule(
            self,
            "EventPhotosExpiryRule",
            rule_name=f"funke-{env_name}-photos-expiry",
            schedule=events.Schedule.rate(Duration.days(1)),
            enabled=True,
        )

        self.event_photos_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "expire_event_photos",
                }),
                retry_attempts=2,
            )
        )

        # Email queue processor - runs every minute
        # Picks up QUEUED messages and sends them with pacing
        # Max 20 emails per invocation to stay within Lambda timeout
        self.email_queue_rule = events.Rule(
            self,
            "EmailQueueRule",
            rule_name=f"funke-{env_name}-process-email-queue",
            schedule=events.Schedule.rate(Duration.minutes(1)),
            enabled=True,
        )

        self.email_queue_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "process_email_queue",
                }),
                retry_attempts=2,
            )
        )

        # Stale sending recovery - runs every 5 minutes
        # Resets messages stuck in sending status (>5 min) back to QUEUED
        self.stale_sending_rule = events.Rule(
            self,
            "StaleSendingRule",
            rule_name=f"funke-{env_name}-recover-stale-sending",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            enabled=True,
        )

        self.stale_sending_rule.add_target(
            targets.LambdaFunction(
                api_stack.worker_function,
                event=events.RuleTargetInput.from_object({
                    "task": "recover_stale_sending",
                }),
                retry_attempts=2,
            )
        )

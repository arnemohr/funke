"""API Gateway + Lambda stack for Funke Event Management System.

Configures:
- Lambda function running FastAPI via Mangum
- API Gateway with HTTP API
- Rate limiting on public routes (10/min/IP)
- CORS configuration
"""

import os

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk.aws_lambda_python_alpha import PythonFunction
from constructs import Construct

from .database_stack import DatabaseStack

# Values that a deploy must never blank out. They live in the Lambda
# environment, which makes the synthesised template the source of truth: a
# deploy from a shell that does not have them overwrites the *running* values
# with empty strings. That happened on 2026-08-20 and silently disabled all
# outgoing mail — the queue worker treats missing SMTP credentials as „dev
# mode" and marks messages as sent without sending them. So a missing value now
# aborts the synth instead of shipping an empty string over a working one.
REQUIRED_SECRETS = (
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_SENDER_EMAIL",
    "VAPID_PRIVATE_KEY",
    "VAPID_PUBLIC_KEY",
)


class ApiStack(Stack):
    """API Gateway + Lambda stack for the application."""

    def _setting(self, name: str, default: str = "") -> str:
        """Resolve one deploy-time setting: environment, then CDK context.

        `.envrc` is the usual source; the lowercased CDK context key stays
        supported so `-c smtp_password=…` keeps working for a one-off deploy.
        Anything in `REQUIRED_SECRETS` that resolves to nothing is recorded and
        reported together by `_require_secrets`.
        """
        value = os.environ.get(name) or self.node.try_get_context(name.lower()) or default
        if not value and name in REQUIRED_SECRETS:
            self._missing_secrets.append(name)
        return value

    def _require_secrets(self) -> None:
        """Abort the synth rather than deploy empty strings over live values.

        `-c allow_empty_secrets=true` is the deliberate escape hatch for an
        environment that genuinely has no mail or push — it has to be typed, so
        nobody wipes a working deployment by forgetting to source `.envrc`.
        """
        if not self._missing_secrets or self.node.try_get_context("allow_empty_secrets"):
            return

        names = sorted(set(self._missing_secrets))
        missing = ", ".join(names)
        verb = "is" if len(names) == 1 else "are"
        raise ValueError(
            f"Refusing to deploy: {missing} {verb} not set, and deploying an "
            "empty value would overwrite the credentials the running Lambdas use "
            "(this is how outgoing mail broke on 2026-08-20).\n"
            "Fix: put the values in .envrc and `direnv allow` (or pass them as "
            "-c smtp_password=… for a one-off).\n"
            "If this environment is genuinely meant to have no mail or push, "
            "deploy with -c allow_empty_secrets=true.",
        )

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        database_stack: DatabaseStack,
        domain_name: str | None = None,
        reports_bucket_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.domain_name = domain_name

        # One resolution order for both Lambdas. They used to read the same
        # settings from different places — the API from `os.environ`, the worker
        # from CDK context — which is why the worker never had SMTP credentials
        # at all: `make deploy` passes no smtp context. Resolving once here and
        # handing the same dict to both makes divergence impossible.
        self._missing_secrets: list[str] = []
        mail_env = {
            "SMTP_HOST": self._setting("SMTP_HOST", "smtp.strato.de"),
            "SMTP_PORT": self._setting("SMTP_PORT", "465"),
            "SMTP_USE_SSL": self._setting("SMTP_USE_SSL", "true"),
            "SMTP_USERNAME": self._setting("SMTP_USERNAME"),
            "SMTP_PASSWORD": self._setting("SMTP_PASSWORD"),
            "SMTP_SENDER_EMAIL": self._setting("SMTP_SENDER_EMAIL"),
            "SMTP_SENDER_NAME": self._setting(
                "SMTP_SENDER_NAME", "Verein für mobile Machenschaften e.V.",
            ),
        }
        push_env = {
            "VAPID_PRIVATE_KEY": self._setting("VAPID_PRIVATE_KEY"),
            "VAPID_PUBLIC_KEY": self._setting("VAPID_PUBLIC_KEY"),
            "VAPID_CLAIM_EMAIL": self._setting(
                "VAPID_CLAIM_EMAIL", "mailto:info@mobilemachenschaften.de",
            ),
        }
        self._require_secrets()
        removal_policy = RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN
        lost_and_found_retention_days = str(
            self.node.try_get_context("lost_and_found_retention_days") or 90
        )
        event_photo_retention_days = str(
            self.node.try_get_context("event_photo_retention_days") or 90
        )

        # The frontend origin. Needed by the HTTP API's preflight and by every
        # bucket the browser writes to directly instead of through the Lambda —
        # reports, lost & found and event photos. Resolved before the first of
        # them is declared, because the reports bucket now needs it too.
        if env_name == "dev":
            cors_origins = ["*"]
        elif domain_name:
            cors_origins = [f"https://{domain_name}"]
        else:
            cors_origins = [f"https://{env_name}.funke.app"]

        # The Vite dev server talks to the deployed bucket too, so it gets its
        # own entry wherever the origin list is not already a wildcard.
        bucket_cors_origins = (
            cors_origins if "*" in cors_origins else [*cors_origins, "http://localhost:5173"]
        )

        # Closing report PDF storage (spec 013), and since spec 025 the charter
        # contracts under a contracts/ prefix. Created alongside the API so
        # the Lambda can own the env-var wiring + IAM grants without cross-stack
        # references. Private, encrypted, versioned in prod.
        #
        # No lifecycle rule, unlike the two photo buckets below, and that absence
        # is the point: both a closing report and a signed charter contract are
        # records the association has to keep (spec 025 § Ablage). Nothing in
        # here may quietly expire.
        # Spec 025: the seal key for finished Chartervertraege. Asymmetric and
        # HSM-backed, so the private key is generated inside KMS and is never
        # exportable — there is deliberately no key material in the Lambda
        # environment, the CloudFormation template, or this repo. Secrets reach
        # this stack as plaintext env vars (see _setting), which is a fine home
        # for an SMTP password and not for a signing key.
        #
        # RETAIN even in dev: a contract sealed with a key that has been
        # destroyed can never be validated again, and the ten-year retention
        # outlives any environment.
        self.charter_seal_key = kms.Key(
            self,
            "CharterSealKey",
            description="Funke: PAdES seal for charter contracts (spec 025)",
            key_usage=kms.KeyUsage.SIGN_VERIFY,
            key_spec=kms.KeySpec.RSA_2048,
            removal_policy=RemovalPolicy.RETAIN,
            # The alias is the contract with the bootstrap script: it looks the
            # key up by name so no ARN has to be copied by hand.
            alias=f"funke-{env_name}-charter-seal",
        )

        self.reports_bucket = s3.Bucket(
            self,
            "ReportsBucket",
            bucket_name=f"funke-{env_name}-reports",
            removal_policy=removal_policy,
            auto_delete_objects=env_name == "dev",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=env_name != "dev",
            cors=[
                # POST only: the organiser uploads the scan of the signed
                # contract straight to S3 via presigned POST (spec 025), which is
                # a real cross-origin request and is blocked without this rule.
                # Reading needs no entry — the PDF routes answer with a 302 onto
                # a presigned GET that the browser navigates to rather than
                # fetches, and a navigation is not a CORS request.
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.POST],
                    allowed_origins=bucket_cors_origins,
                    allowed_headers=["*"],
                    max_age=3600,
                ),
            ],
        )

        # Lost & found photos (spec 023). Private throughout: the browser uploads
        # via presigned POST and the public page reads via presigned GET, so no
        # object is ever world-readable and the Lambda never touches a byte.
        # Deliberately NOT versioned, unlike the reports bucket — noncurrent
        # versions would survive both the sweep's delete and the lifecycle rule
        # below, which is exactly what must not happen to photos of strangers.
        self.lostfound_bucket = s3.Bucket(
            self,
            "LostFoundBucket",
            bucket_name=f"funke-{env_name}-lostfound",
            removal_policy=removal_policy,
            auto_delete_objects=env_name == "dev",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            cors=[
                # POST only: the presigned upload is a real cross-origin request
                # and is blocked without this rule. The gallery's <img src=…>
                # loads are not CORS requests at all, so they need no entry.
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.POST],
                    allowed_origins=bucket_cors_origins,
                    allowed_headers=["*"],
                    max_age=3600,
                ),
            ],
            lifecycle_rules=[
                # Backstop for a stalled expiry sweep — it should never fire while
                # the daily worker runs, but a silent outage must not leave photos
                # of people lying around for years.
                s3.LifecycleRule(
                    id="expire-lostfound-objects",
                    expiration=Duration.days(400),
                    enabled=True,
                ),
            ],
        )

        # Event photos (spec 024). A deliberately separate bucket from the lost &
        # found one: guests hold a write grant on this one, and a pass-through
        # write right must not sit next to the lost & found photos.
        # NOT versioned, and here that is a correctness requirement rather than a
        # cost decision: spec 024 § Unkenntlich machen pixelates faces by
        # overwriting full.jpg and thumb.jpg in place, so a noncurrent version of
        # the un-pixelated original would turn that anonymisation into a pretence.
        self.eventphotos_bucket = s3.Bucket(
            self,
            "EventPhotosBucket",
            bucket_name=f"funke-{env_name}-eventphotos",
            removal_policy=removal_policy,
            auto_delete_objects=env_name == "dev",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            cors=[
                # POST because guests upload straight to S3 via presigned POST,
                # which is a real cross-origin request and fails without this
                # rule.
                #
                # GET because spec 024 § Unkenntlich machen pixelates faces in
                # the organiser's browser: it has to `fetch()` the presigned GET
                # for full.jpg and read the bytes onto a canvas. Without this
                # entry the response carries no `Access-Control-Allow-Origin`,
                # the fetch rejects, and the editor cannot open a single photo —
                # and the fallback of an <img> without `crossorigin` taints the
                # canvas, so `toBlob()` would throw at export time instead, i.e.
                # after the organiser drew the rectangles. The lightbox's
                # „Herunterladen" needs the same read, because `<a download>` is
                # ignored cross-origin.
                #
                # This does not open the one-way street. CORS governs whether a
                # browser may *read a response it already fetched*; it is not an
                # authorisation. Reading still requires a valid presigned GET
                # signature, and the only code that mints one is
                # `api/admin/event_photos.py` behind a Viewer role.
                # `BlockPublicAccess.BLOCK_ALL` and the absent bucket policy are
                # untouched, and the public API still cannot emit a key, a URL or
                # a `photo_id`.
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.POST, s3.HttpMethods.GET],
                    allowed_origins=bucket_cors_origins,
                    allowed_headers=["*"],
                    max_age=3600,
                ),
            ],
            lifecycle_rules=[
                # Backstop for a stalled expiry sweep. It should never fire while
                # the daily worker runs, but a silent outage must not leave photos
                # of guests in our bucket for years.
                s3.LifecycleRule(
                    id="expire-eventphotos-objects",
                    expiration=Duration.days(400),
                    enabled=True,
                ),
            ],
        )

        # Log groups for Lambda functions
        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name=f"/aws/lambda/funke-{env_name}-api",
            retention=logs.RetentionDays.ONE_WEEK if env_name == "dev" else logs.RetentionDays.ONE_MONTH,
            removal_policy=removal_policy,
        )

        # Lambda function for FastAPI backend (with bundled dependencies)
        self.api_function = PythonFunction(
            self,
            "ApiFunction",
            function_name=f"funke-{env_name}-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            entry="../backend",
            index="app/main.py",
            handler="handler",
            memory_size=512,
            timeout=Duration.seconds(30),
            bundling={
                "asset_excludes": [".venv", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"],
            },
            environment={
                "ENV_NAME": env_name,
                "EVENTS_TABLE": database_stack.events_table.table_name,
                "REGISTRATIONS_TABLE": database_stack.registrations_table.table_name,
                "MESSAGES_TABLE": database_stack.messages_table.table_name,
                "ADMINS_TABLE": database_stack.admins_table.table_name,
                "LOTTERY_RUNS_TABLE": database_stack.lottery_runs_table.table_name,
                # Schaluppe Fahrbericht (specs 010-013)
                "BAR_ITEMS_TABLE": database_stack.bar_items_table.table_name,
                "SHIP_STATE_TABLE": database_stack.ship_state_table.table_name,
                "REPORTS_TABLE": database_stack.reports_table.table_name,
                "REPORTS_S3_BUCKET": self.reports_bucket.bucket_name,
                # Fundsachen (spec 023)
                "LOST_AND_FOUND_S3_BUCKET": self.lostfound_bucket.bucket_name,
                "LOST_AND_FOUND_RETENTION_DAYS": lost_and_found_retention_days,
                # Eventfotos (spec 024)
                "EVENT_PHOTO_S3_BUCKET": self.eventphotos_bucket.bucket_name,
                "EVENT_PHOTO_RETENTION_DAYS": event_photo_retention_days,
                # Optional on purpose, and NOT in REQUIRED_SECRETS: an unset
                # pepper means no uploader IP hash is stored at all, which is a
                # valid — and for a privacy field the safer — configuration
                # (spec 024 § Missbrauch). Do not "fix" this by requiring it.
                "PHOTO_IP_PEPPER": self._setting("PHOTO_IP_PEPPER"),
                # Defaulted rather than left to the shell. It resolved to "" in
                # production, so the finance report was filed as
                # SKIPPED_NO_RECIPIENT on every run and never reached anyone —
                # the same failure mode the REQUIRED_SECRETS comment above
                # describes, minus the abort. This is the Verein's own standing
                # address, not a secret; an env var or `-c finance_report_inbox=…`
                # still overrides it.
                "FINANCE_REPORT_INBOX": self._setting(
                    "FINANCE_REPORT_INBOX", "buchhaltung@mobilemachenschaften.de",
                ),
                "CHARTER_SEAL_KMS_KEY_ID": self.charter_seal_key.key_id,
                "LOG_LEVEL": "DEBUG" if env_name == "dev" else "INFO",
                # Auth0 configuration
                "AUTH0_DOMAIN": self.node.try_get_context("auth0_domain") or "",
                "AUTH0_AUDIENCE": self.node.try_get_context("auth0_audience") or "",
                # SMTP + push: resolved once in __init__ and shared with the
                # worker, so the two can never drift apart again.
                **mail_env,
                "BASE_URL": self.node.try_get_context("base_url") or f"https://{domain_name}" if domain_name else "http://localhost:5173",
                # VAPID configuration for Web Push notifications (spec 009)
                **push_env,
            },
            log_group=api_log_group,
        )

        # Grant DynamoDB permissions
        database_stack.events_table.grant_read_write_data(self.api_function)
        database_stack.registrations_table.grant_read_write_data(self.api_function)
        database_stack.messages_table.grant_read_write_data(self.api_function)
        database_stack.admins_table.grant_read_write_data(self.api_function)
        database_stack.lottery_runs_table.grant_read_write_data(self.api_function)
        database_stack.bar_items_table.grant_read_write_data(self.api_function)
        database_stack.ship_state_table.grant_read_write_data(self.api_function)
        database_stack.reports_table.grant_read_write_data(self.api_function)
        self.reports_bucket.grant_read_write(self.api_function)

        # Sign only. The worker never seals, so it gets nothing — the narrower
        # the set of principals that can produce a valid seal, the more the
        # CloudTrail record is worth.
        self.charter_seal_key.grant(self.api_function, "kms:Sign", "kms:GetPublicKey")
        # Read+write covers s3:DeleteObject* as well, which the photo-delete
        # endpoint needs. Signing presigned URLs needs no permission of its own.
        self.lostfound_bucket.grant_read_write(self.api_function)
        # Read+write covers s3:DeleteObject* as well, which the photo-delete and
        # collection-delete endpoints need. Signing presigned POST/GET needs no
        # permission of its own.
        self.eventphotos_bucket.grant_read_write(self.api_function)

        # HTTP API with Lambda integration
        # Disable automatic $default stage to configure throttling manually
        self.http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"funke-{env_name}-api",
            create_default_stage=False,
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=cors_origins,
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.PUT,
                    apigwv2.CorsHttpMethod.DELETE,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                max_age=Duration.hours(1),
            ),
            default_integration=integrations.HttpLambdaIntegration(
                "LambdaIntegration",
                handler=self.api_function,
            ),
        )

        # Create default stage with rate limiting
        # Note: HTTP API throttling is configured at the stage level
        self.http_api.add_stage(
            "DefaultStage",
            stage_name="$default",
            auto_deploy=True,
            throttle=apigwv2.ThrottleSettings(
                rate_limit=100,  # requests per second
                burst_limit=200,
            ),
        )

        # Log group for worker Lambda
        worker_log_group = logs.LogGroup(
            self,
            "WorkerLogGroup",
            log_group_name=f"/aws/lambda/funke-{env_name}-worker",
            retention=logs.RetentionDays.ONE_WEEK if env_name == "dev" else logs.RetentionDays.ONE_MONTH,
            removal_policy=removal_policy,
        )

        # Worker Lambda for async tasks (email retries, confirmations)
        self.worker_function = PythonFunction(
            self,
            "WorkerFunction",
            function_name=f"funke-{env_name}-worker",
            runtime=lambda_.Runtime.PYTHON_3_12,
            entry="../backend",
            index="app/workers/handler.py",
            handler="handler",
            memory_size=256,
            timeout=Duration.minutes(5),
            bundling={
                "asset_excludes": [".venv", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"],
            },
            environment={
                "ENV_NAME": env_name,
                "EVENTS_TABLE": database_stack.events_table.table_name,
                "REGISTRATIONS_TABLE": database_stack.registrations_table.table_name,
                "MESSAGES_TABLE": database_stack.messages_table.table_name,
                "ADMINS_TABLE": database_stack.admins_table.table_name,
                "LOTTERY_RUNS_TABLE": database_stack.lottery_runs_table.table_name,
                # Fundsachen (spec 023) — the daily sweep deletes the objects
                "LOST_AND_FOUND_S3_BUCKET": self.lostfound_bucket.bucket_name,
                "LOST_AND_FOUND_RETENTION_DAYS": lost_and_found_retention_days,
                # Eventfotos (spec 024) — same shape, own sweep and own bucket
                "EVENT_PHOTO_S3_BUCKET": self.eventphotos_bucket.bucket_name,
                "EVENT_PHOTO_RETENTION_DAYS": event_photo_retention_days,
                # Optional on purpose, and NOT in REQUIRED_SECRETS: an unset
                # pepper means no uploader IP hash is stored at all, which is a
                # valid — and for a privacy field the safer — configuration
                # (spec 024 § Missbrauch). Do not "fix" this by requiring it.
                "PHOTO_IP_PEPPER": self._setting("PHOTO_IP_PEPPER"),
                "LOG_LEVEL": "DEBUG" if env_name == "dev" else "INFO",
                # SMTP for the queue + retry worker — the SAME values the API
                # gets. Reading these from CDK context alone is what left the
                # worker permanently without credentials: `make deploy` passes
                # no smtp context.
                **mail_env,
                "BASE_URL": self.node.try_get_context("base_url") or f"https://{domain_name}" if domain_name else "http://localhost:5173",
            },
            log_group=worker_log_group,
        )

        # Grant DynamoDB permissions to worker
        database_stack.events_table.grant_read_write_data(self.worker_function)
        database_stack.registrations_table.grant_read_write_data(self.worker_function)
        database_stack.messages_table.grant_read_write_data(self.worker_function)
        database_stack.admins_table.grant_read_data(self.worker_function)
        database_stack.lottery_runs_table.grant_read_write_data(self.worker_function)
        self.lostfound_bucket.grant_read_write(self.worker_function)
        # Read+write covers s3:DeleteObject* as well, which the daily
        # expire_event_photos sweep needs. Signing presigned URLs needs no
        # permission of its own.
        self.eventphotos_bucket.grant_read_write(self.worker_function)

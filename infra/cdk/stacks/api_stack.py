"""API Gateway + Lambda stack for Funke Event Management System.

Configures:
- Lambda function running FastAPI via Mangum
- API Gateway with HTTP API
- Rate limiting on public routes (10/min/IP)
- CORS configuration
"""

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk.aws_lambda_python_alpha import PythonFunction
from constructs import Construct

from .database_stack import DatabaseStack


class ApiStack(Stack):
    """API Gateway + Lambda stack for the application."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        database_stack: DatabaseStack,
        domain_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.domain_name = domain_name
        removal_policy = RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN

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
                "LOG_LEVEL": "DEBUG" if env_name == "dev" else "INFO",
                # Auth0 configuration
                "AUTH0_DOMAIN": self.node.try_get_context("auth0_domain") or "",
                "AUTH0_AUDIENCE": self.node.try_get_context("auth0_audience") or "",
                # SMTP configuration (Strato)
                "SMTP_HOST": self.node.try_get_context("smtp_host") or "smtp.strato.de",
                "SMTP_PORT": self.node.try_get_context("smtp_port") or "465",
                "SMTP_USE_SSL": self.node.try_get_context("smtp_use_ssl") or "true",
                "SMTP_USERNAME": self.node.try_get_context("smtp_username") or "",
                "SMTP_PASSWORD": self.node.try_get_context("smtp_password") or "",
                "SMTP_SENDER_EMAIL": self.node.try_get_context("smtp_sender_email") or "",
                "SMTP_SENDER_NAME": self.node.try_get_context("smtp_sender_name") or "Verein für mobile Machenschaften e.V.",
                "BASE_URL": self.node.try_get_context("base_url") or f"https://{domain_name}" if domain_name else "http://localhost:5173",
            },
            log_group=api_log_group,
        )

        # Grant DynamoDB permissions
        database_stack.events_table.grant_read_write_data(self.api_function)
        database_stack.registrations_table.grant_read_write_data(self.api_function)
        database_stack.messages_table.grant_read_write_data(self.api_function)
        database_stack.admins_table.grant_read_write_data(self.api_function)
        database_stack.lottery_runs_table.grant_read_write_data(self.api_function)

        # Determine CORS origins
        if env_name == "dev":
            cors_origins = ["*"]
        elif domain_name:
            cors_origins = [f"https://{domain_name}"]
        else:
            cors_origins = [f"https://{env_name}.funke.app"]

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
                "LOG_LEVEL": "DEBUG" if env_name == "dev" else "INFO",
                # SMTP configuration (Strato, needed for retry worker)
                "SMTP_HOST": self.node.try_get_context("smtp_host") or "smtp.strato.de",
                "SMTP_PORT": self.node.try_get_context("smtp_port") or "465",
                "SMTP_USE_SSL": self.node.try_get_context("smtp_use_ssl") or "true",
                "SMTP_USERNAME": self.node.try_get_context("smtp_username") or "",
                "SMTP_PASSWORD": self.node.try_get_context("smtp_password") or "",
                "SMTP_SENDER_EMAIL": self.node.try_get_context("smtp_sender_email") or "",
                "SMTP_SENDER_NAME": self.node.try_get_context("smtp_sender_name") or "Verein für mobile Machenschaften e.V.",
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

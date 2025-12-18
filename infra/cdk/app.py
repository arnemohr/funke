#!/usr/bin/env python3
"""AWS CDK application for Boat Event Management System.

Defines separate stacks for:
- Database (DynamoDB tables)
- API (API Gateway + Lambda)
- Storage (S3/CloudFront for frontend)
- Schedulers (EventBridge rules for workers)
"""

import aws_cdk as cdk

from stacks.database_stack import DatabaseStack
from stacks.api_stack import ApiStack
from stacks.storage_stack import StorageStack
from stacks.scheduler_stack import SchedulerStack

app = cdk.App()

# Get environment configuration
env_name = app.node.try_get_context("env") or "dev"
region = app.node.try_get_context("region") or "eu-central-1"

env = cdk.Environment(region=region)

# Database stack - DynamoDB tables
database_stack = DatabaseStack(
    app,
    f"FunkeDatabase-{env_name}",
    env=env,
    env_name=env_name,
)

# API stack - API Gateway + Lambda (depends on database)
api_stack = ApiStack(
    app,
    f"FunkeApi-{env_name}",
    env=env,
    env_name=env_name,
    database_stack=database_stack,
)
api_stack.add_dependency(database_stack)

# Storage stack - S3 + CloudFront for frontend
storage_stack = StorageStack(
    app,
    f"FunkeStorage-{env_name}",
    env=env,
    env_name=env_name,
)

# Scheduler stack - EventBridge for workers (depends on API)
scheduler_stack = SchedulerStack(
    app,
    f"FunkeScheduler-{env_name}",
    env=env,
    env_name=env_name,
    api_stack=api_stack,
)
scheduler_stack.add_dependency(api_stack)

app.synth()

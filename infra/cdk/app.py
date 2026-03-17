#!/usr/bin/env python3
"""AWS CDK application for Funke Event Management System.

Defines separate stacks for:
- Domain (ACM certificate) - deployed to us-east-1 for CloudFront
- Database (DynamoDB tables)
- API (API Gateway + Lambda)
- Storage (S3/CloudFront for frontend)
- Schedulers (EventBridge rules for workers)
"""

import aws_cdk as cdk

from stacks.database_stack import DatabaseStack
from stacks.domain_stack import DomainStack
from stacks.api_stack import ApiStack
from stacks.storage_stack import StorageStack
from stacks.scheduler_stack import SchedulerStack

app = cdk.App()

# Get environment configuration
env_name = app.node.try_get_context("env") or "dev"
region = app.node.try_get_context("region") or "eu-central-1"
domain_name = app.node.try_get_context("domain_name")  # e.g., funke.mobilemachenschaften.de

env = cdk.Environment(region=region)
env_us_east_1 = cdk.Environment(region="us-east-1")

# Domain stack - ACM certificate (must be in us-east-1 for CloudFront)
domain_stack = None
if domain_name:
    domain_stack = DomainStack(
        app,
        f"FunkeDomain-{env_name}",
        env=env_us_east_1,
        env_name=env_name,
        domain_name=domain_name,
        cross_region_references=True,
    )

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
    domain_name=domain_name,
)
api_stack.add_dependency(database_stack)

# Storage stack - S3 + CloudFront for frontend
storage_stack = StorageStack(
    app,
    f"FunkeStorage-{env_name}",
    env=env,
    env_name=env_name,
    domain_stack=domain_stack,
    api_stack=api_stack,
    domain_name=domain_name,
    cross_region_references=True if domain_stack else False,
)
if domain_stack:
    storage_stack.add_dependency(domain_stack)
storage_stack.add_dependency(api_stack)

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

.PHONY: run dev install synth diff deploy destroy bootstrap clean

# Auth0 configuration (required for deploy)
AUTH0_DOMAIN ?= mobilemachenschaften.eu.auth0.com
AUTH0_AUDIENCE ?= https://b1hdv0usik.execute-api.eu-central-1.amazonaws.com

# CDK context arguments
CDK_CONTEXT = -c auth0_domain=$(AUTH0_DOMAIN) -c auth0_audience=$(AUTH0_AUDIENCE)

# Deploy CDK stacks to AWS
run: synth
	uv run cdk deploy --all $(CDK_CONTEXT)

# Synthesize and diff CDK stacks (development workflow)
dev: synth diff

# Install dependencies
install:
	uv sync --all-extras

# Synthesize CloudFormation templates
synth:
	uv run cdk synth $(CDK_CONTEXT)

# Show diff between deployed and local stacks
diff:
	uv run cdk diff $(CDK_CONTEXT)

# Deploy CDK stacks
deploy:
	uv run cdk deploy --all $(CDK_CONTEXT)

# Destroy CDK stacks
destroy:
	uv run cdk destroy --all $(CDK_CONTEXT)

# Bootstrap CDK in the AWS account/region
bootstrap:
	uv run cdk bootstrap

# Clean build artifacts
clean:
	rm -rf cdk.out __pycache__ .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true





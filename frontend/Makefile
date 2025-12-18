.PHONY: run dev install build lint format deploy clean

# Environment (default: dev)
ENV_NAME ?= dev
STACK_NAME = FunkeStorage-$(ENV_NAME)

# Build and preview the production build
run: build
	npm run preview

# Run the Vite dev server with hot reload
dev:
	npm run dev

# Install dependencies
install:
	npm install

# Build for production
build:
	npm run build

# Run linter
lint:
	npm run lint

# Format code
format:
	npm run format:fix

# Deploy frontend to S3 and invalidate CloudFront cache
deploy: build
	@echo "Deploying frontend to $(ENV_NAME)..."
	$(eval BUCKET_NAME := $(shell aws cloudformation describe-stacks --stack-name $(STACK_NAME) --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text))
	$(eval DISTRIBUTION_ID := $(shell aws cloudformation describe-stacks --stack-name $(STACK_NAME) --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text))
	@echo "Syncing to s3://$(BUCKET_NAME)..."
	aws s3 sync dist/ s3://$(BUCKET_NAME) --delete
	@echo "Invalidating CloudFront cache..."
	aws cloudfront create-invalidation --distribution-id $(DISTRIBUTION_ID) --paths "/*"
	@echo "Deploy complete!"

# Clean build artifacts
clean:
	rm -rf node_modules dist .vite



# Quickstart — Funke Event Management System

## Prerequisites

- Python 3.12 (FastAPI runtime)  
- Node.js 20 for frontend (Vite/Vue)  
- AWS CLI + credentials configured; AWS CDK (Python) installed (`npm install -g aws-cdk` or `pip install aws-cdk-lib`)  
- Auth0 tenant with SPA app + API configured  
- Gmail API client credentials (OAuth2) for send/receive  
- Optional: DynamoDB Local (Docker) for local dev

## Setup

1) Backend (FastAPI on Lambda)  
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# For local dev without Lambda wrapper
uvicorn app.main:app --reload
```

2) Frontend (Vue 3 + Vite + Pico)  
```bash
npm install
npm run dev
```

3) Configure environment (example)  
```bash
cp .env.example .env
# Backend
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://funke-api
AUTH0_CLIENT_ID=...
AUTH0_CLIENT_SECRET=...
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
DYNAMODB_TABLE_PREFIX=funke-dev
REGION=eu-central-1
RATE_LIMIT_PER_MINUTE=10

# Frontend
VITE_API_BASE_URL=http://localhost:8000
VITE_AUTH0_DOMAIN=your-tenant.auth0.com
VITE_AUTH0_CLIENT_ID=...
VITE_AUTH0_AUDIENCE=https://funke-api
```

4) Local DynamoDB (optional)  
```bash
docker run -p 8000:8000 amazon/dynamodb-local
aws dynamodb create-table ... # match table schemas defined in CDK or a local bootstrap script
```

5) Run tests  
```bash
pytest               # FastAPI unit/contract tests
npm run test:unit    # Vitest frontend unit tests
npm run test:e2e     # Playwright flows: registration, lottery, offline sync
```

## Operational Notes

- Deploy with AWS CDK (Python): `cd infra/cdk && cdk bootstrap && cdk deploy` to provision API Gateway, Lambda, DynamoDB, S3/CloudFront.  
- Frontend built and uploaded to S3; CloudFront serves cached assets.  
- API Gateway enforces public endpoint throttling (10/min/IP).  
- Offline check-in: cache `/api/admin/events/{id}/check-in-list` in service worker; queued check-ins post to `/api/admin/check-ins` when back online.  
- Data retention: DynamoDB TTL set for 90-day post-COMPLETED purge; email retries handled via Lambda requeues or SQS DLQ.

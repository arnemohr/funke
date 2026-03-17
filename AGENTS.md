# funke Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-12-14

## Active Technologies
- Python (FastAPI backend, AWS Lambda runtime), Vue 3 (Composition API) frontend with Vite + FastAPI, pydantic, boto3, AWS CDK (Python), Auth0 SDK, Gmail API client, Vite, Vue Router, Pico CSS, Pinia, Vitest/Playwright for frontend, pytest for backend (001-funke-event-mgmt)
- DynamoDB with transactions for capacity/lottery and TTL for data purge; optional IndexedDB on frontend for offline check-in queue (001-funke-event-mgmt)
- Python (FastAPI backend on AWS Lambda), Vue 3 (Composition API) with Vite + FastAPI, pydantic, boto3, AWS CDK (Python), Auth0 SDK/JWT validation, Gmail API client, Vue Router, Pico CSS, Pinia, Vitest/Playwright (frontend), pytest (backend) (001-funke-event-mgmt)

## Project Structure

```text
src/
tests/
```

## Commands

npm test && npm run lint

## Code Style

TypeScript (Node.js 20 LTS) backend; React 18 (Vite) frontend: Follow standard conventions

## Recent Changes
- 001-funke-event-mgmt: Added Python (FastAPI backend on AWS Lambda), Vue 3 (Composition API) with Vite + FastAPI, pydantic, boto3, AWS CDK (Python), Auth0 SDK/JWT validation, Gmail API client, Vue Router, Pico CSS, Pinia, Vitest/Playwright (frontend), pytest (backend)
- 001-funke-event-mgmt: Added Python (FastAPI backend, AWS Lambda runtime), Vue 3 (Composition API) frontend with Vite + FastAPI, pydantic, boto3, AWS CDK (Python), Auth0 SDK, Gmail API client, Vite, Vue Router, Pico CSS, Pinia, Vitest/Playwright for frontend, pytest for backend

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->

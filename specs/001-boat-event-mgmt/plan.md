# Implementation Plan: Funke Event Management System

**Branch**: `001-funke-event-mgmt` | **Date**: 2025-12-14 | **Spec**: `/Users/arnemohr/git/arnemohr/funke/specs/001-funke-event-mgmt/spec.md`
**Input**: Feature specification from `/specs/001-funke-event-mgmt/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Core requirement: deliver funke event lifecycle support (create/publish events, capacity-aware registration with waitlist and lottery, confirmations, comms, admin dashboard, offline check-in). Technical approach: Vue 3 (Composition API) frontend styled with Pico CSS and built with Vite, FastAPI backend on Python deployed serverlessly via AWS Lambda + API Gateway, DynamoDB for data (with transactions/TTL), Auth0 for admin auth, Gmail API for send/receive, and AWS CDK (Python) for infra (Lambda, API Gateway, DynamoDB, S3/CloudFront) targeting ~€1-5/month.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python (FastAPI backend on AWS Lambda), Vue 3 (Composition API) with Vite  
**Primary Dependencies**: FastAPI, pydantic, boto3, AWS CDK (Python), Auth0 SDK/JWT validation, Gmail API client, Vue Router, Pico CSS, Pinia, Vitest/Playwright (frontend), pytest (backend)  
**Storage**: DynamoDB with transactions for capacity/lottery and TTL for data purge; optional IndexedDB on frontend for offline check-in queue  
**Testing**: pytest (backend unit/contract), FastAPI TestClient; Vitest + Playwright (frontend/E2E)  
**Target Platform**: AWS Lambda + API Gateway backend; S3 + CloudFront for static assets; modern desktop/mobile browsers (PWA for check-in)  
**Project Type**: Web (serverless backend API + frontend PWA)  
**Performance Goals**: Handle 500 concurrent registration attempts; p95 <400ms on registration endpoints under Lambda; emails dispatched <5 minutes; check-in interactive <2s on 3G with offline cache  
**Constraints**: Monthly infra target ~€1-5; offline-capable check-in; public endpoints rate limited to 10/min/IP; single-tenant; email-only comms via Gmail API  
**Scale/Scope**: Single organization, ~1 event/week, capacity 1-500 (default 100), max group size 10, registrant volume in low thousands

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Pre-Design Status: ERROR — `.specify/memory/constitution.md` is placeholder/undefined; governance, principles, and gates NEED CLARIFICATION before enforcement. Proceeding required temporary assumption set.

Post-Design Re-check: ERROR — Constitution still undefined. Interim guardrails applied: test critical flows (registration, lottery, offline sync), document API contracts (OpenAPI), enforce PWA offline plan, and validate Auth0/Gmail/DynamoDB integration paths. Formal compliance pending actual constitution content.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   ├── models/
│   ├── services/
│   ├── workers/          # async tasks via Lambda triggers (e.g., email retries)
│   └── main.py           # FastAPI entry for Lambda
└── tests/
    ├── contract/
    ├── integration/
    └── unit/

frontend/
├── src/
│   ├── pages/
│   ├── components/
│   ├── services/
│   ├── stores/
│   └── styles/           # Pico CSS overrides
└── tests/
    ├── e2e/
    └── unit/

infra/
└── cdk/                  # AWS CDK (Python) stacks for API Gateway, Lambda, DynamoDB, S3/CloudFront, Auth0 integration hooks
```

**Structure Decision**: Serverless web application split into FastAPI-on-Lambda backend, Vue PWA frontend, and shared CDK infra definitions for AWS resources (API Gateway, Lambda, DynamoDB, S3/CloudFront, Auth0 integration).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |

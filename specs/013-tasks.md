# 013 — Closing Report: PDF & Email — Tasks

## Phase 1: Data Model

### T1.1 — Report models
**File:** `backend/app/models/report.py` (new)
**Details:**
- Pydantic v2:
  - `EmailStatus` enum: `PENDING`, `SENT`, `FAILED`, `SKIPPED_NO_RECIPIENT`
  - `LineItem` submodel: `bar_item_name: str`, `qty: int`, `unit_price: Decimal`, `line_total: Decimal`
  - `ReportTotals` submodel: `kiosk_total`, `crew_cost`, `expenses_total`, `soll`, `cash_amount`, `cash_diff` (all Decimal)
  - `ReportVersion` — per-version snapshot, all fields per spec (snapshots stored as dict for flexibility; `version: int`, `pdf_s3_key: str | None`)
  - `ReportMeta` — aggregate state (id, tour_id, current_version, finance_recipient, email_status, email_attempts, email_last_error, email_last_attempt_at, sent_at, created_at, updated_at)
  - `ReportResponse` — ReportMeta + `versions: list[int]` (available version numbers) + optionally an embedded `selected_version: ReportVersion`
- Decimal for money, UTC datetimes

### T1.2 — DynamoDB key helpers
**File:** `backend/app/services/config.py`
**Details:**
- Constants:
  - `REPORT_PK_PREFIX = "REPORT#"`, `REPORT_SK_META = "META"`, `REPORT_SK_VERSION_PREFIX = "VERSION#"`
  - `TOUR_REPORT_SK = "REPORT"` (pointer row under a TOUR partition — one per Tour, holds `report_id`)
  - `REPORTS_LIST_PK = "REPORTS"`, SK format `{generated_at_iso}#{report_id}`
- Add env config fields to the `Settings` class: `finance_report_inbox: str | None`, `reports_s3_bucket: str | None`

### T1.3 — CDK: S3 bucket + IAM + env vars
**File:** `infra/` (CDK stack)
**Details:**
- New S3 bucket: private, versioning enabled, SSE, blocked public access
- Grant Lambda `s3:GetObject` / `s3:PutObject` on `{bucket}/reports/*`
- Add env vars to the Lambda: `FINANCE_REPORT_INBOX`, `REPORTS_S3_BUCKET`
- Add `.env.example` entries in `backend/.env.example`

### T1.4 — CDK: WeasyPrint Lambda Layer
**File:** `infra/` (CDK stack)
**Details:**
- Attach a pre-built WeasyPrint layer compatible with the project's runtime (Python 3.12, confirm arch)
- If no suitable prebuilt layer exists for arm64 on 3.12: build one via `docker run --rm -v ...` using the AWS Lambda Python image + pango/cairo/gdk-pixbuf
- Document in `infra/README.md`: how to refresh the layer

---

## Phase 2: Service Layer

### T2.0 — Extend `EmailMessage` with attachment support
**File:** `backend/app/services/email_client.py`
**Details:**
- Add `Attachment` submodel: `filename: str`, `content: bytes`, `content_type: str = "application/pdf"`
- Add `attachments: list[Attachment] = []` to `EmailMessage`
- In `SmtpClient._create_mime_message`, when `email.attachments` is non-empty, switch the outer container to `MIMEMultipart("mixed")` wrapping the existing text/alternative block, and `msg.attach(MIMEApplication(a.content, _subtype=..., name=a.filename))` per attachment with `Content-Disposition: attachment; filename="..."`
- Backward compatible: existing callers (confirmation emails, lottery notifications) pass no attachments; their MIME structure is unchanged
- Unit test: construct an `EmailMessage` with one PDF attachment, call `_create_mime_message`, assert the MIME tree contains one attachment part with the right filename/content-type

### T2.1 — ReportService skeleton
**File:** `backend/app/services/report_service.py` (new)
**Details:**
- Singleton + lazy init
- Methods: `create_or_update_report`, `send_report_email`, `render_pdf`, `get_report`, `get_report_version`, `list_reports`, `list_versions`, `get_report_for_tour`
- Uses `fahrbericht_service`, `tour_service`, `bar_service`, `email_client`, settings from `config.py`
- Email building reuses the pattern in `backend/app/services/email_service.py` — a `_build_report_email(meta, version_snapshot, pdf_bytes) -> EmailMessage` helper that constructs subject + body + attachment. Follows the project's house style: graceful `ValueError` handling, structured logging.

### T2.2 — Implement `create_or_update_report`
**File:** `backend/app/services/report_service.py`
**Details:**
- Signature: `create_or_update_report(tour_id: UUID, version: int) -> ReportMeta`
- Load pointer row `TOUR#{tour_id}` / `REPORT` to find an existing `report_id`; if none, generate a new UUID
- Build snapshots via `model_dump(mode='json')` for Fahrbericht, Tour, bar catalog subset
- Build summaries + `booking_text` using `booking_text.build_booking_text` from spec 012 T2.4
- `TransactWriteItems`:
  - PutItem `REPORT#{report_id}` / `VERSION#{version:04d}` with `ConditionExpression="attribute_not_exists(pk)"` (idempotency per version)
  - UpsertItem `REPORT#{report_id}` / `META` with `current_version = version`, reset email_status, etc.
  - PutItem `TOUR#{tour_id}` / `REPORT` pointer with `ConditionExpression="attribute_not_exists(pk)" OR report_id = :existing_id"` (first-time or matching existing)
- Kick off `send_report_email(report_id)` at the end (await + try/except so exceptions don't leak)

### T2.3 — Implement `send_report_email`
**File:** `backend/app/services/report_service.py`
**Details:**
- Signature: `send_report_email(report_id: UUID) -> None`
- Reads META for `current_version`, `finance_recipient`, skip flags
- Renders the current-version PDF via `render_pdf(report_id, current_version)`
- Builds the `EmailMessage` with the new `attachments` field (T2.0). Filename: `fahrbericht-{date}-v{N}.pdf`. Subject differs between v1 (first time) and v>=2 (Aktualisierung) per spec
- Use `email_client.get_gmail_client()` — handle `ValueError` gracefully (match the pattern in `email_service.py`)
- Update META with status/attempt/timestamps via `UpdateItem`
- Never raise; log with structured fields (report_id, version, attempt, error)

### T2.4 — Implement `render_pdf`
**File:** `backend/app/services/report_service.py`
**Details:**
- Signature: `render_pdf(report_id: UUID, version: int) -> bytes`
- Load the VERSION row for `(report_id, version)`
- If its `pdf_s3_key` is set: `GetObject` from S3 and return
- Otherwise:
  - Render Jinja2 template `report.html` with the version snapshot
  - Run through WeasyPrint: `HTML(string=html).write_pdf(stylesheets=[CSS(...)])`
  - Upload to `s3://{REPORTS_S3_BUCKET}/reports/{report_id}/v{version}.pdf`
  - `UpdateItem` on the VERSION row setting `pdf_s3_key`
  - Return bytes

### T2.5 — PDF template
**File:** `backend/app/templates/report.html`, `backend/app/templates/report.css` (new)
**Details:**
- HTML template mirrors the structure of the HTML prototype's summary + booking-text blocks
- CSS extracted + adapted from the prototype's `@media print` rules, A4 page size
- Header includes boat emoji + "Schaluppe Fahrbericht" + org tagline
- Footer: generation timestamp + short report id + confidentiality note

---

## Phase 3: API Routes

### T3.1 — Report router
**File:** `backend/app/api/admin/reports.py` (new)
**Details:**
- `APIRouter(prefix="/reports", tags=["admin.reports"])`
- Endpoints per spec: list, get, get-version, pdf (current_version), versioned-pdf, resend
- PDF endpoints: `StreamingResponse` over the bytes with `Content-Disposition: attachment; filename="fahrbericht-{date}-v{N}.pdf"`

### T3.2 — Tour/report convenience route
**File:** `backend/app/api/admin/tours.py` (from spec 010)
**Details:**
- Add `GET /tours/{tour_id}/report` → delegates to `report_service.get_report_for_tour`
- Returns 404 when no report exists

### T3.3 — Register router
**File:** `backend/app/main.py`
**Details:**
- `app.include_router(reports_router, prefix="/api/admin")`

---

## Phase 4: Spec 012 integration

### T4.1 — Call `create_or_update_report` from submission pipeline
**File:** `backend/app/services/fahrbericht_service.py`
**Details:**
- Confirms spec 012 T2.2's step: after bar + ship side effects, call `report_service.create_or_update_report(tour_id, version=<new>)` and capture `report.id`
- Persist `report_id` on the Fahrbericht via `UpdateItem` (first submit only — subsequent versions reuse the same id)

### T4.2 — Reapply path must also retry report creation/email
**File:** `backend/app/services/fahrbericht_service.py`
**Details:**
- Confirms spec 012 T2.3: `reapply_side_effects` calls `create_or_update_report(tour_id, current_fahrbericht_version)` (idempotent per version) and then `send_report_email(existing.id)` (no-op if the current version is already SENT)

---

## Phase 5: Frontend — API & Pages

### T5.1 — Reports admin API client
**File:** `frontend/src/services/api.js`
**Details:**
- `adminApi.reports`:
  - `list(params)`, `get(id)`, `getVersion(id, version)`, `listVersions(id)`, `resend(id)`, `getForTour(tourId)`
  - PDF URL helpers: `pdfUrl(id)` → `/api/admin/reports/{id}/pdf`; `versionPdfUrl(id, version)` → `/api/admin/reports/{id}/versions/{version}/pdf` (the app attaches the Auth0 bearer via fetch interceptors; confirm that `<a href>` downloads work — if not, fetch the PDF and open it via Blob URL)

### T5.2 — ReportsListPage
**File:** `frontend/src/pages/admin/ReportsListPage.vue` (new)
**Details:**
- Route: `/admin/reports`
- Filter tabs Alle/Versendet/Fehler/Ohne Empfänger
- Rows with status badge, version badge (e.g. "v3"), and "PDF öffnen" icon button for the current_version
- Empty state message per spec

### T5.3 — ReportDetailPage
**File:** `frontend/src/pages/admin/ReportDetailPage.vue` (new)
**Details:**
- Route: `/admin/reports/:id` (optional `?version=N` query param; defaults to `current_version`)
- Fetches META + selected VERSION snapshot
- Version selector dropdown when `current_version > 1`; selecting an older version reloads the snapshot via `/reports/{id}/versions/{N}`
- Sections per spec (header with version badge, summary tiles, booking text, line items, expenses, ship snapshot)
- Actions: PDF öffnen (selected version), Erneut senden (always current_version — show a confirmation when viewing older version), Zur Tour
- Inline note when viewing a non-current version
- Warning banner for META `SKIPPED_NO_RECIPIENT`
- Reuse `useToast` from spec 008 for resend feedback

### T5.4 — Status badge styles
**File:** `frontend/src/assets/design-tokens.css`, `frontend/src/utils/formatters.js`
**Details:**
- Add `.status-sent`, `.status-pending`, `.status-failed`, `.status-skipped` classes reusing existing tokens (success / neutral / danger / muted)
- Add `formatEmailStatus()` returning German labels

### T5.5 — Router + Nav
**File:** `frontend/src/router/index.js`, `frontend/src/pages/admin/SettingsPage.vue`
**Details:**
- Register `/admin/reports` and `/admin/reports/:id` behind admin guard
- Add "Fahrberichte" entry under the "Schaluppe" section in SettingsPage
- Also link from the Fahrbericht SubmittedView (spec 012 T5.9) via "Bericht ansehen"

### T5.6 — Link from TourDetailPage
**File:** `frontend/src/pages/admin/TourDetailPage.vue`
**Details:**
- Under the Fahrbericht tab, when a submitted report exists, add a secondary "Bericht öffnen" link → `/admin/reports/{id}`

---

## Phase 6: Tests

### T6.1 — Report service unit tests
**File:** `backend/tests/unit/test_report_service.py` (new)
**Details:**
- `moto[dynamodb]` + `mock_aws` + mocked S3 + mocked SMTP client (patch at source: `app.services.email_client.get_gmail_client` per project memory note)
- Cases:
  - `create_or_update_report(tour_id, version=1)` happy path → META + VERSION#0001 + pointer row written
  - `create_or_update_report(tour_id, version=2)` → META updated to v2, VERSION#0002 appended, pointer row unchanged, report_id stable
  - Duplicate `create_or_update_report(tour_id, version=1)` → idempotent, no duplicate items (conditional put catches)
  - Missing `FINANCE_REPORT_INBOX` → META.email_status = SKIPPED_NO_RECIPIENT
  - `send_report_email` SMTP misconfig (ValueError) → SKIPPED_NO_RECIPIENT, no exception
  - `send_report_email` SMTP error → FAILED, error persisted
  - `send_report_email` success for v2 → SENT, subject includes "Aktualisierung v2", sent_at updated

### T6.2 — PDF renderer smoke test
**File:** `backend/tests/unit/test_report_pdf.py` (new)
**Details:**
- Fixture Report → call `render_pdf` → assert PDF starts with `%PDF-` and has >0 pages (parse with a lightweight lib or just check magic bytes + size)
- Mock S3 client to avoid network

### T6.3 — HTML template snapshot
**File:** `backend/tests/unit/test_report_template.py` (new)
**Details:**
- Jinja2 render the template directly (skip WeasyPrint) and snapshot-compare the HTML
- Catches layout regressions without pixel-diffing a PDF

### T6.4 — API contract tests
**File:** `backend/tests/contract/test_report_routes.py` (new)
**Details:**
- Auth guard
- List, get, resend — happy path + missing id
- PDF endpoint returns `application/pdf` content type with a sensible filename

### T6.5 — End-to-end smoke
**File:** (PR checklist)
**Details:**
- Configure `FINANCE_REPORT_INBOX=arne+test@…` in a staging deploy
- Submit a Fahrbericht → inspect the received email + PDF attachment
- Resend from the UI → verify the attempt counter increments

---

## Phase 7: Documentation & Deploy

### T7.1 — Document env vars + setup
**File:** `README.md`, `backend/.env.example`, `AGENTS.md`
**Details:**
- README: add a "Finance report delivery" section — how to set `FINANCE_REPORT_INBOX`, where the S3 bucket is, how to resend manually
- `.env.example`: placeholders for the two new vars
- `AGENTS.md`: short note linking to `report_service.py` and `booking_text.py`

### T7.2 — Runbook
**File:** `docs/runbook-reports.md` (new)
**Details:**
- What to do when a report is FAILED
- Where to find the PDF in S3 if the email is lost
- How to bulk-resend (loop over list endpoint — ad-hoc script or a future feature)

---

## Execution Order

```
T1.1 → T1.2 → T1.3 → T1.4                              (Model + keys + infra)
  ↓
T2.0                                                   (Extend EmailMessage with attachments — lands first, unblocks T2.3)
  ↓
T2.1 → T2.5 → T2.4 → T2.2 → T2.3                       (Service — template needs to exist before create_or_update_report fills booking_text; render_pdf before send_report_email)
  ↓
T3.1 → T3.2 → T3.3                                     (API)
  ↓
T4.1 → T4.2                                            (Wire into spec 012 submission)
  ↓
T5.4 → T5.1 → T5.2 → T5.3 → T5.5 → T5.6                (Frontend)
  ↓
T6.1 → T6.2 → T6.3 → T6.4 → T6.5                       (Tests + smoke)
  ↓
T7.1 → T7.2                                            (Docs)
```

Note: a portion of T2.2 (`create_report`) has to be written alongside spec 012 T2.2 — they form one submission pipeline. Coordinate execution so the integration lands in a single PR or at least two tightly-sequenced PRs.

# 013 — Closing Report: PDF & Email

## Summary

On Fahrbericht submission (spec 012), persist a **Closing Report** as a standalone DynamoDB record, render a PDF on demand with **WeasyPrint**, and email it to the finance team at a configurable inbox using the **existing SMTP email pipeline** (`backend/app/services/email_client.py` + `email_service.py`).

Finance asks for two things: a durable artifact per tour (so they can file and reconcile) and delivery to their inbox (so they don't have to log in). This spec is the capstone that turns a submitted Fahrbericht into both.

Reports are **versioned**: every Fahrbericht (re-)submission in spec 012 produces a new Report version, a fresh PDF, and a fresh email ("Aktualisierung"). Earlier versions remain accessible in the admin UI for audit.

## Problem

1. The HTML prototype stops at "🖨 Drucken / PDF speichern". Nothing is stored; nothing is sent.
2. Without a persisted report, later edits to the bar catalog, tour metadata, or ship state could change how historical trips look — there's no immutable record of what was booked.
3. Finance needs the booking text + line items in their inbox, not another dashboard to check.
4. Without a retry path, a single Gmail outage would silently lose the report.

## Scope

- A `Report` entity persisted in DynamoDB that captures the Fahrbericht data at submission time (immutable snapshot).
- Routes to list reports, fetch metadata, render PDF, resend email.
- PDF renderer that produces the HTML prototype's visual layout (`~/Downloads/schaluppe-fahrbericht.html` print view) from the Report data.
- Gmail send via existing `email_client.py` to an env-configurable finance address. Subject + body derived from the Report; PDF attached.
- Admin UI: Reports list, Report detail with PDF link and resend button.
- Retry semantics: failures don't block submission; manual resend + reapply side effects from spec 012 handle recovery.

Out of scope:

- Automated scheduled retry (manual resend only for MVP).
- Multiple recipient support (single env-configured address — future spec could add CC/BCC or a recipient list).
- Finance-side actions (approve, mark paid, etc.).
- Analytics across reports (e.g. monthly revenue summaries) — deferred.

## Data Model

### Report

A Report has a **stable id per Tour** and one or more **versions**.

DynamoDB keys:
- `pk = REPORT#{report_id}`, `sk = META` — latest metadata (status, email state, current version)
- `pk = REPORT#{report_id}`, `sk = VERSION#{version:04d}` — immutable per-version snapshot
- `pk = TOUR#{tour_id}`, `sk = REPORT` — pointer row holding only the `report_id` (one per Tour)

Per-version snapshot fields:

| Field | Type | Notes |
|-------|------|-------|
| `report_id` | UUID | Stable across versions |
| `version` | int | 1, 2, 3, … — matches the Fahrbericht `version` it was created from |
| `tour_id` | UUID | Parent Tour |
| `fahrbericht_snapshot` | JSON | Full serialized Fahrbericht at this submission |
| `tour_snapshot` | JSON | Serialized Tour fields at this submission |
| `bar_catalog_snapshot` | JSON | `{bar_item_id: {name, serving_unit, package_unit, servings_per_package, category, note, ek, kb}}` for every item referenced in the tallies |
| `kiosk_summary` | list[`LineItem`] | `{bar_item_name, qty, unit_price_kb, line_total}` |
| `crew_summary` | list[`LineItem`] | Same shape with EK |
| `expenses_summary` | list[`ExpenseLine`] | Copy of `expenses` |
| `totals` | obj | `{kiosk_total, crew_cost, expenses_total, soll, cash_amount, cash_diff}` |
| `booking_text` | str | Pre-rendered booking text (see spec 012 template) |
| `pdf_s3_key` | str \| None | Cached after first PDF render for this version |
| `generated_at` | datetime | UTC |

META row fields (aggregate state, overwritten on each new version):

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | Report id |
| `tour_id` | UUID | Parent Tour |
| `current_version` | int | Points at the latest VERSION row |
| `finance_recipient` | str | Effective recipient at the time of the last send attempt |
| `email_status` | enum | `PENDING`, `SENT`, `FAILED`, `SKIPPED_NO_RECIPIENT` — for the **current_version** email |
| `email_attempts` | int | Attempts for the current version |
| `email_last_error` | str \| None | |
| `email_last_attempt_at` | datetime \| None | |
| `sent_at` | datetime \| None | Last successful send (any version) |
| `created_at` | datetime | First version's generated_at |
| `updated_at` | datetime | Set whenever current_version advances |

### Why snapshots?

Later stock edits, catalog renames, or deactivations must not silently change the content of a historical report. The Report version is the authoritative record for finance. All human-readable fields (names, prices, totals) come from the per-version snapshot, not from live data.

### GSIs

- `GSI_REPORTS_BY_DATE`: `pk = REPORTS`, `sk = {generated_at_iso}#{report_id}` — list/pagination newest-first. Projected from the META row only.

## Service Contract: `create_or_update_report`

Called by spec 012's submission pipeline with the Fahrbericht's new `version`.

```python
async def create_or_update_report(tour_id: UUID, version: int) -> Report:
    ...
```

1. Fetch the Fahrbericht (must be SUBMITTED, version must equal the argument).
2. Fetch the Tour.
3. Fetch the subset of the bar catalog referenced in the tallies.
4. Build snapshots (Fahrbericht, Tour, catalog subset).
5. Compute summaries (kiosk_summary, crew_summary, expenses_summary, totals) — same formulas as spec 012's computed block, same `booking_text` via `booking_text.build_booking_text`.
6. Look up the existing Report META row for the Tour via the TOUR#→REPORT pointer:
   - Not found → this is the first version. Create META with `current_version = 1` and VERSION#0001.
   - Found → reuse the existing `report_id`. Write VERSION#{version:04d} with the new snapshot; conditional-put prevents re-writing an existing version row (idempotent retries).
7. Update META: `current_version = version`, reset `email_status = PENDING`, `email_attempts = 0`, `email_last_error = None`, `updated_at = now`.
8. Determine `finance_recipient` from env `FINANCE_REPORT_INBOX`. If unset → set META `email_status = SKIPPED_NO_RECIPIENT`.
9. Kick off `send_report_email(report_id)` (same process; no queue for MVP).

Idempotent on retry: conditional `PutItem` on `VERSION#{version:04d}` ensures the snapshot is written at most once per version. A repeated call for the same `(tour_id, version)` returns the existing Report unchanged.

## Service Contract: `send_report_email`

```python
async def send_report_email(report_id: UUID) -> None:
    ...
```

- Early-exit when `email_status = SENT` (for the current_version) or `email_status = SKIPPED_NO_RECIPIENT`.
- Early-exit when `finance_recipient` is unset.
- Render PDF via `render_pdf(report_id, version=current_version)` (caches in S3 if not already present).
- Build email:
  - Subject: `"Schaluppe Fahrbericht – {date} – {tour_name}"` for version 1; `"Schaluppe Fahrbericht (Aktualisierung v{N}) – {date} – {tour_name}"` for version ≥ 2.
  - Body: booking text + a short lead sentence ("Hallo Finance-Team, anbei der Fahrbericht der Schaluppe vom {date}." or "…anbei die aktualisierte Version v{N} des Fahrberichts…").
  - PDF attached as `fahrbericht-{date}-v{N}.pdf`.
- **Reuse the existing SMTP email pipeline** at `backend/app/services/email_client.py`:
  - Call `email_client.get_gmail_client()` (kept for backward-compat; under the hood it's the SMTP client — see note on email infra below).
  - Use the existing graceful `ValueError` handling pattern from `email_service.py` when SMTP credentials are missing.
- On success: set `sent_at`, META `email_status = SENT`, increment `email_attempts`.
- On failure: set META `email_status = FAILED`, `email_last_error`, increment `email_attempts`. Do not raise — the caller (spec 012's submission pipeline) treats this as a post-commit side effect.

### Email infrastructure reuse

The app ships with a working SMTP-based email pipeline:

- `backend/app/services/email_client.py` defines `EmailMessage`, `SmtpClient`, and `get_gmail_client()` (the function is named for historical reasons; implementation is plain SMTP via Strato — see spec 009's commit history).
- `backend/app/services/email_service.py` is the project's house style for building emails: graceful `ValueError` fallback when unconfigured, structured logging, consistent subject/body builders per flow.

This spec **reuses both files**. The only extension needed is attachment support on `EmailMessage`, because guest-facing emails are all plain text/HTML today — there is no PDF attachment path yet. See Task T2.0 in the tasks file for the small, backward-compatible addition.

No separate Gmail API layer is introduced. No third-party email service (SendGrid etc.) is introduced. All report emails flow through the same SMTP server already used for confirmations and lottery notifications.

## Service Contract: `render_pdf`

```python
async def render_pdf(report_id: UUID, version: int) -> bytes:
    ...
```

- Look up the VERSION row for `(report_id, version)`; if it has a `pdf_s3_key` and the object exists, return its bytes.
- Otherwise render with WeasyPrint from an HTML template (see Rendering below), upload to S3 at `reports/{report_id}/v{version}.pdf`, set `pdf_s3_key` on the VERSION row, return bytes.

### Rendering engine: **WeasyPrint** (locked)

Picked because:
- The HTML prototype already has a working print layout (`~/Downloads/schaluppe-fahrbericht.html` lines 116–121). Reusing the same HTML+CSS structure via a Jinja2 template keeps visual parity with the on-screen summary and minimizes duplicate layout work.
- German typography and right-to-left-safe glyph handling are mature.
- Pure HTML/CSS lets the marketing/design team iterate without touching Python drawing primitives.

**Trade-off acknowledged**: WeasyPrint needs native libraries (pango, cairo, gdk-pixbuf). Shipped via a **Lambda Layer** — either a prebuilt one (e.g. `kotaimen/python-weasyprint-lambda-layer`) or one we build ourselves using the AWS Lambda Python Docker image + pango/cairo/gdk-pixbuf. First deploy attaches the layer; subsequent reports pay only the render-time cost.

ReportLab was considered and rejected: pure Python, but re-implementing the prototype's CSS-grid layout in ReportLab drawing primitives is a non-trivial port.

### Template

- `backend/app/templates/report.html` (new) — Jinja2, mirrors the HTML prototype's summary and booking-text layout.
- `backend/app/templates/report.css` (new) — extracted print styles from the prototype, adjusted for A4.
- Header: "Schaluppe Fahrbericht — Verein für mobile Machenschaften e.V."
- Sections: Fahrtinfo / Crew, Kiosk-Einnahmen, Crew-Verköstigung, Ausgaben, Kassenabgleich, Buchungstext, Ship-Status snapshot, Offene Todos + Notizen.
- Footer: generated timestamp, report id (short form), "vertraulich — nur für internen Gebrauch".

## API

All admin routes under `/api/admin/`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/reports` | Paginated list (newest first). Query: `status`, `limit`, `cursor`, `from_date`, `to_date`. META rows only |
| `GET` | `/reports/{id}` | Metadata + list of available versions |
| `GET` | `/reports/{id}/versions/{version}` | Per-version snapshot (for the detail page's body) |
| `GET` | `/reports/{id}/pdf` | Streams the PDF for `current_version` (renders on first call, caches after) |
| `GET` | `/reports/{id}/versions/{version}/pdf` | Streams a specific version's PDF |
| `POST`| `/reports/{id}/resend` | Triggers `send_report_email` again for the current_version; returns updated metadata |
| `GET` | `/tours/{tour_id}/report` | Convenience: returns the Report META for this Tour or 404 |

Internal-only:
- `POST /reports` is **not** exposed publicly — report creation is driven by spec 012's submission pipeline only.

## Configuration

Backend env vars (new):

- `FINANCE_REPORT_INBOX` — email address to receive reports. If unset, reports land as `SKIPPED_NO_RECIPIENT`.
- `REPORTS_S3_BUCKET` — S3 bucket for PDF storage. Private, versioning on, lifecycle: none (reports are retained indefinitely).

CDK changes:

- New S3 bucket + IAM policy granting the Lambda `GetObject`/`PutObject` on `reports/*`.
- New env vars wired into the Lambda.
- Optional: Lambda Layer for WeasyPrint.

Document both in `backend/.env.example`.

## UI

### Routes

- `/admin/reports` — list
- `/admin/reports/{id}` — detail

### Reports list (`/admin/reports`)

- PageHeader: "Fahrberichte" with small count badge
- Filter tabs: "Alle", "Versendet", "Fehler", "Ohne Empfänger"
- Each row: date, tour name, finance recipient (muted), status badge, right-aligned "PDF öffnen" icon button
- Empty state: "Noch keine Berichte. Der erste wird nach Abschluss einer Fahrt hier auftauchen."

### Report detail (`/admin/reports/{id}`)

Top section:
- Header with status badge and version selector ("Version {current}" with a dropdown of older versions when `current_version > 1`)
- Summary tiles: Datum, Tour, Empfänger, Soll, Ist, Differenz (from the selected version's snapshot)

Body:
- Booking text block (monospaced, "Text kopieren" button — same visual as spec 012 Abschluss tab)
- Kiosk + Crew line-item tables rendered from the selected version's snapshot
- Expenses (if any)
- Ship-status snapshot (read-only tile grid)

Actions (right-side column on desktop, sticky bar on mobile):
- "PDF öffnen" → opens `/api/admin/reports/{id}/versions/{selected_version}/pdf` in a new tab
- "Erneut senden" → calls resend (always sends the current_version); shows loading state; toast on success/failure
- "Zur Tour" → `/admin/tours/{tour_id}`
- When viewing an older version, show a small inline note: "Dies ist eine ältere Version. Aktuell ist v{current_version}."

Warning banner when META `email_status = SKIPPED_NO_RECIPIENT`: "Kein Empfänger konfiguriert. Setz `FINANCE_REPORT_INBOX` im Backend und drück dann auf Erneut senden."

### Integration with spec 012

- When a Fahrbericht is SUBMITTED, spec 012's view includes a "Bericht ansehen" link → `/admin/reports/{id}`.
- The report id is stored on the Fahrbericht (spec 012 T2.2) — the view reads it directly.

## Failure handling

- **Email unconfigured at submit time**: report persists with `SKIPPED_NO_RECIPIENT`. No error shown as a submission failure. Warning shown in the UI.
- **Email send throws**: report persists with `FAILED`, error message stored. Admin resends manually. Submission is not reversed.
- **PDF render throws**: email sending is skipped for that attempt (we need the attachment). Report stays `FAILED` with error. Admin can resend — the renderer retries.
- **S3 upload throws**: render still returns the in-memory bytes to the caller; `pdf_s3_key` stays unset. Next render attempt will retry the upload.

Metrics (CloudWatch): `ReportCreated`, `ReportEmailSent`, `ReportEmailFailed`, `ReportPdfRendered`, `ReportPdfRenderFailed`. Alarm on `ReportEmailFailed > 0 in 15m`.

## Testing

- Unit tests for `report_service.create_report` with a fake `fahrbericht_service` + `tour_service` + `bar_service`:
  - Happy path → snapshot fields populated, email kicked off
  - Idempotent repeat call with same tour_id → no duplicate
  - Missing `FINANCE_REPORT_INBOX` → report saved with `SKIPPED_NO_RECIPIENT`, email not attempted
- `send_report_email` tests with mocked Gmail client:
  - Success path increments attempts, sets `sent_at`
  - Gmail `ValueError` (misconfig) → `SKIPPED_NO_RECIPIENT`, no exception
  - Gmail exception → `FAILED`, no exception re-raised
- `render_pdf`: golden fixture comparison on the rendered HTML (not pixel-level on the PDF); separate smoke test that asserts valid PDF bytes.
- Contract tests for each route.
- Manual smoke test: configure `FINANCE_REPORT_INBOX=arne+test@…`, submit a Fahrbericht end-to-end, confirm email arrives with PDF.

## Backward compatibility

- Purely additive. Existing Events, Registrations, and (for specs 010–012 integration) existing Tours without Fahrberichte are unaffected.
- `FINANCE_REPORT_INBOX` unset on first deploy is handled gracefully — reports land as `SKIPPED_NO_RECIPIENT` with a visible warning. Operators set the env var, then press "Erneut senden" per report.
- The WeasyPrint layer deployment is a one-time CDK change; rollback means removing the layer + unsetting the env vars. No data migration.

## Offene Fragen

1. **PDF engine**: **WeasyPrint locked in**. The only implementation risk is the Lambda Layer on Python 3.12 — verify arch (arm64 vs x86_64) on first deploy and pick a compatible prebuilt layer, or build one via Docker.
2. **Scheduled retry** of FAILED emails: out of scope for MVP (manual resend). If failure rate turns out painful, add EventBridge scheduled retry of `email_status = FAILED` reports — e.g. every hour with exponential backoff capped at 24h.
3. **Recipient list vs single address**: MVP uses one env var. If finance wants CC or multiple addresses, split into a list (comma-separated env var or backend setting).
4. **Superseded-version notification**: when a v2 email goes out, do we want to include a "vorherige Version v1" note in the subject/body so finance can align filings? MVP: yes, bake into the subject line. Confirm wording with the real finance team.
5. **PDF storage retention**: MVP retains indefinitely. Add S3 lifecycle rule (e.g. move to Glacier after 1 year) if storage cost matters.
6. **Accountant-facing format**: the booking text follows the HTML's SKR04 account convention (8400, 4220). Confirm with the real accountant before first live report — a mismatch would require a quick template fix.

# 012 — Fahrbericht Form

## Summary

The **Fahrbericht** is the main crew flow per tour: a multi-tab form the Funker*in fills in during or after the trip. It captures trip info + crew, bar consumption (kiosk vs crew), ship status, cash, and expenses. It autosaves as a DRAFT while editing and transitions to SUBMITTED on a single confirmation step. Submission mutates the Bar catalog and Ship state (spec 011) and triggers report generation (spec 013).

This spec replaces the standalone HTML prototype at `~/Downloads/schaluppe-fahrbericht.html` with a version that lives in the app: authenticated, persistent, shareable across devices, and integrated with the other Funke data models.

## Problem

1. The HTML prototype is **local-only** — all state lives in `localStorage`. If two crew members open the form on different phones, they see different data. Losing the device loses the report.
2. The HTML **doesn't talk to the app** — consumption doesn't decrement stock, ship status doesn't update the dashboard, cash totals don't land in a durable record.
3. Submission is **just a print button** — no record is created, no email is sent, nothing is stored for the finance team.
4. Crews need to be able to **pick up where they left off**: start the Fahrbericht during boarding, add consumption during the trip, finish it on the way back — possibly across multiple sessions and devices.

## Scope

- The Fahrbericht data model, API (GET/PUT/submit), and validation.
- The five-tab frontend form (Fahrt / Kiosk / Crew / Schiff / Abschluss) with autosave, live totals, and a sticky summary bar.
- The submission pipeline: transition state, call `bar_service.apply_consumption`, call `ship_service.apply_ship_status`, transition Tour to COMPLETED, hand off to spec 013 for report generation + email.
- Booking-text generation for Leasy / NetXp.

Out of scope:

- The PDF itself, Report persistence, email delivery — all handled by spec 013.
- Multi-ship support.

## Data Model

### Fahrbericht

DynamoDB keys: `pk = TOUR#{tour_id}`, `sk = FAHRBERICHT`.

Co-located with the Tour (same partition) so a single `Query(pk = TOUR#{id})` returns both.

| Field | Type | Notes |
|-------|------|-------|
| `tour_id` | UUID | 1:1 with Tour (enforced by the sk) |
| `status` | enum | `DRAFT`, `SUBMITTED` |
| `version` | int | Starts at 0 for DRAFT. Each successful SUBMITTED transition increments this. Re-opening a SUBMITTED report for editing bumps status back to DRAFT without incrementing version; the version is only bumped at the *next* submit |
| `boarding_fee` | Decimal | `Umlage Boarding` — flat fee per event, €. Defaults 0 |
| `bar_surcharge` | Decimal | `Umlage Bar` — flat surcharge, €. Defaults 0 |
| `kiosk_tally` | dict[UUID, int] | Map bar_item_id → quantity consumed by guests. Sparse — missing id means 0 |
| `crew_tally` | dict[UUID, int] | Map bar_item_id → quantity consumed by crew |
| `applied_kiosk_tally` | dict[UUID, int] | The tally **as it was applied** to the Bar catalog at the last submission. Used to compute deltas on re-submit. Empty before the first submit |
| `applied_crew_tally` | dict[UUID, int] | Same for crew |
| `applied_ship_notes_ids` | list[UUID] | Ids of notes previously appended to Ship state — lets re-submit skip duplicates |
| `applied_ship_todos_ids` | list[UUID] | Ids of todos previously appended to Ship state |
| `ship_status` | `ShipStatusSnapshot` | Embedded snapshot — see spec 011 |
| `new_notes` | list[str] | Free-text ship notes added during this tour |
| `new_todos` | list[str] | New open todos surfaced during this tour |
| `cash_amount` | Decimal \| None | Bargeld im Umschlag, € |
| `cash_handed_to` | str \| None | Name of the person who received the envelope |
| `expenses` | list[`ExpenseLine`] | Each: `{description, amount}` |
| `submitted_at` | datetime \| None | Set on the latest DRAFT → SUBMITTED transition |
| `submitted_by` | str \| None | Auth0 sub of the last submitter |
| `report_id` | UUID \| None | Populated by spec 013 on submit (stable across re-submits) |
| `created_at` | datetime | UTC |
| `updated_at` | datetime | UTC |

`kiosk_tally` and `crew_tally` are stored as DynamoDB maps (sparse). Entries referencing a bar item that has since been deleted are tolerated on read but filtered out in summaries.

### Computed (not stored)

- `kiosk_total = Σ qty * bar_item.kb` across `kiosk_tally`
- `crew_cost = Σ qty * bar_item.ek` across `crew_tally`
- `expenses_total = Σ expenses[i].amount`
- `soll = kiosk_total + boarding_fee + bar_surcharge`
- `cash_diff = cash_amount − soll`

These are re-computed on every read / render. They are **also** recomputed at submission time and passed to spec 013 so the Report snapshot is consistent with what the user saw.

## Lifecycle

```
(no Fahrbericht) ──► DRAFT (autosaved) ──► SUBMITTED  ──► SUBMITTED (v+1)
                       │                       │
                       │   "Bearbeiten"        │
                       └── deleted by admin    └── re-opened → DRAFT (reopened)
                           before first submit     (same id, same report_id)
```

- **DRAFT (first)**: `version=0`, fully editable. Autosaved on every meaningful change. Multiple authenticated crew members can open and edit the same DRAFT; last write wins (no CRDT — surface a subtle toast when another session saves newer data).
- **SUBMITTED**: `version=N (N≥1)`. Read-only *by default* but reversible: a "Bearbeiten" button reopens the report into a DRAFT. The underlying DynamoDB item is not duplicated — same `tour_id` / `sk = FAHRBERICHT`.
- **DRAFT (reopened)**: same editable experience as the first draft. `applied_kiosk_tally` / `applied_crew_tally` are preserved so a later submit can compute the delta.
- A new submit of a reopened DRAFT increments `version` and re-runs the submission pipeline with **delta semantics** instead of full re-apply (see below).

### Submission pipeline (first submit — `version 0 → 1`)

```
1. Validate DRAFT has minimum required fields (see Validation)
2. Transaction begin
   a. Update Fahrbericht: status=SUBMITTED, version=1, submitted_at, submitted_by
   b. Transition Tour to COMPLETED (via tour_service — spec 010)
3. Transaction commit
4. Post-commit side effects (best-effort; failure does not revert submission):
   a. bar_service.apply_consumption(tour_id, version=1, kiosk_tally, crew_tally)
      → persist applied_kiosk_tally, applied_crew_tally on the Fahrbericht
   b. ship_service.apply_ship_status(tour_id, version=1, ship_status, new_notes, new_todos)
      → persist applied_ship_notes_ids, applied_ship_todos_ids on the Fahrbericht
   c. report_service.create_or_update_report(tour_id, version=1) (spec 013)
5. Return the SUBMITTED Fahrbericht + ConsumptionResult warnings + report_id
```

### Re-submission pipeline (edit + re-submit — `version N → N+1`)

```
1. Validate DRAFT (same rules)
2. Transaction begin
   a. Update Fahrbericht: status=SUBMITTED, version=N+1, submitted_at, submitted_by
   b. Keep Tour at COMPLETED (no-op)
3. Transaction commit
4. Post-commit side effects, each with version=N+1:
   a. bar_service.apply_consumption_delta(
          tour_id, version=N+1,
          previous=applied_kiosk_tally + applied_crew_tally,
          next=kiosk_tally + crew_tally,
      )
      → writes diff = next - previous as the new delta, idempotent per version
      → updates applied_*_tally on Fahrbericht
   b. ship_service.apply_ship_status_versioned(
          tour_id, version=N+1, ship_status,
          previously_applied_notes=applied_ship_notes_ids,
          previously_applied_todos=applied_ship_todos_ids,
          new_notes, new_todos,
      )
      → overwrites scalar fields from the snapshot; appends only notes/todos whose ids are NOT in the previously-applied lists; removes any previously-applied note/todo whose id was dropped from the reopened draft (edit implies intent)
      → updates applied_*_ids
   c. report_service.create_or_update_report(tour_id, version=N+1) (spec 013)
      → creates a new Report version (see spec 013) and triggers an update email
5. Return the SUBMITTED Fahrbericht + warnings + report_id
```

**Why post-commit instead of inside the transaction?** DynamoDB supports a 100-item TransactWriteItems limit and cannot mix GSI index items with complex conditional writes across multiple partitions. Two strategies:

- **Strategy A (MVP, chosen)**: Fahrbericht status + Tour status update inside one `TransactWriteItems`. Bar/Ship/Report mutations are post-commit. Each uses a **versioned** idempotency marker (spec 011's `CONSUMPTION#{tour_id}#v{version}` and `STATE#{tour_id}#v{version}`, spec 013's `REPORT#{id}#v{version}`), so retrying the side effects is safe and re-submissions can distinguish old from new state. The API server retries once on failure; a scheduled sweeper (future scope) can reconcile any stragglers.
- **Strategy B (rejected for MVP)**: one giant TransactWriteItems. Too complex; surfaces DynamoDB transaction quota errors; item count can exceed 100 on big tallies.

If any post-commit side effect fails, the submission is **still considered successful** (the Fahrbericht is in SUBMITTED state). The UI surfaces a warning: "Konsum- oder Schiffsdaten konnten nicht sofort aktualisiert werden — retry läuft im Hintergrund." A "Jetzt erneut anwenden" button calls a dedicated endpoint `POST /tours/{id}/fahrbericht/reapply-side-effects` that re-runs steps 4a-c idempotently against the **current** `version`.

## Validation

Required before DRAFT → SUBMITTED transition:

- `tour.date` is set (spec 010 guarantees this).
- At least one of: a non-zero kiosk_tally, crew_tally, expenses list, or a filled cash_amount. (Prevents accidental empty submits.)
- If `cash_amount` is set, `cash_handed_to` is required.
- If `cash_amount` is set, the absolute `cash_diff` is shown to the user; if `> 5€` the submit confirmation sheet displays a warning but does not block submission.
- Every `bar_item_id` referenced in the tallies must exist and be `active=true` at submission time (consistent with the catalog rendered during editing).

Autosave is always permitted — no validation blocks DRAFT writes.

## API

Under `/api/admin/` behind Auth0 admin guard.

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/tours/{tour_id}/fahrbericht` | Returns the Fahrbericht (DRAFT or SUBMITTED) or 404 |
| `POST` | `/tours/{tour_id}/fahrbericht` | Create a blank DRAFT for this Tour. 409 if one already exists |
| `PUT`  | `/tours/{tour_id}/fahrbericht` | Upsert DRAFT. 409 if status is SUBMITTED |
| `POST` | `/tours/{tour_id}/fahrbericht/submit` | Submit a DRAFT → SUBMITTED (increments `version`). 409 if already SUBMITTED or missing validation requirements |
| `POST` | `/tours/{tour_id}/fahrbericht/reopen` | Transition SUBMITTED → DRAFT for edits. Does not bump `version`. 409 if already DRAFT. Returns the DRAFT Fahrbericht |
| `POST` | `/tours/{tour_id}/fahrbericht/reapply-side-effects` | Retry spec 011 + spec 013 side effects for the current `version` |
| `DELETE` | `/tours/{tour_id}/fahrbericht` | Delete a DRAFT. 409 if SUBMITTED (re-open + delete is not supported — once submitted, there is always an audit record) |

The GET response includes a `computed` block carrying the computed totals so the client doesn't have to re-fetch the catalog just to render a summary.

## UI

### Route

`/admin/tours/{tour_id}/fahrbericht` — full-page form with tab nav. Back link returns to `/admin/tours/{tour_id}`.

When the Tour detail page's "Fahrbericht" tab is opened:
- If a Fahrbericht exists → navigates to this page.
- If none exists → shows a button "Bericht starten" which `POST`s a blank DRAFT and then navigates.

### Page structure

```
┌───────────────────────────────────────┐
│ PageHeader: {Tour name} – Fahrbericht │
│ ← Zurück zur Tour                     │
├───────────────────────────────────────┤
│ Tab nav: Fahrt · Kiosk · Crew · Schiff · Abschluss │
├───────────────────────────────────────┤
│                                       │
│  [ active tab content ]               │
│                                       │
├───────────────────────────────────────┤
│ Sticky bottom bar:                    │
│ Kiosk Soll   Crew Kosten   Kasse (Ist)│
└───────────────────────────────────────┘
```

The sticky total bar mirrors the HTML `#totalbar` block. Values update live as the user edits tallies or cash.

### Tab 1 — Fahrt

Fields:
- Veranstaltungsname (text; defaults from Tour.name, editable — writes back to Tour via debounced PATCH)
- Datum (date; defaults from Tour.date, editable — writes back to Tour)
- Fahrdauer in Stunden (step 0.5)
- Anzahl Gäste
- Charterer / Veranstalter (text)
- Umlage Boarding (€)
- Umlage Bar (€)

Crew subsection (reads + writes to Tour — editing here edits the Tour record):
- Funker*in (text)
- Skipper (text)
- Weitere Crew (list editor, as in spec 010's Tour detail)

"Weiter → Kiosk" button at bottom (mobile convenience), matching the HTML's flow.

### Tab 2 — Kiosk

Infobox at top: "🛒 Selbstbedienungs-Kiosk: Trag hier ein, wie viele Einheiten Gäste aus dem Kiosk entnommen haben. Die Summe ist der Soll-Betrag im Kassenbuch."

Counter rows grouped by category:
- Each row uses the shared `CounterRow` component from spec 011 (T7.3) in `emphasis="kiosk"` mode.
- The row shows name, unit, optional note, `KB € x.xx` on the right, EK as a sub-hint. `+` / `−` buttons on the right edge, current quantity in the middle.
- Subtotal appears once qty > 0 (muted green text, right-aligned under the row).

Live section total: "Kiosk Soll gesamt: € ..." at the top of the list.

Only `active=true` bar items are rendered. Items that were used in a DRAFT but later deactivated stay visible **with a warning badge** until the user explicitly zeros them.

### Tab 3 — Crew

Same layout as Kiosk but:
- Infobox: "🍹 Crew-Verköstigung: Was Bar-Crew und Crew selbst konsumiert haben. Wird als Betriebsausgabe (Wareneinsatz) gebucht."
- Counter rows use `emphasis="crew"` — the price shown is EK (red) with KB as sub-hint (mirroring the HTML).
- Live section total: "Wareneinsatz Crew gesamt: € ..."

### Tab 4 — Schiff

Pre-filled from the current `ShipState` (spec 011) on first open of the DRAFT — the crew only adjusts what changed.

Sections:
- **Kraftstoff**: Tank 1 (%), Tank 2 (%), Volle Kanister an Bord, Volle Kanister Garage
- **Technik & Sanitär**: Wassertank (date), CO₂ (enum select), Batterie (%), Klo 1 (enum), Klo 2 (enum), Persennig (enum)
- **Anmerkungen**: textarea "Schäden / Besonderes / Fehlendes" → on save, individual lines (split on newline) are appended to `new_notes`
- **Noch zu erledigende Aufgaben**: textarea → split on newline, each becomes an entry in `new_todos`

Uses the same tile/grid pattern as spec 011's Ship dashboard (visually consistent).

### Tab 5 — Abschluss

Sections in order (mirroring the HTML):

1. **Kasse**
   - Bargeld im Umschlag (€)
   - Übergeben an (text)

2. **Ausgaben während Fahrt**
   - Dynamic list of `{description, amount}` rows with a trailing `×` remove button
   - "+ Ausgabe hinzufügen" button adds a row

3. **Zusammenfassung** (read-only computed block)
   - Kiosk-Einnahmen card: one line per consumed kiosk item, totals, umlage lines, `Soll im Umschlag`
   - Crew-Verköstigung card: items + `Wareneinsatz Crew`
   - Ausgaben card (only if any): per-line + total
   - Kassenabgleich card: `Soll`, `Ist`, `Differenz` with badge (✅ passt / ⬆️ Überschuss / ⚠️ Fehlbetrag)

4. **Buchungstext für Leasy / NetXp**
   - Monospace pre-block (dark background, green text — match HTML styling)
   - Contains the full booking text generated client-side from the data; button "Text kopieren" uses the existing toast for feedback
   - Format matches the HTML template at `renderBuchText()` lines 508–550

5. **Submit**
   - Large primary button. Label: "Fahrbericht einreichen" on the first submit (`version=0`); "Aktualisierung einreichen" on any re-submit (`version ≥ 1`)
   - Tap → opens `SubmitConfirmationSheet` (`ActionSheet`) with a summary, warnings (cash diff > 5€, any negative-stock forecast, any bar items referenced that are now inactive), and — on re-submits — a **diff view** showing what changed vs. `applied_*_tally` and which notes/todos will be appended or removed
   - Final button: "Endgültig einreichen" or "Aktualisierung bestätigen"
   - On confirm: calls the submit endpoint. On success: replaces the page with a read-only summary. The summary includes a "Bearbeiten" button that calls `reopen` and returns to editing. Also surfaces a "Bericht ansehen" link routing to spec 013's report detail

### Autosave behaviour

- Debounced 1500ms after the last meaningful change. Saved on blur immediately.
- Indicator at the top of the page (subtle): "Gespeichert vor N Sek." / "Ungespeicherte Änderungen" / "Speichern fehlgeschlagen — erneut versuchen".
- On save conflict (another session wrote newer data): show a toast "Ein anderer Crew-Member hat gerade gespeichert. Neueste Version wird geladen." and refetch.

### Counter UX

Visual cue: when a counter goes non-zero, the quantity text colour shifts to teal (spec 008 brand accent) and the subtotal appears. Matches the HTML's `.nonzero` class.

Tap-and-hold on `+` / `−` enables quick repeat (50ms interval after 400ms hold) — common on mobile for high tallies (HTML doesn't do this; it's a small UX upgrade).

## Integration

- **Spec 010 (Tour)**: Fahrbericht lives under `pk = TOUR#{id}`. Submission calls `tour_service.transition_to_completed`. Fahrt-tab edits to name/date/crew write back to the Tour via debounced PATCH.
- **Spec 011 (Bar, Ship)**: Consumption and ship-status snapshot applied post-commit as described in Lifecycle. Bar catalog fetched once per form load (GET `/bar-items?active=true`) and cached in the component.
- **Spec 013 (Report)**: Submission calls `report_service.create_report(tour_id)`. The `report_id` returned is stored on the Fahrbericht and used for the "Bericht ansehen" link.

## Booking text template

Rendered client-side for instant preview. Server-side duplicate for spec 013's email body (single source in `backend/app/services/booking_text.py` to keep formats in sync).

```
KASSENBUCH-EINGANG:
Datum: {date}
Veranstaltung: {name} ({guest_count} Gäste)
Funker*in: {funker}

EINNAHMEN (8400 / Erlöse Kiosk):
  {bar_item.name} × {qty} = € {qty * kb}
  ...

SUMME EINNAHMEN: € {kiosk_total}
Umlage Boarding: € {boarding_fee}
Umlage Bar: € {bar_surcharge}
─────────────────────────────────
SOLL Umschlag: € {soll}
IST Umschlag:  € {cash_amount}
Differenz:     € {cash_diff}

AUSGABEN (4220 / Wareneinsatz Crew):
  {bar_item.name} × {qty} = € {qty * ek}
  ...
Crew-Wareneinsatz: € {crew_cost}
Sonstige Ausgaben Fahrt: € {expenses_total}
```

## Testing

- `fahrbericht_service` unit tests: DRAFT upsert, status transitions, submission pipeline with mocked bar/ship/report services, idempotent re-submit prevention.
- Contract tests for each route.
- Frontend component tests for the counter row, sticky total bar recompute, and booking-text renderer (given a fixture tally, produce expected text).
- End-to-end test at least once manually (per project convention for UI changes): create tour → fill tally on mobile viewport → submit → check that bar stock decreased and ship state updated.

## Backward compatibility

- Purely additive. No impact on Events or Registrations.
- Spec 010 deletion policy already accounts for an existing Fahrbericht.

## Offene Fragen

1. **Who can reopen a SUBMITTED Fahrbericht?** MVP: any admin who can edit Events. Finer-grained ACL (only Funker, only OWNER) is a follow-up if abuse appears.
2. **Multi-user concurrency on a reopened DRAFT**: last-write-wins for MVP. The `version` field already exists for audit; we can co-opt it as an optimistic-lock token (`If-Match` header) in a follow-up if collisions become painful.
3. **Mobile autosave while offline**: MVP assumes connectivity. Offline queueing would require a Service Worker cache — possible given spec 009 set up PWA, but complex. Defer.
4. **Bar item deactivated mid-DRAFT**: Fahrbericht keeps the tally but surfaces a warning at submit. Alternative: silently drop the entry. Recommendation: warning — the crew may have manually restocked and re-sold.
5. **Booking text customization**: SKR04 account numbers (8400, 4220) are hardcoded to match the HTML. If the accountant needs to change them, promote to a backend setting or env var.
6. **Tap-and-hold repeat on counters**: nice-to-have, not essential for MVP. Ship if the component makes it simple; defer if complicated.

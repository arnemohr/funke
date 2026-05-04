# 018 — Modify Single Registrations (Admin)

**Status:** recommendation, pre-implementation
**Author:** Arne
**Date:** 2026-04-29

## Context

Admins manage registrations from `RegistrationTable.vue` on the event detail page. Today the per-row actions are limited: toggle promoted, promote a waitlisted reg, delete the entire registration. There is no way to view a single registration in detail or to surgically edit it — neither the registrant's metadata (typo'd phone number, an allergy note) nor individual guests in a group (rename one, drop one).

The backend has partial primitives already: `PUT /events/{eid}/registrations/{rid}/group-members` (admin endpoint that edits names but not size) and `confirm_with_names` (public endpoint that shrinks `group_size` when the registrant confirms with fewer names). Neither covers the admin "I need to fix this one reg right now" job. Today's workaround — delete the registration and ask the guest to re-register — is hostile to both the admin and the guest.

This spec adds a single-registration detail page accessible from the table. It folds the existing per-row actions into the page and adds in-place editing of registrant fields and group members, including guest deletion with automatic group-size reduction.

## TL;DR recommendation

1. **New full-page route** at `/admin/events/:eventId/registrations/:registrationId`. Same convention as the rest of the admin app (lottery, fahrbericht, event detail are all pages). Deep-linkable.
2. **Entry point** is the registrant name in the existing table — it becomes a `<router-link>`. No new column, no new menu item.
3. **Editable fields:** registrant `name`, `phone`, `notes`; per-guest names; per-guest delete (shrinks `group_size`). `email` is read-only — it is the identity / token target.
4. **Replace** the bespoke `…/group-members` admin endpoint with one general `PUT /events/:eid/registrations/:rid` taking a partial update.
5. **Capacity is not auto-reshuffled.** Deleting a guest shrinks `group_size`; the admin uses the existing "Nachrücken" affordance on a waitlisted reg if they want to fill the freed seat. This keeps the UI honest and avoids two paths writing to the waitlist.
6. **Frozen states** (`CANCELLED`, `CHECKED_IN`, and `COMPLETED` events) render the page read-only with an explanatory banner. Admin can still purge a `CANCELLED` reg.

## Architecture

**Route**

`/admin/events/:eventId/registrations/:registrationId` — added to the Vue router config alongside the existing event-scoped admin routes.

**Page component**

`frontend/src/pages/admin/RegistrationDetailPage.vue`. Single-column layout, three sections (`Anmeldedaten`, `Gäste auf der Bordliste`, `Aktionen`). Mirrors `EventDetailPage` styling — Pico defaults, no cards, generous vertical spacing.

**Entry point — `RegistrationTable.vue`**

The first cell (`<td data-label="Name">`) wraps the registrant name in a `<router-link>` to the detail page. Subtle hover affordance (underline-on-hover); same visual weight as today. No other change to the table — actions, filters, mobile cards stay as they are.

**Back navigation**

Header has "← Zurück zur Anmeldeliste". Uses `router.back()` when navigation history is intra-app (preserves table scroll/filter state); falls back to a hard link to the event detail page when the page was opened from a pasted URL or fresh tab.

**Loading**

`GET /events/:eid/registrations/:rid` (new admin endpoint — see API section). Suspense fallback uses the same `aria-busy="true"` shell the table uses.

## Page layout

**Header**

- Muted line: event name + start date (e.g., "Schaluppentour 12.07.2026, 18:00").
- Page title: registrant's `name`.
- Status badge below the title (the same `.status-badge` class the table uses).

**Section A — `Anmeldedaten`**

| Field | Treatment |
|---|---|
| `name` (registrant) | Editable text input |
| `email` | Read-only with `mailto:` link |
| `phone` | Editable, empty string clears |
| `notes` | Editable textarea, max 500 chars |
| `Angemeldet am` | Read-only timestamp |
| `Bestätigt am` | Read-only timestamp, hidden when null |
| Promoted toggle | Same control as in the table; rendered here when event status is `OPEN` / `REGISTRATION_CLOSED` |

Save button at the bottom of the section: `Änderungen speichern` (primary, disabled when nothing dirty). Sibling `Verwerfen` button when dirty.

**Section B — `Gäste auf der Bordliste`**

Header line: `X von Y Plätzen genutzt` — e.g., "3 von 4 Plätzen genutzt" — to make the `group_members` ↔ `group_size` relationship visible.

One row per slot:

- **Named slot** — text input pre-filled with the name. Trash icon at the right end.
- **Placeholder slot** (pre-confirmation, `group_members` is null or shorter than `group_size`) — rendered as muted "Gast 2" / "Gast 3" / …, **non-editable**, with a trash icon. Admin can shrink the group by deleting placeholders but cannot invent names — those are filled by the registrant via the public confirm flow. A muted helper line at the bottom of the section explains: "Gastnamen werden von der Person eingetragen, die sich angemeldet hat."
- The **registrant's own slot** is the input bound to Section A's `name` field — renaming there updates the row live. Trash icon hidden (the registrant cannot be removed without deleting the whole reg).

Save button at the bottom of the section: `Änderungen speichern`. When at least one slot is staged for deletion, label changes to `N Gäste entfernen und speichern` so the destructive part is visible before commit. Sibling `Verwerfen` button when dirty.

Inline delete affordance: pressing the trash icon collapses the row to "Gast entfernen? `[Entfernen]` `[Abbrechen]`" — no full modal for a single-name delete. Confirm strikes through the row and updates the "X von Y" counter immediately to preview the new size; the change commits on Save.

Validation:

- Empty name on save → inline "Name darf nicht leer sein" under the offending input.
- All names trimmed before submission.
- Floor on `group_size` is 1; the registrant's row is undeletable, which makes this implicit.

**Section C — `Aktionen`**

- `Nachrücken` / `Direkt bestätigen` — only when `status == WAITLISTED` and event is `CONFIRMED` (today's logic).
- `Anmeldung löschen` — destructive button at the bottom. Reuses today's confirmation dialog from the table.

**Frozen states**

When the page is read-only (`CANCELLED`, `CHECKED_IN`, or event `COMPLETED`), all editable inputs render as plain text and all save buttons are hidden. A banner at the top of the page explains why (copy in the Status gate / copy section). The `Anmeldung löschen` button stays available for `CANCELLED` only, so admins can purge cancelled regs.

## Edit flows

**Save model.** Page-level "save per section" pattern — Section A and Section B each have their own `Änderungen speichern` button, each disabled until that section is dirty. No autosave; admins want a deliberate commit. Toast on success ("Änderungen gespeichert"); inline error message above the section on failure.

**Rename guest.** Type into the input → Section B becomes dirty → Save sends the full `group_members` list (with `group_size` unchanged).

**Delete guest.** Trash → inline confirmation → row staged for removal. On Save, `group_members` and `group_size` are sent together: `group_size` becomes `len(remaining group_members)`. One DynamoDB write.

**Cancel pending changes.** `Verwerfen` resets the section's local state to the last loaded server state.

**Pre-confirmation placeholder edits.**

Renaming a placeholder is **not allowed** — names belong to the registrant's confirm flow and must not be invented by the admin. The placeholder rows accept only the trash action.

Deleting a placeholder shrinks `group_size` by 1. `group_members` stays untouched (still null until the registrant confirms with names) — the API receives `group_size` only, with no `group_members` payload.

Once the registrant has confirmed and `group_members` is populated, every slot in Section B is a named slot and full rename + delete works as described above. The asymmetry is honest: the "names" the admin sees are always names someone confirmed.

**Concurrency.** If the registrant confirms via the public link while the admin is mid-edit, the API returns 409 Conflict with the current `RegistrationResponse`. The page replaces its form state with the fresh data and shows a banner: "Die Anmeldung wurde zwischenzeitlich aktualisiert. Aktuelle Daten geladen — bitte erneut prüfen." Admin re-reviews and saves again. No automatic merge.

## API surface

Two new admin endpoints. The existing `PUT /events/:eid/registrations/:rid/group-members` is replaced (per project policy, no compatibility shim — the only callers are the admin UI we're rewriting).

### `GET /events/:eid/registrations/:rid` (new)

- Auth: `OWNER` / `ADMIN`.
- Returns `RegistrationResponse`.
- 404 if not in this event / org.

### `PUT /events/:eid/registrations/:rid` (new — replaces `…/group-members`)

- Auth: `OWNER` / `ADMIN`.
- Body — partial update, all fields optional:
  - `name: str | None` — registrant name, 1–200 chars after strip.
  - `phone: str | None` — `""` clears.
  - `notes: str | None` — `""` clears, max 500 chars.
  - `group_size: int | None` — must be ≤ current `group_size`. **Cannot grow.** Floor 1.
  - `group_members: list[str] | None` — entries trimmed; all entries must be non-empty (1–200 chars). `len(group_members)` must equal the post-update `group_size` (so a rename without a delete sends a list of the same length as today). To leave names unchanged while shrinking, omit the field and send `group_size` only.
- Server rules:
  - 400 if registration status ∈ {`CANCELLED`, `CHECKED_IN`}.
  - 400 if event status is `COMPLETED`.
  - If both `group_size` and `group_members` provided: `len(group_members) == group_size`.
  - If only `group_members` provided: `len(group_members) ≤ current group_size`, and `group_size` is set to `len(group_members)` (this is how a rename-with-delete is committed). Growing the group through `group_members` is rejected for the same reason `group_size` cannot grow directly.
  - If only `group_size` provided and `group_members` is currently set: the existing list is truncated to `group_size` from the right (last entries dropped). This case is used to delete placeholders pre-confirmation when there is no list — but if a list exists, truncation is the only sensible behaviour and admins are not expected to use it (the UI sends both fields together when a list exists).
  - All field updates land in a single DynamoDB `update_item`.
  - Optimistic concurrency: `ConditionExpression` on the registration's current `responded_at` (when present) and `status` — gives us a stable token without adding a `version` column. On `ConditionCheckFailed`, return 409 with the current `RegistrationResponse`.
- Returns `RegistrationResponse`.
- Logs `registration.update` via `log_admin_action` with the set of changed field names (no PII in extras — names go through normal logging only).

### Service-layer changes

In `app/services/registration_service.py`:

- Remove `admin_update_group_members` (only the admin UI calls it).
- Add `admin_update_registration(event_id, registration_id, patch)` returning `(Registration, error)`. v1 does **not** increment `freed_spots` or call `_promote_from_waitlist` — capacity changes are purely local to the registration. See "Capacity behaviour" below.
- Keep `confirm_with_names` untouched — it owns a separate state transition (`CONFIRMED → PARTICIPATING`) and is the public confirm flow's contract.

### Frontend `services/api.js`

- `getAdminRegistration(eventId, registrationId)` — new.
- `updateAdminRegistration(eventId, registrationId, patch)` — new.
- Remove the existing `updateAdminGroupMembers` helper (replaced by the patch endpoint).

## Capacity behaviour

Deleting a guest shrinks `group_size`. The admin **does not** trigger waitlist promotion automatically.

Rationale: the existing public-confirm path's `freed_spots` increment is consumed by a daily batch job — fine for guests confirming days ahead, wrong for "Klaus called five minutes ago to drop his +1." Auto-promoting in real time also creates a second write path into the waitlist, alongside the existing `_promote_from_waitlist` used by full-registration delete. Two paths to the same destination is exactly the kind of seam that breeds bugs (e.g., race against the daily job, double-promotions).

If the admin wants the freed seat filled, they open a waitlisted reg and use the existing `Nachrücken` action. That path is well-trodden, idempotent, and observable.

When demand for "auto-promote on group shrink" surfaces (e.g., from same-day attrition patterns), it's a single follow-up: call `_promote_from_waitlist` from the patch endpoint when `group_size` decreases and event status is `CONFIRMED`. Out of scope for v1.

## Status gate

| Status | Edit fields | Delete guest | Delete registration |
|---|---|---|---|
| `REGISTERED` | ✓ | ✓ | ✓ |
| `CONFIRMED` | ✓ | ✓ | ✓ |
| `PARTICIPATING` | ✓ | ✓ | ✓ |
| `WAITLISTED` | ✓ | ✓ | ✓ |
| `CANCELLED` | — | — | ✓ (purge) |
| `CHECKED_IN` | — | — | — |

Plus: when event status is `COMPLETED`, the page is fully read-only regardless of registration status.

UI and API enforce the same gate (defense in depth). The API is the source of truth.

## Edge cases

| Case | Handling |
|---|---|
| Admin tries to grow `group_size` | API rejects with 400. UI doesn't expose the affordance — no "+ Gast hinzufügen" button. |
| Last guest deleted (would set `group_size` to 0) | Implicit floor: registrant slot has no trash icon. API rejects 400 if a client somehow sends it. |
| Phone cleared on a reg with SMS reminders queued | Existing reminder logic no-ops when `phone is None`. No extra wiring. |
| Concurrent edit (registrant confirms public link mid-admin-edit) | 409 → reload form + banner. No merge. |
| Deep link to a deleted registration | 404 → "Diese Anmeldung existiert nicht mehr." with a link back to the event. |
| Event is `COMPLETED` | Read-only banner ("Die Veranstaltung ist abgeschlossen…"); only purge available for `CANCELLED` regs. |
| Registrant slot rename | Ordinary `name` field update; the registrant's own row in Section B and the `name` input in Section A are bound to the same field — editing one updates the other live. |

## Copy (German)

- Page title: registrant's `name`.
- Section headings: `Anmeldedaten`, `Gäste auf der Bordliste`, `Aktionen`.
- Save: `Änderungen speichern`. Discard: `Verwerfen`.
- Save with pending guest deletes: `1 Gast entfernen und speichern` / `N Gäste entfernen und speichern`.
- Inline guest delete confirm: `Gast entfernen?` `[Entfernen]` `[Abbrechen]`.
- Empty name validation: `Name darf nicht leer sein.`
- Frozen banners:
  - `CANCELLED`: "Diese Anmeldung wurde storniert. Änderungen sind nicht möglich."
  - `CHECKED_IN`: "Diese Person ist bereits eingecheckt. Änderungen sind nicht mehr möglich."
  - `COMPLETED` event: "Die Veranstaltung ist abgeschlossen. Änderungen sind nicht mehr möglich."
- Concurrency banner: "Die Anmeldung wurde zwischenzeitlich aktualisiert. Aktuelle Daten geladen — bitte erneut prüfen."
- Toast on save success: "Änderungen gespeichert."
- 404 on deep link: "Diese Anmeldung existiert nicht mehr."

## Scope of v1

1. New admin GET endpoint and replacement PUT endpoint (and service method).
2. New `RegistrationDetailPage.vue` with three sections, two save buttons, frozen-state read-only mode.
3. Make the registrant name in `RegistrationTable.vue` a `<router-link>` to the detail page; no other table changes.
4. Move the per-row Promoted toggle and Waitlist actions into the detail page's Section C in addition to keeping them in the table (parity for now — a follow-up could remove the table copies if the new page sticks).
5. Replace the existing admin `updateAdminGroupMembers` API helper with the new patch helper.

**Out of scope (deferred, not "no")**

- Adding new guests / growing `group_size`. Hard rule: the group can only shrink.
- Editing `email`. Identity boundary — confirmation tokens, dedup keys, lottery membership.
- Manual status overrides (force-cancel, force-confirm).
- Bulk edit across multiple regs.
- Audit log surfaced in the UI (`log_admin_action` continues to write entries).
- Notifying the registrant on admin edits.
- Auto-promote from the waitlist when an admin shrinks a group (see "Capacity behaviour").
- A `version` / `updated_at` column on `Registration` for proper optimistic concurrency. Using `responded_at` + `status` as the conflict token is enough for v1.

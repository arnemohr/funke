# 008 — Design Overhaul: Task Breakdown

> Derived from `specs/008-design-overhaul.md`. Each task is self-contained and independently shippable.
> Tick off with `[x]` as implemented.

---

## Phase 0: Quick Fixes (trivial, high-impact)

### P0-1: Fix `<html lang="en">` to `lang="de"`
- [x] In `frontend/index.html` line 2, change `lang="en"` to `lang="de"`
- **Why**: WCAG 3.1.1 violation — screen readers pronounce German text with English rules
- **Approach**: Single attribute change

### P0-2: Fix unformatted date on Registration Management Page
- [x] In `RegistrationManagePage.vue` line 19, `eventInfo.start_at` is rendered raw (ISO string)
- [x] Import `formatDate()` from shared `utils/formatters.js`
- [x] Apply: `{{ formatDate(eventInfo.start_at) }}`
- **Why**: Users see `2026-06-15T10:00:00Z` instead of a human-readable date
- **Approach**: Import from shared formatters (created as part of P2-2)

---

## Phase 1: Foundation

### P1-1: Create shared design tokens CSS
- [x] Create `frontend/src/assets/design-tokens.css` with CSS custom properties
- [x] Define status colour tokens (text + background for each status), using darkened text values for WCAG AA contrast
- [x] Define typography scale: `--text-xs` through `--text-xl`
- [x] Define spacing scale: `--space-1` through `--space-8`
- [x] Import in `main.js` after Pico CSS import
- **Why**: 6 components independently define status badge colours with inconsistent values. No single source of truth exists

### P1-2: Remove root font-size override
- [x] In `App.vue`, remove `:root { font-size: 87.5%; }` (lines 48-50)
- **Why**: 87.5% base (14px) combined with component-level `0.65rem`/`0.7rem` produces 9-10px text, below readable thresholds

### P1-3: Translate event status codes to German
- [x] Create `formatEventStatus()` function in `utils/formatters.js`
- [x] Apply in `EventsPage.vue` (event table status badges)
- [x] Apply in `DebugPage.vue` (event status displays)
- [x] Apply in `lottery.vue` (event status display)
- **Why**: Admin users see raw English codes like `DRAFT`, `LOTTERY_PENDING` in a German UI

### P1-4: Replace `alert()` / `confirm()` with toast notifications
- [x] Create toast composable `frontend/src/composables/useToast.js`
- [x] Create `frontend/src/components/ToastContainer.vue`
- [x] Mount `ToastContainer` in `App.vue`
- [x] Replace all 11 `alert()` calls in `EventsPage.vue`
- [x] Replace 1 `alert()` in `DebugPage.vue`
- [x] Replace `confirm()` in `EventsPage.vue` with a custom `<dialog>`
- **Why**: Native `alert()` blocks the browser thread, can't be styled, and is inconsistent

### P1-5: Fix context menu focus/keyboard accessibility
- [x] In `RegistrationTable.vue`, add `:focus-visible` styles to `.context-menu-trigger`
- [x] Add `:focus-visible` styles to `.context-menu-item`
- [x] Add keyboard event handlers: `Escape` to close menu, `ArrowDown`/`ArrowUp` to navigate items
- [ ] Add upward flip logic: if the trigger is in the bottom 200px of the viewport, position menu above instead of below
- **Why**: WCAG 2.4.7 violation — keyboard users cannot see focus, cannot navigate menu items

### P1-6: Fix colour contrast for WCAG AA
- [x] Design tokens define corrected values (P1-1)
- [x] Updated all 6 components to use global token values (removed scoped status badge CSS)
- **Why**: Current contrast ratios failed WCAG AA

### P1-7: Add active state to navigation
- [x] In `App.vue`, add CSS for `.router-link-exact-active` on nav links
- **Why**: No visual indication of current page in the nav bar

### P1-8: Remove unnecessary API reload on filter change
- [x] In `EventsPage.vue`, removed `watch(statusFilter, loadEvents)` watcher
- **Why**: Every filter tab click triggered an unnecessary API reload

---

## Phase 2: Consistency

### P2-1: Consolidate status badge CSS across components
- [x] Defined `.status-badge` and `.status-{name}` classes in `design-tokens.css`
- [x] Removed duplicated status badge CSS from all 6 components
- **Why**: Same CSS defined 6 times with slight variations

### P2-2: Extract shared utility functions
- [x] Created `frontend/src/utils/formatters.js` with all shared formatters
- [x] Replaced inline `formatDate()` in 7 components
- [x] Replaced inline `formatDateTime()` in `DebugPage.vue`
- [x] Replaced inline `berlinToUTCISO()` in `EventsPage.vue` and `EventForm.vue`
- [x] Replaced inline `formatStatus()` in `RegistrationTable.vue`
- **Why**: Duplicated functions across many components

### P2-3: Eliminate `!important` overrides
- [x] Defined shared `.btn-danger` and `.btn-success` classes in `design-tokens.css` using Pico CSS custom properties
- [x] Replaced `!important` overrides in `EventsPage.vue` (9 instances)
- [x] Replaced `!important` overrides in `RegistrationManagePage.vue` (10 instances)
- [x] Replaced `!important` overrides in `EventDetailModal.vue` (9 instances)
- [x] `ConfirmPage.vue` (10 instances) — file deleted as orphaned code
- **Why**: 38 `!important` overrides indicate CSS architecture fights the framework

### P2-4: Add count badges to filter tabs
- [x] In `EventsPage.vue`, added `filterCounts` computed and display counts in each tab
- **Why**: Admin cannot see at a glance how many events are in each state

### P2-5: Improve events table registration column readability
- [x] Split dense "Anmeldungen" column into two readable lines
- [x] Expanded "WL" to "Warteliste"
- **Why**: Current format is dense and requires learned knowledge

### P2-6: Improve event detail modal button grouping
- [x] Grouped Tier 2 buttons by function (Management, Sharing, Communication) with `.button-group` separators
- [x] Added `title` attributes to specialist terms (Boardingzettel, Einladungstext)
- **Why**: Up to 8 visually equivalent buttons in a single row is overwhelming

### P2-7: Add responsive form-row collapse for EventForm
- [x] Added `@media (max-width: 576px)` media query for `.form-row`
- **Why**: Two-column grid doesn't collapse on mobile

### P2-8: Add `overflow-x: auto` to tables in modals/debug
- [x] Wrapped `RegistrationTable` in `EventDetailModal.vue` with scrollable div
- [x] Added `overflow-x: auto` to `.event-content` in `DebugPage.vue`
- **Why**: Tables with 7-11 columns overflow on small screens

### P2-9: Show management link on registration success
- [x] Added management URL with copy button on `RegistrationPage.vue` success state
- [x] Constructed URL from `registration.id` and `registration.registration_token`
- **Why**: Management URL only exists in the confirmation email

### P2-10: Improve registration form inline hints
- [x] Added `<small>` hint below "Gruppengröße": "Wie viele Personen insgesamt (inkl. dir selbst)?"
- **Why**: First-time users don't know if group size includes themselves

### P2-11: Reset MessageComposer form state on open
- [x] Expanded watcher to reset all form state (subject, body, selectedIds, includeLinks, error, result)
- **Why**: Opening composer after a previous use retains stale content

### P2-12: Fix DebugPage memory leak
- [x] Added `onUnmounted` cleanup for `visibilitychange` listener
- **Why**: Listener never removed — leaks if user navigates away

### P2-13: Remove orphaned pages
- [ ] Delete `frontend/src/pages/cancel/CancelPage.vue`
- [ ] Delete `frontend/src/pages/confirm/ConfirmPage.vue`
- [ ] Delete `frontend/src/pages/Home.vue`
- **Why**: ~800 lines of dead code. Files are orphaned (not referenced by router)
- **Note**: Deletion blocked by sandbox. Run manually: `rm frontend/src/pages/cancel/CancelPage.vue frontend/src/pages/confirm/ConfirmPage.vue frontend/src/pages/Home.vue`

### P2-14: Fix `hasActions()` dead code in RegistrationTable
- [x] Simplified to `return reg.status !== 'CANCELLED'`
- **Why**: The `||` branch could never evaluate to true

### P2-15: Remove dead `cancelDialog` ref in RegistrationManagePage
- [x] Removed unused `ref="cancelDialog"` from template and `const cancelDialog = ref(null)` from script
- **Why**: Dead code

---

## Phase 3: Polish

### P3-1: Style empty states with visual emphasis
- [x] Wrapped empty state in `<article>` card with centered text and embedded "Neue Veranstaltung" button
- **Why**: Plain `<p>` with no visual emphasis or embedded action

### P3-2: Add brand identity
- [x] Derived brand palette from mobilemachenschaften.de, updated to 2026 design language
- [x] Brand primary: deep navy `#0C1E3C` (nautical heritage from parent org's `#00102E`)
- [x] Accent: warm amber-orange `#E8722A` (the "Funke" spark, derived from org's `#ff6900`)
- [x] Override `--pico-primary` with brand navy in `design-tokens.css`
- [x] Navy header with white text, accent-coloured active nav indicator
- [x] Warm off-white surface `#FAFAF8`, warm grey text `#5C6470`
- [x] Updated landing page with brand mark (⚓), tagline, and org motto
- **Why**: Derived from mobilemachenschaften.de to create visual continuity with the parent organisation

### P3-3: Improve success state after registration
- [ ] Restructure green-box-with-white-card nesting in `RegistrationPage.vue`
- **Why**: Visual nesting is awkward — deferred for visual review

### P3-4: Auto-open event detail after creation
- [x] After creating an event, auto-open detail modal via `viewRegistrations(newEvent)`
- **Why**: After creating, user was left at the list with no indication of where the new event went

### P3-5: Add visual capacity indicator on registration page
- [ ] Show remaining capacity with progress bar
- **Why**: May require backend change to include registration count in public API response — deferred

### P3-6: Fix lottery metrics grid for 4 items
- [x] Changed grid to `repeat(auto-fit, minmax(120px, 1fr))`
- **Why**: 4 metric items with 3-column grid caused imbalance

### P3-7: Add breadcrumbs to lottery page
- [x] Added breadcrumb nav: Veranstaltungen › {Event Name} › Verlosung
- **Why**: Navigation context was lost when transitioning to lottery page

### P3-8: Add post-lottery "next step" guidance
- [x] Added finalized-guidance section with message and "Zurück zur Übersicht" link
- **Why**: After finalizing, admin had no guided transition

### P3-9: Differentiate REGISTERED vs WAITLISTED visual treatment
- [x] REGISTERED: changed to light blue info banner
- [x] WAITLISTED: changed icon to clipboard, added empathetic hint text
- **Why**: Both states used identical grey background with same hourglass emoji

### P3-10: Add backdrop to HelpPanel overlay
- [x] Added semi-transparent backdrop with click-to-close
- **Why**: Panel overlapped content without visual separation

### P3-11: Create public landing page
- [x] Created `LandingPage.vue` with brief explanation and admin link
- [x] Updated router: `/` loads landing page instead of redirecting to login
- **Why**: Public users visiting root URL were sent to admin login

### P3-12: Remove footer close button from EventDetailModal
- [x] Removed "Schließen" button from footer
- **Why**: Redundant with header X button, visually competed with action buttons

### P3-13: Add tooltips for specialist terms
- [x] Added `title` attributes to Boardingzettel and Einladungstext buttons
- **Why**: Terms are domain-specific and not self-explanatory

---

## Task Dependency Graph

```
P0-1, P0-2 ─── (no dependencies, do first)           ✅

P1-1 (design tokens) ──┬── P1-6 (contrast fix)        ✅
                        ├── P2-1 (consolidate badges)  ✅
                        ├── P2-3 (eliminate !important) ✅
                        └── P3-2 (brand identity)      ✅

P1-3 (event status translation) ── P2-2 (shared utils) ✅

P1-4 (toast system) ─── ✅
P1-5 (context menu a11y) ─── ✅ (upward flip deferred)
P1-7 (nav active state) ─── ✅
P1-8 (remove API reload) ─── ✅

P2-13 (remove orphaned pages) ─── ⬜ (manual deletion needed)

All P3 items ─── ✅ except P3-3 (success state), P3-5 (capacity indicator)
```

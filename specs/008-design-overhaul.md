# 008 -- Design Overhaul: UI/UX Review & Visual Language Improvement

> **Scope**: Frontend-only. No behaviour changes, no backend modifications.
> **Goal**: Make the site self-explanatory, visually coherent, and more pleasant to use.
> **Review date**: 2026-04-02
> **Reviewed files**: All 18 Vue components, 6 JS modules, index.html

---

## 1. Executive Summary

Funke is a functional boat-event management tool that works well. The interface has grown organically across 7 spec iterations and accumulated visual inconsistencies, unclear information hierarchy, and missed opportunities for guiding users through tasks. This spec catalogues every issue found and proposes concrete, behaviour-preserving improvements.

**Key themes:**
- The public-facing pages (registration, management) lack warmth and brand personality for a boat party app
- The admin interface is dense and action-heavy with insufficient visual hierarchy
- Status information is presented inconsistently across screens (different colours for the same semantic status, raw English codes in some places, German labels in others)
- The visual language (colours, spacing, typography) is ad-hoc rather than systematic
- 38 `!important` overrides, 11 `alert()` calls, and 1 `confirm()` call indicate design-system friction and UX debt

---

## 2. Global Issues

### 2.1 No Design Tokens / Shared Visual Language

**Problem**: Colours are hardcoded hex values scattered across every component. The same semantic status uses different colours in different components, and status badge CSS is defined independently in 6 separate files.

**Verified inconsistencies (exact values from code):**

| Status | EventsPage.vue | RegistrationTable.vue | lottery.vue | DebugPage.vue |
|--------|---------------|----------------------|-------------|---------------|
| `status-open` | `#dcfce7`/`#16a34a` (green) | n/a | `#dbeafe`/`#2563eb` (blue) | `#dcfce7`/`#16a34a` (green) |
| `status-confirmed` | `#d1fae5`/`#065f46` (dark green) | `#fef3c7`/`#d97706` (amber) | `#fef3c7`/`#d97706` (amber) | `#fef3c7`/`#d97706` (amber) |
| `status-completed` | `#dbeafe`/`#2563eb` (blue) | n/a | n/a | `#dbeafe`/`#2563eb` (blue) |

The EventsPage uses `status-confirmed` as dark green (`#d1fae5`/`#065f46`) for event-level CONFIRMED status, while RegistrationTable, MessageComposer, and lottery.vue use amber (`#fef3c7`/`#d97706`) for registration-level CONFIRMED. This is a meaningful inconsistency -- at event level CONFIRMED means "lottery finalized, awaiting participant responses" (a positive state), while at registration level it means "awaiting confirmation from participant" (a pending state). The semantic difference is valid, but using the same CSS class name for different meanings is confusing for maintenance.

The `.error` class is also redefined in **8 separate components** with slight variations (some use `#dc3545`, others `#dc2626`; some have `1rem` padding, others `0.75rem`).

**Recommendation**: Create a `design-tokens.css` file with CSS custom properties:
- Status colours (one canonical palette, with distinct names for event-level vs registration-level if semantics differ)
- Semantic colours (success, warning, danger, info, neutral)
- Spacing scale (4px base: 4, 8, 12, 16, 24, 32, 48)
- Typography scale
- Border radius and shadow tokens

### 2.2 Raw Status Codes Shown to Admin Users

**Problem**: The events table (`EventsPage.vue` line 92), debug page (`DebugPage.vue` lines 61, 122), and lottery page (`lottery.vue` lines 16, 167) display raw English status codes (`DRAFT`, `OPEN`, `REGISTRATION_CLOSED`, `LOTTERY_PENDING`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, `BESTÄTIGT`) directly. The `RegistrationTable.vue` correctly uses `formatStatus()` to translate registration statuses to German (line 263-273), but no equivalent helper exists for event-level statuses.

The lottery page is inconsistent even with itself: it shows the raw `event.status` on line 16 but uses a hardcoded German label `BESTÄTIGT` on line 167 and `ABGESCHLOSSEN` / `PRÜFUNG AUSSTEHEND` on lines 132-133.

**Recommendation**: Add a `formatEventStatus()` helper and use it everywhere:
- `DRAFT` -> `Entwurf`
- `OPEN` -> `Offen`
- `REGISTRATION_CLOSED` -> `Anmeldung geschlossen`
- `LOTTERY_PENDING` -> `Verlosung ausstehend`
- `CONFIRMED` -> `Bestätigt`
- `COMPLETED` -> `Abgeschlossen`
- `CANCELLED` -> `Abgesagt`

Consider placing both `formatStatus()` and `formatEventStatus()` in a shared utility file rather than duplicating across components.

### 2.3 Root Font-Size Reduction

**Problem**: `App.vue` line 48-50 sets `:root { font-size: 87.5% }` (14px effective base). Combined with component-level reductions, text becomes very small:
- DebugPage base: `0.85rem` (line 282) = ~11.9px effective
- DebugPage table headers: `0.7rem` (line 491) = ~9.8px effective
- DebugPage status badges: `0.65rem` (line 577) = ~9.1px effective
- "Gesehen" badge in RegistrationTable: `0.65rem` (line 323) = ~9.1px effective
- MessageComposer status badges: `0.65rem` (line 275) = ~9.1px effective
- MessageLog type/status badges: `0.7rem` (lines 139, 149) = ~9.8px effective

WCAG SC 1.4.4 requires text to be resizable up to 200%. Starting from a reduced base makes this harder to achieve and hurts readability at default zoom on standard-density displays.

**Recommendation**: Remove the root font-size override. Let Pico CSS use its default 16px base. Adjust component-level sizing only where genuinely needed. The smallest text should not go below `0.75rem` (12px at 16px base).

### 2.4 `!important` Overrides

**Problem**: 38 instances of `!important` across 4 files:
- `EventsPage.vue`: 9 instances (cancel-confirm-btn, delete-btn, discard-btn)
- `RegistrationManagePage.vue`: 10 instances (confirm-btn, cancel-btn, cancel-confirm-btn)
- `EventDetailModal.vue`: 9 instances (cancel-btn, delete-btn)
- `ConfirmPage.vue`: 10 instances (confirm-yes, confirm-no)

All are used to override Pico CSS default button colours for danger/success actions. This is a fragile pattern indicating the colour system fights the framework.

**Recommendation**: Use Pico CSS custom properties (`--pico-primary`, `--pico-primary-hover`) scoped to specific selectors, or define shared utility classes (`.btn-danger`, `.btn-success`) once in a global stylesheet that leverages specificity rather than `!important`.

### 2.5 `alert()` and `confirm()` Usage

**Problem**: 11 `alert()` calls in `EventsPage.vue` and 1 in `DebugPage.vue`, plus 1 `confirm()` call in `EventsPage.vue` line 804. These are:
- **Jarring UX**: Native dialogs block the browser thread, cannot be styled, and feel out of place in a modern SPA
- **Inaccessible**: Screen readers may not announce them properly in all contexts
- **Inconsistent**: Some operations use custom dialogs (cancel event, delete event) while others use native `alert()`

Specific instances in `EventsPage.vue`:
- Success notifications: "Anmeldelink wurde kopiert!" (line 564), "Einladungstext wurde kopiert!" (line 597)
- Error notifications: lines 514, 525, 536, 685, 706, 742, 815
- Result notification: line 787
- Confirmation: `confirm()` for registration deletion (line 804)

**Recommendation**: Replace with an inline toast/notification system. A lightweight composable (`useToast()`) with auto-dismissing messages at the top or bottom of the viewport would handle all cases. The registration delete confirmation should use a custom dialog consistent with the cancel/delete event dialogs.

### 2.6 No Brand Identity

**Problem**: The header shows only the word "Funke" in bold (`App.vue` line 6). No logo, colour accent, or visual personality. For a boat party community tool named after "Verein fuer mobile Machenschaften e.V.", the interface feels like a generic admin template.

**Recommendation**:
- Add a simple brand mark (text mark with an accent colour or small icon)
- Introduce a brand/accent colour beyond Pico's default blue -- something that fits the boat/community theme (teal/ocean blue or warm orange)
- The header could carry a subtle background tint

### 2.7 `<html lang="en">` Mismatch

**Problem**: `index.html` line 2 sets `lang="en"` but the entire UI is in German. This affects screen reader pronunciation and browser spell-checking.

**Recommendation**: Change to `<html lang="de">`.

### 2.8 Duplicated Utility Functions

**Problem**: `formatDate()` is defined independently in 7 components with slight variations:
- `EventsPage.vue` (line 451): short month, includes time
- `RegistrationPage.vue` (line 200): long weekday + long month, includes time
- `RegistrationManagePage.vue`: no formatDate -- `eventInfo.start_at` is rendered raw (line 19)
- `EventDetailModal.vue` (line 223): short month, includes time
- `RegistrationTable.vue` (line 236): short month, includes time
- `lottery.vue` (line 230): short month, includes time
- `MessageLog.vue` (line 95): short month, includes time
- `DebugPage.vue` (line 162): date only, no time; plus separate `formatDateTime()` (line 174)

Similarly, `berlinToUTCISO()` is duplicated in both `EventsPage.vue` (line 459) and `EventForm.vue` (line 142) with identical logic.

**Recommendation**: Extract shared formatters into a `utils/formatters.js` module. This reduces duplication and ensures consistent date formatting across the app.

### 2.9 Missing `onUnmounted` Cleanup in DebugPage

**Problem**: `DebugPage.vue` adds a `visibilitychange` event listener on mount (line 275) but never removes it. This causes a memory leak if the user navigates away from the debug page. By contrast, `RegistrationTable.vue` correctly cleans up its click listener in `onUnmounted` (line 195).

**Recommendation**: Add `onUnmounted(() => document.removeEventListener('visibilitychange', handleVisibilityChange))`.

---

## 3. Public Pages Review

### 3.1 Registration Page (`/register/:token`)

**File**: `frontend/src/pages/registration/RegistrationPage.vue`

#### 3.1.1 Event Details Presentation

**Problem**: Event details are shown in a `<dl>` grid (line 34-46) which is functional but dry. The most important information (date, capacity, deadline) is presented with equal visual weight. There is no visual cue about whether spots are still available -- `event.capacity` is shown as a bare number.

**What works well**:
- `formatDate()` is properly called for both `start_at` and `registration_deadline` (lines 36, 43)
- Deadline passed state is highlighted with red + bold via `.deadline-passed` class (line 42, CSS line 330-333)
- The late signup notice is well-written and actionable (line 51)
- The form heading changes dynamically for late signups (line 56)

**Recommendation**:
- Use a card-style layout with subtle visual accents for each detail
- Show remaining capacity context: "80 Plaetze" is less useful than "12 von 80 Plaetzen vergeben" with a progress bar
- Highlight the deadline more prominently since it is the most time-sensitive information

#### 3.1.2 Form Layout

**Problem**: The form is a single-column stack of full-width fields. "Gruppengroesse" uses a dropdown for 1-10 which is good, but the label "Gruppengroesse *" (line 93) does not explain what it means. A first-time user may not know whether this includes themselves.

**What works well**:
- Proper `label`/`for` associations for accessibility
- Sensible placeholders (e.g., "deine@email.de")
- Disabled state during submission
- `aria-busy` on the submit button

**Recommendation**:
- Add an inline hint below "Gruppengroesse": e.g., "Wie viele Personen insgesamt (inkl. dir selbst)?"
- Consider grouping Name + Email on one row at wider viewports
- Add a visual divider between event details and the form

#### 3.1.3 Success State

**Problem**: The success state (line 128-153) centres text on a green background with a nested white card for registration details and an info-box for the email notice. The visual nesting (green box > white box) is slightly odd but functional.

**More significantly**: After registration success, the user's only guidance is "check your email" (line 147-151). There is **no way to return to or bookmark the management page** from this screen. The management URL is only in the confirmation email. If the email is delayed, filtered, or lost, the user has no way to manage their registration.

**Recommendation**:
- Display the management page link prominently after registration: "Speichere diesen Link, um deine Anmeldung spaeter zu verwalten:" with a copy button. This requires the API to return the `registration_id` and `registration_token` in the registration response (verify backend).
- Make the "check your email" notice more actionable with a call-to-action style

#### 3.1.4 HelpButton on Public Pages

**Problem**: The HelpButton appears on the registration page (line 22) and management page (line 21). While help is useful, a "?" button with no label might confuse public users who are not admins and may not expect in-app help on what should be a simple form.

**Recommendation**: Evaluate whether the help button is needed on public pages. If kept, add a text label "Hilfe" next to the "?" to make its purpose clearer for non-technical users. On admin pages the icon-only "?" is fine since admins will learn the interface.

### 3.2 Registration Management Page (`/registration/:registrationId`)

**File**: `frontend/src/pages/registration/RegistrationManagePage.vue`

#### 3.2.1 Event Info Bar -- Unformatted Date (BUG)

**Problem**: The event info bar renders `eventInfo.start_at` directly without formatting (line 19):
```html
<span class="event-meta">{{ eventInfo.start_at }}<template v-if="eventInfo.location"> ...
```
This displays the raw ISO string (e.g., "2026-06-15T10:00:00Z") to the user. The page has no `formatDate()` function defined in its script section. This is a confirmed bug.

By contrast, the RegistrationPage correctly calls `formatDate(event.start_at)` for the same information.

**Recommendation**: Add a `formatDate()` function and use it: `{{ formatDate(eventInfo.start_at) }}`. This is a P1 fix.

#### 3.2.2 Status Communication

**Problem**: The REGISTERED and WAITLISTED states both use the same visual treatment -- `.status-banner.neutral` (grey background, `#f5f5f5`) with the same hourglass emoji (line 62 and 82). Users visiting this page need to immediately distinguish between "in the running" (REGISTERED) and "on the waitlist" (WAITLISTED).

**What works well**:
- The `statusMessage` from the API provides context-specific text
- The CONFIRMED (action-needed) state is visually distinct with an amber border and celebration emoji (line 103-104)
- "Ja, ich bin dabei!" button is excellent -- clear, actionable, emotionally appropriate (line 159)
- The cancel dialog has warm, empathetic copy (lines 246-253)

**Recommendation**:
- Use different background colours for REGISTERED (light blue) vs WAITLISTED (light grey) to visually distinguish them
- Use different icons (hourglass for REGISTERED/pending, queue icon for WAITLISTED)
- For WAITLISTED, add empathetic phrasing: "Falls jemand absagt, rueckst du automatisch nach."

#### 3.2.3 Group Member Name Entry (CONFIRMED state)

**Problem**: When a user needs to remove a member, the warning "Entfernte Personen koennen nicht wieder hinzugefuegt werden" (line 149-151) appears **only after a member has already been removed** (it is conditioned on `editableMembers.length < originalGroupSize`). This is too late -- the user should understand the consequence before acting.

**What works well**:
- The remove button has no inline confirmation, but the API call `handleRemoveMember()` (line 387) immediately persists the change server-side, which is the correct pattern (no optimistic local-only deletion)
- The first member (index 0, the registrant themselves) cannot be removed (line 139, 201)

**Recommendation**:
- Show the warning text before any removal occurs, or at minimum show a brief inline confirmation when clicking the remove button
- In the CONFIRMED state, the `removeMember()` function (line 351) does a local-only splice without API call -- this means if the user then clicks "Ja, ich bin dabei!", the reduced list is sent. This is intentional but could lose data if the user navigates away. Consider auto-saving on removal like the PARTICIPATING state does.

#### 3.2.4 Cancel Flow

**What works well**:
- The dialog text adapts based on status (PARTICIPATING gets stronger warning, line 246-249)
- "Nee, doch nicht" is excellent informal German for the dismiss action (line 258)
- `<dialog>` element is used correctly with `:open` binding

**Minor issue**: The cancel dialog uses `ref="cancelDialog"` (line 235) but this ref is never used in the script. Dead code.

### 3.3 Cancel Page (`/cancel/:registrationId`)

**File**: `frontend/src/pages/cancel/CancelPage.vue`

**Problem**: This page still exists as a standalone component but is effectively dead code. The router redirects `/cancel/:registrationId` to `/registration/:registrationId` (router line 38-42). However, `CancelPage.vue` is still imported by the router as a lazy-loaded route -- wait, actually checking the router again: the redirect is done inline and CancelPage.vue is **never referenced in the router**. It is orphaned code.

Similarly, `ConfirmPage.vue` is never referenced in the router -- it too is orphaned.

**Recommendation**: Remove `CancelPage.vue` and `ConfirmPage.vue` from the codebase, or if they serve as reference, document them as deprecated. They add ~640 lines of unused code.

### 3.4 Confirm Page (`/confirm/:registrationId`)

**File**: `frontend/src/pages/confirm/ConfirmPage.vue`

Same as above -- orphaned. But worth noting: this page shows raw `registration.status` in two places (lines 80, 153) without `formatStatus()`, and displays raw status in the "already cancelled" detail card (line 23 of CancelPage: `registration.status`). If these pages were to be re-used, they would need the same translation treatment.

### 3.5 Home Page (`/`)

**File**: `frontend/src/pages/Home.vue`

**Problem**: The root path `/` redirects to `/login` (router line 8). The `Home.vue` component contains only a placeholder paragraph: "Welcome. Replace this placeholder with registration/admin routes." (line 3). It appears to be unused -- no route points to it.

**Recommendation**: Either remove `Home.vue` or create a proper landing page. Currently, public users who visit the root URL are sent to the admin login page, which is confusing if they are not admins.

---

## 4. Admin Pages Review

### 4.1 Navigation

**File**: `App.vue` lines 2-30

**Problem**:
1. **No active state**: There is no visual indication of which page the user is currently on. Both "Veranstaltungen" and "Debug" are plain `<router-link>` elements with no `.router-link-active` styling.
2. **Dense horizontal bar**: The nav crams "Funke" brand, nav links, user email, and logout button into a single horizontal bar. On narrow screens, Pico CSS nav wraps these unpredictably.
3. **No hamburger/collapse on mobile**: The nav has no responsive collapse mechanism.

**What works well**:
- The Debug link is intentionally muted (`.debug-link`, line 63-66), appropriately de-emphasising a developer tool
- Logout button is styled as `outline secondary`, correctly signalling it is not a primary action

**Recommendation**:
- Add active state styling via `.router-link-exact-active` (Vue Router provides this class automatically)
- Visually separate user info (email + logout) from navigation links
- On mobile, consider collapsing or stacking the nav

### 4.2 Events Page

**File**: `frontend/src/pages/admin/EventsPage.vue`

#### 4.2.1 Status Filter Tabs

**Problem**: The filter tabs are functional. "In Bearbeitung" groups `REGISTRATION_CLOSED`, `LOTTERY_PENDING`, and `CONFIRMED` which is a smart UX choice. The tabs use `nav a.active` styling (CSS line 852-855) with a filled primary background. Issues:
1. No count badges showing how many events are in each state
2. Tabs may overflow horizontally on narrow screens without scroll indicator
3. German labels in the tabs are good -- but they do not match the raw English status badges in the table below them

**Recommendation**:
- Add count badges: e.g., "Offen (3)"
- Consider a gradient fade on mobile to indicate horizontal scroll
- Ensure tab labels and table status badges use the same German terminology

#### 4.2.2 Events Table -- Registration Column Density

**Problem**: The "Anmeldungen" column (line 96-98) packs dense information:
```
{{ event.registration_spots }} Pers. ({{ event.registration_count }}) . {{ event.confirmed_spots }} Best. / {{ event.capacity }}
```
With optional waitlist: `(+{{ event.waitlist_spots }} WL)`

The abbreviations "Pers.", "Best.", "WL" require learned knowledge. This is the densest column in the table.

**Recommendation**:
- Split into two sub-lines or use a more readable format
- Replace abbreviations with clearer labels or add `title` attributes
- Consider a mini progress bar showing confirmed/capacity ratio

#### 4.2.3 Empty State

**Problem**: "Noch keine Veranstaltungen. Leg los und erstelle deine erste!" is friendly and appropriate, but it is a plain `<p>` tag (line 66-68) with no visual emphasis and no action button.

**Recommendation**: Style as a centred empty state card with visual emphasis, and duplicate the "Neue Veranstaltung" button within the empty state area so the user has a clear call-to-action.

#### 4.2.4 Event Reload on Filter Change

**Problem**: `watch(statusFilter, loadEvents)` on line 819 triggers a full API reload when the filter changes. But `loadEvents()` always fetches all events (no status parameter is passed to the API), and filtering is done client-side via `filteredEvents` computed. This means every filter tab click triggers an unnecessary API call.

**Recommendation**: Remove the watcher on `statusFilter` or change `loadEvents()` to only be called on mount and explicit refresh. The client-side `filteredEvents` computed already handles filtering correctly.

### 4.3 Event Detail Modal

**File**: `frontend/src/components/EventDetailModal.vue`

#### 4.3.1 Information Density

**Problem**: The modal is 1100px wide (line 3) and contains an event info summary, a full registration table with filters, and a three-tier button system. This is a lot of content for a modal overlay.

**What works well**:
- The event info summary is compact and well-structured (lines 23-44)
- The capacity display "X / Y bestaetigt, Z ausstehend" is clear
- Conditional display of waitlist and promoted info

**Recommendation**: Consider whether this should be a full page rather than a modal. At minimum, the table area should have `max-height` with scroll so the footer buttons remain visible.

#### 4.3.2 Button Hierarchy

**Problem**: The three-tier system (Primary / Utility / Destructive) is well-structured:
- **Tier 1** (line 59-88): Single workflow button, full-width -- excellent
- **Tier 2** (line 91-146): Up to 8 buttons in a wrapped flex row -- overwhelming
- **Tier 3** (line 149-177): Behind a `<details>` disclosure -- good pattern for hiding destructive actions

Issues with Tier 2:
- All buttons are outline-styled, making them visually equivalent
- "Boardingzettel" and "Einladungstext" are specialist terms without explanations
- The button labels change contextually (e.g., "Link kopieren" vs "Link kopieren (Warteliste)") which is good, but there are too many buttons at once

**Recommendation**:
- Group Tier 2 buttons by function with subtle separators or labels
- Add tooltips for specialist terms
- Consider moving less-used actions (Nachrichten, Boardingzettel) into the `<details>` section or a submenu

#### 4.3.3 Close Button Redundancy

**Problem**: There is both an X close button in the header (line 5-9) and a "Schliessen" button at the bottom footer (line 179). The footer button is styled as a primary action (`close-btn`, CSS line 301-304) and aligned to the right, but visually it competes with the workflow actions above it.

**Recommendation**: Remove the footer "Schliessen" button. The header X and Escape key (native `<dialog>` behaviour) are sufficient. If kept, style it as a subtle text link.

### 4.4 Registration Table

**File**: `frontend/src/components/RegistrationTable.vue`

#### 4.4.1 Table on Small Screens

**Problem**: The table has 7-8 columns (Name, Email, Phone, Persons, Status, Promoted, Registered, Actions). On screens under ~1000px this overflows. There is no `overflow-x: auto` on the table container.

**Recommendation**: At minimum, add `overflow-x: auto` to a wrapping div. On mobile, consider a card-based view per registration.

#### 4.4.2 "Gesehen" Badge

**Problem**: The "Gesehen" badge (line 68-74) uses `0.65rem` font-size (CSS line 323) which is ~9.1px effective with the root reduction. The badge conveys useful admin information (whether a CONFIRMED registrant has viewed their management page) but is nearly invisible.

**Recommendation**: Raise to at least `0.75rem`. Consider a visual indicator on the status badge itself (e.g., a dot or eye icon) with a tooltip showing the last-seen timestamp.

#### 4.4.3 Context Menu Accessibility

**Problem**: The context menu trigger (lines 96-101) uses `all: unset` (CSS line 341), which removes all default button styles including focus outline. This is an accessibility violation -- keyboard users cannot see when the trigger is focused.

The menu items (lines 103-125) also use `all: unset` (CSS line 370). Both lack `:focus-visible` styles.

Additionally:
- The menu has no keyboard navigation (arrow keys, Enter to select, Escape to close)
- For the last table rows, the dropdown may overflow the modal/viewport (positioned via `top: 100%`, CSS line 359)
- No transition/animation on open/close

**Recommendation**:
- Add `:focus-visible` styles to both trigger and items
- Add keyboard navigation (Escape to close, arrow keys)
- Consider flipping the menu upward for bottom rows
- Add a subtle fade-in transition

#### 4.4.4 `hasActions()` Logic Bug

**Problem**: `hasActions()` on line 176-179 has a logical issue:
```js
function hasActions(reg) {
  return reg.status !== 'CANCELLED'
    || (reg.status === 'WAITLISTED' && props.eventStatus === 'CONFIRMED')
}
```
The second condition can never be true when combined with the first via `||`. If `reg.status !== 'CANCELLED'` is false (meaning status IS 'CANCELLED'), then `reg.status === 'WAITLISTED'` is also false. The function effectively just returns `reg.status !== 'CANCELLED'`, which is probably the intended behaviour, but the second condition is dead code.

**Recommendation**: Simplify to `return reg.status !== 'CANCELLED'` or fix the logic if the intent was different.

### 4.5 Lottery Page

**File**: `frontend/src/pages/admin/events/[eventId]/lottery.vue`

#### 4.5.1 Overall Layout -- Best-Designed Page

**Strengths**:
- Panel containers with headers: excellent visual grouping (`.panel`, CSS line 394-400)
- Summary metrics grid: clean and scannable (lines 46-63)
- Lottery metadata (seed, execution time, status): well-presented for admin transparency (lines 114-139)
- Back-link to events page: good navigation (line 6)
- Capacity warning for over-promoted registrations: proactive error prevention (line 67-70)

This page should serve as the design reference for the rest of the app.

#### 4.5.2 Issues

1. **Summary metrics grid uses `repeat(3, ...)` but has 4 items** (line 378): "Plaetze", "Bestaetigt", "Warteliste", "Bevorzugt". The 4th wraps to a new row, creating visual imbalance.

2. **"Abschliessen & Benachrichtigen" vs "Neu mischen" button distinction**: Both are in the `.actions` div (line 80-107). "Abschliessen" uses default (primary) styling while "Neu mischen" uses `.secondary`. This is **actually correct** -- the draft spec claimed they were similarly styled, but checking the code: "Neu mischen" has `class="secondary"` (lines 84, 93) while "Abschliessen" has no class modifier (lines 100-105), making it the primary button. This is the correct hierarchy.

3. **Raw event status displayed** (line 16): `{{ event.status }}` shows English code. See issue 2.2.

4. **No post-finalization guidance**: After finalizing the lottery, the page updates its state but provides no "next step" message guiding the admin back to manage confirmations.

**Recommendation**:
- Change grid to `repeat(4, minmax(100px, 1fr))` or `repeat(auto-fit, minmax(120px, 1fr))`
- Translate event status to German
- After finalization, show a guidance message: "Teilnehmende wurden benachrichtigt. Du kannst den Bestaetigungsstatus in der Veranstaltungsuebersicht verfolgen." with a "Zurueck zur Uebersicht" button

### 4.6 Debug Page

**File**: `frontend/src/pages/admin/DebugPage.vue`

**Problem**: The debug page is explicitly a developer tool, so design standards are relaxed. However:
- Font sizes reach `0.65rem` (CSS line 577) = ~9.1px effective -- too small even for a debug view
- Status badge CSS is fully duplicated (lines 571-634, 18 rules) from other components
- The registrations table has 11 columns (`white-space: nowrap` on all cells, line 486), which overflows on most screens without any scroll container
- Raw English status codes shown everywhere (no `formatStatus()`)
- `alert('Link kopiert!')` on line 207
- Memory leak: `visibilitychange` listener not cleaned up (see 2.9)

**Recommendation**: Since this is a debug tool, minimal changes needed:
- Raise minimum font size to `0.75rem`
- Share status badge CSS via a utility class
- Add `overflow-x: auto` to the table wrapper
- Fix the event listener cleanup

### 4.7 Message Composer

**File**: `frontend/src/components/MessageComposer.vue`

**What works well**:
- Recipient selection by status filter with select-all toggle
- Recipient count in the send button: `Senden (${selectedIds.length})` (line 115) -- good
- "Verwaltungslink einfuegen" checkbox (line 83-90) -- useful feature
- Scrollable recipient list with max-height (CSS line 254)

**Issues**:
1. Status badges in the recipient list show raw English status codes (line 53): `{{ reg.status }}`. The status filter dropdown uses German labels (lines 28-33), creating inconsistency within the same component.
2. The `status-badge` CSS is duplicated again (lines 270-283)
3. Form state is not fully reset on close -- if the user opens the composer, starts typing, closes without sending, then reopens, the previous content remains. The watcher on line 175-179 only resets `statusFilter`, not the message content.

**Recommendation**:
- Use `formatStatus()` for the status badges in the recipient list
- Reset all form state (subject, body, selectedIds, includeLinks) when the dialog opens
- Share status badge CSS

### 4.8 Message Log

**File**: `frontend/src/components/MessageLog.vue`

**What works well**:
- Message type labels are translated to German via `formatType()` (line 108-119)
- Message status labels are translated via `formatMsgStatus()` (line 121-129)
- Clean table layout

**Issues**:
1. Status badge CSS duplicated again (lines 144-157)
2. On large event histories, the table could become very long inside the dialog without pagination or virtual scrolling

### 4.9 Event Form

**File**: `frontend/src/components/EventForm.vue`

**What works well**:
- Two-column grid for related fields (Name/Location, Date/Capacity, Deadline/Reminders)
- Proper label/input associations
- Smart Berlin timezone handling with `berlinToUTCISO()`
- Default values (capacity: 80, reminders: "7, 3, 1") reduce friction

**Issues**:
1. The reminder schedule input (line 78-82) uses free-text comma-separated input. The placeholder "7, 3, 1" helps, but a first-time admin might not understand the format. The label "Erinnerungen (Tage vorher)" is better than the draft spec claimed ("Erinnerungsplan (optional)") -- the draft was inaccurate here.
2. "Automatisch von der Warteliste nachruecken lassen" checkbox (line 86-93) -- the label is clear. The draft claimed this lacked explanation, but the label is actually self-explanatory. No change needed.
3. The two-column grid does not collapse on mobile -- there is no `@media` query to stack columns on small screens. The `.form-row` uses `grid-template-columns: 1fr 1fr` (CSS line 231) with no responsive override.

**Recommendation**:
- Add `@media (max-width: 576px) { .form-row { grid-template-columns: 1fr; } }` for responsive stacking
- Consider adding a small hint below the reminder field: "z.B. 7,3,1 -- Tage vor dem Event"

### 4.10 Help Panel

**File**: `frontend/src/components/help/HelpPanel.vue`

**What works well**:
- Slides in from right with CSS transition (lines 126-135)
- Sticky header within scrollable panel (CSS line 60-62)
- Responsive: full-width on mobile (CSS line 138-145)
- Properly scoped with `z-index: 100`
- Content is computed based on `helpKey` prop

**Issues**:
1. Positioned `absolute` (CSS line 41), which overlaps content rather than pushing it aside. On narrow screens at full-width, it completely covers the underlying content with no backdrop.
2. Uses `v-html` for section content (line 15), which is a potential XSS vector. Since content comes from a local JS file (`helpContent.js`), this is safe in practice, but should be documented.
3. The `max-height: 70vh` (CSS line 44) might clip long help content on short viewports.

**Recommendation**:
- Add a semi-transparent backdrop behind the panel to make the overlay feel intentional
- Document the `v-html` usage safety in a code comment
- The current approach is acceptable for help content (it is reference material, not workflow)

---

## 5. User Flow Analysis

### 5.1 Public User Journey

```
Registration Link -> See event details -> Fill form -> Submit -> See confirmation
                                                                    |
                                                          (receives email)
                                                                    |
Email link -> Registration Management Page -> See status -> Take action (confirm/cancel)
```

**Issues in the flow:**

1. **No recovery path for management URL**: After registration success, the management page link is only available in the confirmation email. If the email is delayed, filtered, or lost, the user has no way to manage their registration. The success screen (RegistrationPage lines 128-153) does not display the management URL.

2. **Token-dependent management URL**: The management page requires `?token=...` in the query string (RegistrationManagePage line 322-329). If a user bookmarks the URL without the token (which some browsers strip), or if the token is truncated when pasted, they get an error with no recovery guidance. The error message "Ungueltiger Link. Schau nochmal in deiner E-Mail nach." (line 326) is helpful but could also suggest checking spam folders.

3. **No navigation from public pages**: Public pages (registration, management) have no header navigation. Users land cold from external links. This is intentional and correct for a focused single-task flow. No change needed.

4. **Root URL redirects to admin login**: A public user who visits `funke.example.com/` is sent to the admin login page. There is no public-facing landing or "about" page. This is confusing if a non-admin user accidentally navigates to the root.

**Recommendation**:
- After registration success, display the management page link: "Speichere diesen Link, um deine Anmeldung spaeter zu verwalten:" with a copy button
- On the management page error state, add: "Schau auch in deinem Spam-Ordner nach."
- Consider a minimal public landing page at `/` that says "Funke -- Verein fuer mobile Machenschaften" with a note that registration links are shared directly

### 5.2 Admin Event Lifecycle

```
Events List -> Create Event -> (back to list) -> View Event Detail -> Publish -> Share Link
    -> Close Registration -> Go to Lottery -> Run -> Review -> Finalize
    -> (back to Events) -> Manage Confirmations -> Complete Event
```

**Issues in the flow:**

1. **No auto-open after creation**: After creating an event, the user returns to the event list (EventsPage line 500-501: `events.value.unshift(newEvent); showCreateModal.value = false`). First-time users may wonder where the new event went, especially if a filter is active that hides DRAFT events.

2. **Mental model shift between modal and page**: Event detail is a modal (1100px overlay), but the lottery is a full page. Navigating from the modal's "Verlosung" button (EventDetailModal line 77) to a full page, then back to the events list (not back to the modal), is slightly disorienting.

3. **No post-lottery next step**: After finalizing the lottery, the admin must independently know to navigate back and monitor confirmations. There is no guided transition.

4. **Unnecessary API reload on filter change**: As noted in 4.2.4, every filter tab click triggers a full `loadEvents()` API call even though filtering is client-side.

**Recommendation**:
- After creating an event, auto-open the event detail modal for the new event
- After finalizing the lottery, show a clear next-step message with a link back to the events overview
- Consider adding breadcrumbs on the lottery page: "Veranstaltungen > {Event Name} > Verlosung"
- Remove the unnecessary API reload on filter change

---

## 6. Accessibility Audit

### 6.1 Critical Issues

1. **Context menu trigger removes focus styles**: `all: unset` on `.context-menu-trigger` (RegistrationTable CSS line 341) and `.context-menu-item` (line 370) removes `:focus-visible` outlines. Keyboard users cannot see which element is focused. **WCAG 2.4.7 violation.**

2. **`<html lang="en">` for German content**: Screen readers will use English pronunciation rules for German text. **WCAG 3.1.1 violation.** See issue 2.7.

3. **Colour contrast failures**: Several status badge combinations likely fail WCAG AA (4.5:1 for normal text):
   - `#d97706` on `#fef3c7` (amber status badges): calculated contrast ~3.5:1 -- **fails AA**
   - `#16a34a` on `#dcfce7` (green status badges): calculated contrast ~3.2:1 -- **fails AA**
   - `#6b7280` on `#e5e7eb` (grey status badges): calculated contrast ~3.7:1 -- **fails AA**

   These affect RegistrationTable, EventsPage, lottery.vue, DebugPage, and MessageComposer.

### 6.2 Major Issues

4. **No keyboard navigation for context menus**: The registration table context menu (RegistrationTable lines 94-126) only responds to click events. No arrow-key navigation, no Escape to close, no Enter to select. The menu close handler (line 194) uses a document-level click listener, which does not handle keyboard events.

5. **Focus management in modals**: When dialogs open, focus should move to the first interactive element. When they close, focus should return to the trigger. Currently relies entirely on browser `<dialog>` defaults, which vary across browsers. Pico CSS `<dialog>` with `:open` attribute binding (not `.showModal()`) may not trap focus at all.

6. **Multiple `alert()` calls**: Native `alert()` is announced differently by screen readers across platforms. Some screen readers may not announce the content at all if the alert interrupts another action.

### 6.3 Minor Issues

7. **Form error association**: Error messages (e.g., RegistrationPage line 117-119) use `role="alert"` which is good for screen reader announcement, but are not associated with specific form fields via `aria-describedby`. Users may not know which field caused the error.

8. **Loading states**: `aria-busy="true"` is correctly used throughout (e.g., EventsPage line 22, RegistrationPage line 4). This is good practice.

9. **Button labels**: HelpButton uses `aria-label="Hilfe"` and `title="Hilfe"` (HelpButton lines 5-6). This is correct.

---

## 7. Proposed Design System Summary

### Colour Palette (Tokens)

| Token | Use | Value |
|-------|-----|-------|
| `--color-brand` | Primary brand accent | TBD (ocean teal or warm orange) |
| `--color-success` | Participating, confirmed actions | `#15803d` (text), `#dcfce7` (bg) -- darkened for contrast |
| `--color-warning` | Pending actions, confirmation needed | `#92400e` (text), `#fef3c7` (bg) -- darkened for contrast |
| `--color-danger` | Cancel, delete, errors | `#dc2626` (text), `#fee2e2` (bg) |
| `--color-info` | Informational, neutral statuses | `#1d4ed8` (text), `#dbeafe` (bg) |
| `--color-neutral` | Muted, draft, waitlisted | `#4b5563` (text), `#e5e7eb` (bg) -- darkened for contrast |
| `--color-purple` | Lottery pending | `#6d28d9` (text), `#ede9fe` (bg) |

Note: Text colours have been darkened from current values to meet WCAG AA contrast ratios on their respective backgrounds.

### Typography Scale

| Token | Size | Use |
|-------|------|-----|
| `--text-xs` | 0.75rem | Badges, captions (minimum) |
| `--text-sm` | 0.875rem | Secondary info, labels |
| `--text-base` | 1rem | Body text |
| `--text-lg` | 1.125rem | Section headings |
| `--text-xl` | 1.5rem | Page titles |

### Spacing Scale

`4, 8, 12, 16, 24, 32, 48, 64` px -- mapped to `--space-1` through `--space-8`.

### Shared Component Classes

- `.status-badge` -- one definition, used everywhere (replaces 6 independent definitions)
- `.btn-danger` -- destructive button styling without `!important`
- `.btn-success` -- confirmation button styling without `!important`
- `.card-panel` -- the lottery page's panel pattern, reusable
- `.info-banner` -- coloured info/warning/error banners
- `.metric-grid` -- the lottery page's metrics layout
- `.error-message` -- replaces 8 independent `.error` definitions

### Shared Utility Module

- `utils/formatters.js`: `formatDate()`, `formatDateTime()`, `formatEventStatus()`, `formatRegistrationStatus()`, `berlinToUTCISO()`

---

## 8. Priority Matrix

| # | Issue | Impact | Effort | Priority |
|---|-------|--------|--------|----------|
| 1 | Fix unformatted date in event info bar (RegistrationManagePage line 19) | High (bug) | Low | P0 |
| 2 | Fix `<html lang="en">` to `lang="de"` (index.html line 2) | High (a11y) | Trivial | P0 |
| 3 | Translate event status codes to German | High (user-facing) | Low | P1 |
| 4 | Create shared design tokens CSS | High (consistency) | Medium | P1 |
| 5 | Remove root font-size override | Medium (readability) | Low | P1 |
| 6 | Replace `alert()`/`confirm()` with toast notifications | Medium (UX) | Medium | P1 |
| 7 | Fix context menu focus/keyboard accessibility | Medium (a11y) | Medium | P1 |
| 8 | Fix colour contrast for WCAG AA compliance | Medium (a11y) | Medium | P1 |
| 9 | Add active state to navigation | Medium (wayfinding) | Low | P1 |
| 10 | Remove unnecessary API reload on filter change (EventsPage) | Low (perf) | Trivial | P1 |
| 11 | Consolidate status badge CSS across components | Medium (maintenance) | Medium | P2 |
| 12 | Extract shared utility functions (formatDate, berlinToUTCISO) | Medium (maintenance) | Medium | P2 |
| 13 | Eliminate `!important` overrides with proper CSS architecture | Medium (maintenance) | Medium | P2 |
| 14 | Add count badges to filter tabs | Medium (clarity) | Low | P2 |
| 15 | Improve events table registration column readability | Medium (clarity) | Low | P2 |
| 16 | Improve event detail modal button grouping | Medium (UX) | Medium | P2 |
| 17 | Add tooltips for specialist terms | Medium (onboarding) | Low | P2 |
| 18 | Add responsive form-row collapse for EventForm | Medium (responsive) | Low | P2 |
| 19 | Add overflow-x:auto to tables in modals | Medium (responsive) | Low | P2 |
| 20 | Show management link on registration success | Medium (recovery) | Low | P2 |
| 21 | Improve registration form inline hints (Gruppengroesse) | Medium (self-service) | Low | P2 |
| 22 | Reset MessageComposer form state on open | Low (UX) | Low | P2 |
| 23 | Fix DebugPage memory leak (visibilitychange listener) | Low (tech debt) | Trivial | P2 |
| 24 | Remove orphaned CancelPage.vue and ConfirmPage.vue | Low (cleanup) | Trivial | P2 |
| 25 | Fix hasActions() dead code in RegistrationTable | Low (cleanup) | Trivial | P2 |
| 26 | Remove dead cancelDialog ref in RegistrationManagePage | Low (cleanup) | Trivial | P2 |
| 27 | Style empty states with visual emphasis | Low (polish) | Low | P3 |
| 28 | Add brand identity (colour, header treatment) | Medium (personality) | Medium | P3 |
| 29 | Improve success state after registration | Low (polish) | Low | P3 |
| 30 | Post-create auto-open event detail | Low (flow) | Low | P3 |
| 31 | Add visual capacity indicator on registration page | Low (delight) | Medium | P3 |
| 32 | Fix lottery metrics grid for 4 items | Low (visual) | Low | P3 |
| 33 | Add breadcrumbs to lottery page | Low (wayfinding) | Low | P3 |
| 34 | Add post-lottery "next step" guidance | Low (flow) | Low | P3 |
| 35 | Differentiate REGISTERED vs WAITLISTED visual treatment | Low (clarity) | Low | P3 |
| 36 | Add backdrop to HelpPanel overlay | Low (polish) | Low | P3 |
| 37 | Create public landing page (replace Home.vue) | Low (completeness) | Low | P3 |
| 38 | Remove footer close button from EventDetailModal | Low (simplification) | Trivial | P3 |

---

## 9. Implementation Strategy

### Phase 0: Quick Fixes (P0 -- ship immediately)
Fix the unformatted date bug and the HTML lang attribute. These are trivial, high-impact changes.

### Phase 1: Foundation (P1 items)
Establish design tokens, fix accessibility violations (focus styles, contrast), replace `alert()` calls, translate status codes, and address the root font-size issue. This creates the foundation for all subsequent work.

### Phase 2: Consistency (P2 items)
Consolidate duplicated CSS, extract shared utilities, improve information density and readability, add responsive breakpoints, fix minor bugs and dead code.

### Phase 3: Polish (P3 items)
Brand identity, visual refinements, flow improvements, empty states, and guidance messaging.

Each phase should be independently shippable. No phase changes any user-facing behaviour -- only presentation and clarity.

---

## 10. Corrections to Original Draft

The following findings from the initial draft were re-evaluated and corrected:

1. **Draft 3.2.1 claimed event info bar date is "likely a bug"** -- **Confirmed as actual bug**. `eventInfo.start_at` is rendered raw on RegistrationManagePage line 19 with no `formatDate()` call. Elevated to P0.

2. **Draft 5.1 claimed "Erinnerungsplan (optional)" label** -- **Inaccurate**. The actual label is "Erinnerungen (Tage vorher)" (EventForm line 75), which is clearer than the draft stated.

3. **Draft 5.1 claimed "Autopromote Warteliste checkbox has no inline explanation"** -- **Inaccurate**. The label reads "Automatisch von der Warteliste nachruecken lassen" (EventForm line 92), which is self-explanatory.

4. **Draft 4.5.2 claimed "Abschliessen" and "Neu mischen" are similarly styled** -- **Inaccurate**. "Neu mischen" has `class="secondary"` while "Abschliessen" uses default primary styling. The hierarchy is already correct.

5. **Draft did not identify**: HTML lang mismatch, orphaned CancelPage/ConfirmPage, unnecessary API reload on filter change, DebugPage memory leak, MessageComposer state persistence issue, hasActions() dead code, EventForm missing responsive breakpoint, or several specific accessibility violations. These have been added.

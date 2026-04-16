# Schaluppe PWA — Navigation Concept

## Context

Schaluppe is an event management PWA for a cultural raft association in Hamburg. It serves two audiences:

1. **Public users** — register for events, manage their registration, confirm attendance
2. **Admin users** — create/manage events, run lotteries, send messages, view registrations

The admin side currently lives almost entirely on a single page (`/admin/events`) with 10+ modals layered on top. This works on desktop but creates navigation confusion on mobile: users lose orientation, can't go "back" to a previous modal, and the bottom tab bar competes with modal actions.

This document defines the navigation strategy for the installed PWA, targeting 2026 mobile-first usability.

---

## 1. Information Architecture

### Two navigation zones (never mixed)

| Zone | Who | Entry point | Navigation pattern |
|------|-----|------------|-------------------|
| **Public** | Anyone with a link | `/register/:token`, `/registration/:id` | No persistent navigation. Single-purpose pages. Back = browser back. |
| **Admin** | Authenticated users | `/admin/events` | Bottom tab bar (mobile), sidebar or top bar (desktop) |

Public pages are standalone — a registrant arrives via email link, completes one task, and leaves. No menu needed, no tabs, no chrome. Maximum screen real estate for the form.

Admin pages are a workspace — users switch between views, take multi-step actions, and need orientation cues at all times.

### Admin page hierarchy

```
Events (list)          ← primary screen, always reachable
  └─ Event (detail)    ← full page, not a modal
      ├─ Registrations (tab/section within detail)
      ├─ Messages (tab/section within detail)
      └─ Lottery (sub-page, already exists)

Settings               ← account, push notifications, about
```

**Key change: Event detail becomes a full page, not a modal.** This is the single most impactful navigation improvement. Modals are appropriate for quick confirmations ("Delete this?") and short forms ("Clone with new date"). They are NOT appropriate for a screen with a registration table, search, filters, 12 action buttons, and multiple sub-modals.

---

## 2. Navigation Pattern: Bottom Tab Bar

### Why bottom tabs

- Thumb-reachable on all phone sizes (2026 phones are 6.1"–6.9")
- Always visible — users never lose the way back
- Most familiar pattern (every major app uses it)
- Works identically as PWA and in browser

### Tab structure (3 tabs)

| Tab | Label | Icon | Destination | Why |
|-----|-------|------|------------|-----|
| **Events** | Events | Calendar | `/admin/events` | Primary task. 90% of admin time is here. |
| **Settings** | Einstellungen | Gear | `/admin/settings` | Push notifications, account info, logout. Replaces current Debug page for non-debug settings. |
| **Debug** | Debug | Terminal/Code | `/admin/debug` | Keep for power users. Can be hidden behind a long-press or toggle in Settings for v2. |

### Why 3, not more

- 3 tabs = no scrolling, large touch targets, instant recognition
- Every tab leads to a distinct top-level section
- Adding more tabs later (e.g., "Statistiken") is easy — up to 5 tabs is fine

### Tab behavior

- Tapping the active tab scrolls to top and resets the view (closes any open state)
- Active tab has brand-color highlight and bold label
- Inactive tabs are muted gray
- Tab bar height: 56px (48px content + 8px safe area on iPhone)
- Touch target: minimum 48x48px per tab (WCAG 2.5.8)

---

## 3. Page-Level Navigation

### Events list → Event detail

**Current:** Clicking an event opens a dialog on the same page.
**Proposed:** Clicking an event navigates to `/admin/events/:eventId` — a full page.

Benefits:
- Browser back button works naturally
- URL is shareable/bookmarkable
- Scroll position on event detail is independent from the list
- No z-index stacking issues from modals-within-modals
- Bottom tab bar remains visible (user always knows where they are)

### Event detail page structure

Instead of one massive modal, the event detail page uses **sections** or **tabs within the page**:

```
┌─────────────────────────────────┐
│ ← Events    Bootsfahrt Juli     │  ← Top bar with back + event name
│ Status: OFFEN                   │
├─────────────────────────────────┤
│ [Details] [Anmeldungen] [Nachr.]│  ← In-page tabs (horizontal scroll)
├─────────────────────────────────┤
│                                 │
│  (Tab content area)             │
│                                 │
├─────────────────────────────────┤
│ [Primary action button]         │  ← Sticky footer with status-aware CTA
├─────────────────────────────────┤
│ [Events] [Settings] [Debug]     │  ← Bottom tab bar (always visible)
└─────────────────────────────────┘
```

**In-page tabs for event detail:**

| Tab | Content |
|-----|---------|
| **Details** | Event info (name, date, location, capacity, description), edit button, utility actions (clone, copy link, export PDF) |
| **Anmeldungen** | Registration table with search + filter. Context menu per row. |
| **Nachrichten** | Message log + "Neue Nachricht" button → opens composer (still a modal — it's a short form) |

**Sticky footer CTA:** One primary action button at the bottom of the page (above tab bar), changes with event status:
- DRAFT → "Veröffentlichen"
- OPEN → "Anmeldung schließen"
- REGISTRATION_CLOSED → "Zur Verlosung"
- CONFIRMED → "Abschließen"

### What stays as modals

Keep modals for short, focused interactions:
- **Confirmations:** Cancel event, delete event, delete registration
- **Short forms:** Clone event (just a date picker), edit event (form)
- **Message composer** (focused writing task, benefits from overlay focus)
- **Discard unacknowledged** (short checklist + send)

### What becomes a full page

- **Event detail** (too complex for a modal)
- **Lottery** (already a full page — good)

---

## 4. Labels and Language

### Principles
- German UI throughout (matches existing app)
- Verb-first for actions: "Erstellen", "Bearbeiten", "Absagen"
- Noun for destinations: "Events", "Einstellungen"
- No jargon: "Anmeldung" not "Registration", "Verlosung" not "Lottery"
- Consistent: same action always has the same label everywhere

### Navigation labels

| Element | Label | Reason |
|---------|-------|--------|
| Tab 1 | Events | Short, clear, matches page title |
| Tab 2 | Einstellungen | Standard German app convention |
| Tab 3 | Debug | Technical term intentional — this is a power-user page |
| Back button | ← Events | Shows where "back" goes (not just an arrow) |
| Primary CTA | Status-dependent verb | "Veröffentlichen", "Schließen", etc. |

---

## 5. State Handling

### Active tab indication
- Bottom tab icon + label colored in brand navy (`#0C1E3C`)
- 2px bar above the active tab (standard iOS/Android indicator)
- Inactive tabs in `#8B95A1` (muted)

### Orientation cues on event detail
- **Breadcrumb-style back button:** "← Events" (not just an arrow)
- **Event name** in the top bar (truncated with ellipsis if long)
- **Status badge** visible at all times
- **In-page tab underline** shows which section you're viewing

### Loading states
- Skeleton screens (gray placeholder shapes) instead of spinners
- Tab bar never shows loading state — it's always interactive
- Page content loads independently of navigation chrome

### Error states
- Inline error banners within the page content area
- Navigation remains fully functional during errors
- "Retry" button next to error message

---

## 6. Desktop Adaptation

On screens wider than 768px:
- Bottom tab bar can optionally move to a **left sidebar** (48px collapsed, 200px expanded)
- Or remain at the bottom — both are acceptable in 2026
- Event list and event detail can show **side-by-side** (master-detail) on screens > 1024px
- In-page tabs become a horizontal tab bar below the event header

The mobile layout is the primary design. Desktop is a progressive enhancement, not the other way around.

---

## 7. Accessibility

| Requirement | Implementation |
|-------------|---------------|
| Touch targets | Minimum 48x48px (WCAG 2.5.8) |
| Color contrast | All text 4.5:1 against background (WCAG AA) |
| Active state | Never rely on color alone — use bold + underline + icon fill |
| Screen reader | Tab bar uses `role="navigation"`, `aria-current="page"` on active tab |
| Keyboard | Tabs focusable with arrow keys, Enter activates |
| Reduced motion | Respect `prefers-reduced-motion` for tab transitions |
| Focus management | On page navigation, focus moves to page heading (h1) |
| Safe areas | `env(safe-area-inset-bottom)` for iPhone home indicator |

---

## 8. Design Principles Behind These Decisions

1. **One screen, one purpose.** If a screen does more than one thing, it needs in-page tabs — not modal stacking.

2. **Back always works.** Every navigation action is reversible. Browser back, swipe back, "← Events" — all do the same thing.

3. **Navigation is not content.** The tab bar and back button are navigation chrome. They never change, never hide, never compete with content.

4. **Progressive disclosure, not hidden menus.** All primary actions are visible. Destructive actions are in a clearly marked "danger zone" section — visible but separated, not hidden behind a kebab menu.

5. **Thumb zone first.** Primary actions at the bottom of the screen. Navigation at the bottom. Only read-only content at the top.

6. **Consistent everywhere.** Same tab bar on every admin page. Same back-button pattern on every sub-page. Same modal pattern for every confirmation.

---

## 9. Do's and Don'ts

### Do's
- **Do** use the bottom tab bar for all top-level navigation
- **Do** use full pages for complex views (event detail, lottery)
- **Do** use modals only for quick confirmations and short forms
- **Do** show a labeled back button ("← Events") on sub-pages
- **Do** keep the primary action as a sticky footer button
- **Do** show status badges consistently (same colors, same positions)
- **Do** provide loading skeletons for content areas
- **Do** respect safe areas on all mobile devices
- **Do** make every interactive element at least 48x48px

### Don'ts
- **Don't** nest modals inside modals (never more than 1 modal deep)
- **Don't** hide primary actions behind hamburger menus or kebab menus
- **Don't** use swipe gestures as the only way to access actions
- **Don't** change the tab bar based on context or page
- **Don't** use toast notifications for important outcomes (use inline feedback)
- **Don't** auto-close modals on background tap for destructive actions
- **Don't** put navigation labels in ALL CAPS (harder to read in German)
- **Don't** use icon-only tabs — always include a text label
- **Don't** disable the tab bar while content is loading

---

## 10. Proposed Menu Structure (Summary)

```
Bottom Tab Bar (always visible, authenticated users only)
├── Events (/admin/events)
│   └── Event Detail (/admin/events/:id)  ← full page
│       ├── [Tab] Details
│       ├── [Tab] Anmeldungen
│       ├── [Tab] Nachrichten
│       └── Verlosung (/admin/events/:id/lottery)  ← sub-page
├── Einstellungen (/admin/settings)
│   ├── Push-Benachrichtigungen
│   ├── Konto (email, role)
│   └── Abmelden
└── Debug (/admin/debug)

Modals (context-dependent, max 1 deep)
├── Neue Veranstaltung (create form)
├── Bearbeiten (edit form)
├── Duplizieren (date picker)
├── Nachricht senden (composer)
├── Absagen bestätigen (confirmation)
├── Löschen bestätigen (confirmation)
└── Anmeldung löschen (confirmation)

Public pages (no tab bar, no navigation chrome)
├── /register/:token (registration form)
└── /registration/:id (manage registration)
```

---

## 11. Testing the Navigation with Real Users

### Quick hallway test (30 minutes, 3-5 people)

Give the phone to someone unfamiliar with the app. Ask them to complete these tasks without guidance:

1. "Find the list of all events."
2. "Open the event 'Bootsfahrt Juli' and check how many people signed up."
3. "Go back to the event list."
4. "Send a message to all confirmed participants of that event."
5. "Turn on push notifications."
6. "Log out."

**What to watch for:**
- Do they tap the correct tab immediately, or hesitate?
- Do they use the back button or the tab bar to return to the list?
- Can they find the message action without help?
- Do they look for Settings in the tab bar or somewhere else?

### Success criteria
- **Task 1-3:** Completed in under 10 seconds each, zero wrong taps
- **Task 4:** Completed in under 30 seconds (involves sub-navigation)
- **Task 5-6:** Completed in under 15 seconds each
- **Zero "Where am I?" moments** — user always knows which screen they're on

### Follow-up questions
- "Was anything confusing or unexpected?"
- "Where would you look for [feature X] if I asked you to find it?"
- "Did you feel lost at any point?"

If 4 out of 5 users complete all tasks without help, the navigation works. If any task fails for 2+ users, redesign that path before shipping.

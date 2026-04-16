# PWA Navigation Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Schaluppe PWA navigation from modal-driven to page-driven architecture per the nav concept spec.

**Architecture:** Extract event detail from a dialog on EventsPage into a full standalone page at `/admin/events/:eventId`. Create a Settings page for account/push actions. Keep the bottom tab bar with 3 tabs (Events, Settings, Debug). All existing modals for short interactions (create, edit, clone, confirm-delete) remain as modals — they just live on the detail page now instead of the list page.

**Tech Stack:** Vue 3 (Composition API, script setup), Vue Router 4, Pico CSS 2

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `frontend/src/pages/admin/EventDetailPage.vue` | Full-page event detail with in-page tabs (Details, Anmeldungen, Nachrichten) |
| `frontend/src/pages/admin/SettingsPage.vue` | Push notifications, account info, logout |
| `frontend/src/composables/useEventActions.js` | Shared event action handlers (publish, cancel, clone, delete, etc.) extracted from EventsPage |

### Modified files
| File | Change |
|------|--------|
| `frontend/src/pages/admin/EventsPage.vue` | Remove EventDetailModal + all detail-related state/handlers. Event name click navigates to route. |
| `frontend/src/pages/admin/DebugPage.vue` | Remove push notification section (moved to Settings) |
| `frontend/src/components/EventDetailModal.vue` | Delete (replaced by EventDetailPage) |
| `frontend/src/router/index.js` | Add `/admin/events/:eventId` and `/admin/settings` routes |
| `frontend/src/App.vue` | Add Settings tab, update active-state logic |

### Unchanged files (reused as-is)
- `EventForm.vue` — used in create/edit modals (same props/emits)
- `RegistrationTable.vue` — used in Anmeldungen tab (same props/emits)
- `MessageComposer.vue` — used as modal on detail page (same props/emits)
- `MessageLog.vue` — used as modal on detail page (same props/emits)
- `help/useHelp.js` — used on detail page (same API)
- All backend files — zero changes

---

## Task 1: Create useEventActions composable

Extract the event action handlers from EventsPage into a reusable composable. Both EventsPage (for create) and EventDetailPage (for all detail actions) will use it.

**Files:**
- Create: `frontend/src/composables/useEventActions.js`

- [ ] **Step 1: Create the composable**

```javascript
// frontend/src/composables/useEventActions.js
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../services/api'
import { showToast } from './useToast.js'

/**
 * Shared event action handlers.
 * @param {object} options
 * @param {import('vue').Ref<object|null>} options.event - reactive event ref
 * @param {import('vue').Ref<Array>} options.registrations - reactive registrations ref
 * @param {Function} options.refreshEvent - reload event data
 * @param {Function} options.refreshRegistrations - reload registrations
 */
export function useEventActions({ event, registrations, refreshEvent, refreshRegistrations }) {
  const router = useRouter()

  // Action loading states
  const publishing = ref(false)
  const closingRegistration = ref(false)
  const completing = ref(false)
  const togglingPromotedId = ref(null)

  // Clone modal state
  const cloneEvent = ref(null)
  const cloneStartAt = ref('')
  const cloning = ref(false)
  const cloneError = ref(null)

  // Cancel event modal state
  const cancelEventData = ref(null)
  const cancelConfirmation = ref('')
  const cancelling = ref(false)
  const cancelError = ref(null)

  // Edit modal state
  const editEventData = ref(null)
  const editing = ref(false)
  const editError = ref(null)

  // Delete event modal state
  const deleteEventData = ref(null)
  const deleting = ref(false)
  const deleteError = ref(null)

  // Delete registration modal state
  const deleteRegData = ref(null)

  // Capacity warning
  const capacityWarning = ref(null)

  // Message modals
  const showMessageComposer = ref(false)
  const showMessageLog = ref(false)

  // Discard unacknowledged modal
  const showDiscardModal = ref(false)
  const discardSubject = ref('')
  const discardMessage = ref('')
  const selectedDiscardIds = ref(new Set())
  const discarding = ref(false)
  const discardError = ref(null)

  async function publishEvent() {
    publishing.value = true
    try {
      const updated = await adminApi.publishEvent(event.value.id)
      event.value = updated
      showToast('Veranstaltung veröffentlicht', 'success')
    } catch (err) {
      showToast(err.message || 'Fehler beim Veröffentlichen', 'error')
    } finally {
      publishing.value = false
    }
  }

  async function closeRegistration() {
    closingRegistration.value = true
    try {
      const updated = await adminApi.closeRegistration(event.value.id)
      event.value = updated
      showToast('Anmeldung geschlossen', 'success')
    } catch (err) {
      showToast(err.message || 'Fehler beim Schließen', 'error')
    } finally {
      closingRegistration.value = false
    }
  }

  async function completeEvent() {
    completing.value = true
    try {
      const updated = await adminApi.completeEvent(event.value.id)
      event.value = updated
      showToast('Veranstaltung abgeschlossen', 'success')
    } catch (err) {
      showToast(err.message || 'Fehler beim Abschließen', 'error')
    } finally {
      completing.value = false
    }
  }

  function showCloneModal() {
    cloneEvent.value = event.value
    cloneStartAt.value = ''
    cloneError.value = null
  }

  async function handleClone() {
    cloning.value = true
    try {
      const { berlinToUTCISO } = await import('../utils/formatters.js')
      const isoString = berlinToUTCISO(cloneStartAt.value)
      const cloned = await adminApi.cloneEvent(cloneEvent.value.id, isoString)
      cloneEvent.value = null
      showToast('Veranstaltung dupliziert', 'success')
      router.push(`/admin/events/${cloned.id}`)
    } catch (err) {
      cloneError.value = err.message || 'Fehler beim Duplizieren'
    } finally {
      cloning.value = false
    }
  }

  function copyRegistrationLink() {
    const url = `${window.location.origin}/register/${event.value.registration_link_token}`
    navigator.clipboard.writeText(url).then(() => {
      showToast('Link kopiert!', 'success')
    }).catch(() => {
      prompt('Link kopieren:', url)
    })
  }

  function copyInviteText() {
    const { formatDateGerman, formatTimeGerman } = import('../utils/formatters.js').then ? {} : {}
    // Dynamic import for formatters
    import('../utils/formatters.js').then(({ formatDateGerman, formatTimeGerman }) => {
      const e = event.value
      const link = `${window.location.origin}/register/${e.registration_link_token}`
      const date = formatDateGerman(e.start_at)
      const time = formatTimeGerman(e.start_at)
      const parts = [`🚢 ${e.name}`, '']
      if (e.description) parts.push(e.description, '')
      parts.push(`📅 ${date} um ${time} Uhr`)
      if (e.location) parts.push(`📍 ${e.location}`)
      parts.push(`👥 ${e.capacity} Plätze`, '', `🔗 Anmeldung: ${link}`)
      navigator.clipboard.writeText(parts.join('\n')).then(() => {
        showToast('Einladungstext kopiert!', 'success')
      }).catch(() => {
        prompt('Einladungstext kopieren:', parts.join('\n'))
      })
    })
  }

  function goToLottery() {
    router.push({ name: 'admin-event-lottery', params: { eventId: event.value.id } })
  }

  function showCancelEventModal() {
    cancelEventData.value = event.value
    cancelConfirmation.value = ''
    cancelError.value = null
  }

  async function handleCancelEvent() {
    if (cancelConfirmation.value !== 'absagen') return
    cancelling.value = true
    try {
      const updated = await adminApi.cancelEvent(cancelEventData.value.id)
      event.value = updated
      cancelEventData.value = null
      showToast('Veranstaltung abgesagt', 'success')
    } catch (err) {
      cancelError.value = err.message || 'Fehler beim Absagen'
    } finally {
      cancelling.value = false
    }
  }

  function showEditModal() {
    editEventData.value = event.value
    editError.value = null
  }

  async function handleEdit(formData) {
    editing.value = true
    try {
      const updated = await adminApi.updateEvent(editEventData.value.id, formData)
      event.value = updated
      editEventData.value = null
      showToast('Veranstaltung gespeichert', 'success')
    } catch (err) {
      editError.value = err.message || 'Fehler beim Speichern'
    } finally {
      editing.value = false
    }
  }

  function showDeleteModal() {
    deleteEventData.value = event.value
    deleteError.value = null
  }

  async function handleDelete() {
    deleting.value = true
    try {
      await adminApi.deleteEvent(deleteEventData.value.id)
      deleteEventData.value = null
      showToast('Veranstaltung gelöscht', 'success')
      router.push('/admin/events')
    } catch (err) {
      deleteError.value = err.message || 'Fehler beim Löschen'
    } finally {
      deleting.value = false
    }
  }

  async function handleExportPdf() {
    try {
      await adminApi.exportBoardingPdf(event.value.id)
    } catch (err) {
      showToast(err.message || 'Export fehlgeschlagen', 'error')
    }
  }

  async function handleTogglePromoted({ registrationId, promoted }) {
    togglingPromotedId.value = registrationId
    try {
      await adminApi.togglePromoted(event.value.id, registrationId, promoted)
      await Promise.all([refreshRegistrations(), refreshEvent()])
    } catch (err) {
      showToast(err.message || 'Fehler beim Ändern', 'error')
    } finally {
      togglingPromotedId.value = null
    }
  }

  async function handlePromoteWaitlisted({ registrationId, targetStatus }) {
    const reg = registrations.value.find((r) => r.id === registrationId)
    if (!reg) return
    const needed = reg.group_size || 1
    const confirmed = event.value.confirmed_spots || 0
    const capacity = event.value.capacity || 0
    const remaining = capacity - confirmed
    if (needed > remaining) {
      capacityWarning.value = { name: reg.name, needed, remaining }
      return
    }
    try {
      await adminApi.promoteFromWaitlist(event.value.id, registrationId, targetStatus)
      await Promise.all([refreshRegistrations(), refreshEvent()])
      showToast(`${reg.name} nachgerückt`, 'success')
    } catch (err) {
      showToast(err.message || 'Fehler beim Nachrücken', 'error')
    }
  }

  function handleDiscardUnacknowledged() {
    discardSubject.value = `Absage: ${event.value.name}`
    discardMessage.value = `Hallo {name},\n\nleider müssen wir deine Anmeldung für "${event.value.name}" zurücknehmen, da du die Teilnahme nicht rechtzeitig bestätigt hast.\n\nViele Grüße`
    const confirmed = registrations.value.filter((r) => r.status === 'CONFIRMED')
    selectedDiscardIds.value = new Set(confirmed.map((r) => r.id))
    discardError.value = null
    showDiscardModal.value = true
  }

  function toggleAllDiscard() {
    const confirmed = registrations.value.filter((r) => r.status === 'CONFIRMED')
    if (selectedDiscardIds.value.size === confirmed.length) {
      selectedDiscardIds.value = new Set()
    } else {
      selectedDiscardIds.value = new Set(confirmed.map((r) => r.id))
    }
  }

  function toggleDiscardId(id) {
    const next = new Set(selectedDiscardIds.value)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    selectedDiscardIds.value = next
  }

  async function handleDiscardConfirm() {
    discarding.value = true
    try {
      const result = await adminApi.discardUnacknowledged(
        event.value.id,
        [...selectedDiscardIds.value],
        discardMessage.value,
        discardSubject.value,
      )
      showDiscardModal.value = false
      await Promise.all([refreshRegistrations(), refreshEvent()])
      showToast(`${result.discarded_count} Anmeldungen verworfen (${result.discarded_spots} Plätze)`, 'success')
    } catch (err) {
      discardError.value = err.message || 'Fehler beim Verwerfen'
    } finally {
      discarding.value = false
    }
  }

  function handleDeleteRegistration({ registrationId, name }) {
    deleteRegData.value = { registrationId, name }
  }

  async function confirmDeleteRegistration() {
    if (!deleteRegData.value) return
    const { registrationId } = deleteRegData.value
    try {
      await adminApi.deleteRegistration(event.value.id, registrationId)
      await Promise.all([refreshRegistrations(), refreshEvent()])
      deleteRegData.value = null
      showToast('Anmeldung gelöscht', 'success')
    } catch (err) {
      showToast(err.message || 'Fehler beim Löschen', 'error')
    }
  }

  return {
    // Loading states
    publishing, closingRegistration, completing, togglingPromotedId,
    // Clone
    cloneEvent, cloneStartAt, cloning, cloneError, showCloneModal, handleClone,
    // Cancel
    cancelEventData, cancelConfirmation, cancelling, cancelError, showCancelEventModal, handleCancelEvent,
    // Edit
    editEventData, editing, editError, showEditModal, handleEdit,
    // Delete event
    deleteEventData, deleting, deleteError, showDeleteModal, handleDelete,
    // Delete registration
    deleteRegData, handleDeleteRegistration, confirmDeleteRegistration,
    // Capacity warning
    capacityWarning,
    // Messages
    showMessageComposer, showMessageLog,
    // Discard
    showDiscardModal, discardSubject, discardMessage, selectedDiscardIds, discarding, discardError,
    handleDiscardUnacknowledged, toggleAllDiscard, toggleDiscardId, handleDiscardConfirm,
    // Actions
    publishEvent, closeRegistration, completeEvent,
    copyRegistrationLink, copyInviteText, goToLottery,
    handleExportPdf, handleTogglePromoted, handlePromoteWaitlisted,
  }
}
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npx eslint src/composables/useEventActions.js`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/composables/useEventActions.js
git commit -m "feat: extract useEventActions composable from EventsPage"
```

---

## Task 2: Create EventDetailPage

The core of the refactor. This page replaces EventDetailModal with a full page at `/admin/events/:eventId`.

**Files:**
- Create: `frontend/src/pages/admin/EventDetailPage.vue`

- [ ] **Step 1: Create EventDetailPage.vue**

The page has:
- A top bar with back button ("← Events") and event name
- In-page tabs: Details, Anmeldungen, Nachrichten
- Tab content area
- Sticky footer with primary CTA
- All confirmation/edit modals from the old EventsPage

The template reuses existing components: `EventForm`, `RegistrationTable`, `MessageComposer`, `MessageLog`, `HelpPanel`.

Create the full file at `frontend/src/pages/admin/EventDetailPage.vue`. The file is large but self-contained — it owns its data loading and uses `useEventActions` for handlers.

Key patterns:
- `const route = useRoute()` to get `eventId` from params
- Load event via `adminApi.getEvent(eventId)` on mount
- Load registrations via `adminApi.listRegistrations(eventId)` on mount
- `useEventActions({ event, registrations, refreshEvent, refreshRegistrations })`
- Three in-page tabs controlled by `activeTab` ref
- All modals from the old flow (edit, clone, cancel, delete, discard, messages, delete-reg, capacity-warning)
- Sticky footer with status-dependent primary button

- [ ] **Step 2: Build and lint**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npm run build && npm run lint`
Expected: Clean build, no lint errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/admin/EventDetailPage.vue
git commit -m "feat: add EventDetailPage as full-page replacement for EventDetailModal"
```

---

## Task 3: Create SettingsPage

**Files:**
- Create: `frontend/src/pages/admin/SettingsPage.vue`

- [ ] **Step 1: Create SettingsPage.vue**

Contains:
- Push notification toggle (moved from DebugPage)
- Account info section (email, role from Auth0)
- Logout button
- App version / about info

```vue
<template>
  <article class="settings-page">
    <h2>Einstellungen</h2>

    <!-- Push Notifications -->
    <section class="settings-section">
      <h3>Push-Benachrichtigungen</h3>
      <p v-if="!pushSupported" class="muted">
        Push-Benachrichtigungen werden in diesem Browser nicht unterstützt.
      </p>
      <template v-else>
        <button v-if="!pushSubscribed" @click="handleSubscribe" class="outline">
          Benachrichtigungen aktivieren
        </button>
        <button v-else @click="handleUnsubscribe" class="outline secondary">
          Benachrichtigungen deaktivieren
        </button>
      </template>
    </section>

    <!-- Account -->
    <section class="settings-section">
      <h3>Konto</h3>
      <dl class="account-info">
        <dt>E-Mail</dt>
        <dd>{{ user?.email || '–' }}</dd>
      </dl>
    </section>

    <!-- Logout -->
    <section class="settings-section">
      <button @click="handleLogout" class="secondary">Abmelden</button>
    </section>
  </article>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuth0 } from '@auth0/auth0-vue'
import { usePushNotifications } from '../../composables/usePushNotifications.js'
import { showToast } from '../../composables/useToast.js'

const { user, logout } = useAuth0()
const {
  isSubscribed: pushSubscribed,
  isSupported: pushSupported,
  subscribe,
  unsubscribe,
  checkSubscription,
} = usePushNotifications()

onMounted(() => {
  checkSubscription()
})

async function handleSubscribe() {
  try {
    const ok = await subscribe()
    if (ok) {
      showToast('Push-Benachrichtigungen aktiviert', 'success')
    } else {
      showToast('Berechtigung verweigert', 'error')
    }
  } catch (err) {
    showToast(`Fehler: ${err.message}`, 'error')
  }
}

async function handleUnsubscribe() {
  try {
    await unsubscribe()
    showToast('Push-Benachrichtigungen deaktiviert', 'success')
  } catch (err) {
    showToast(`Fehler: ${err.message}`, 'error')
  }
}

function handleLogout() {
  logout({ logoutParams: { returnTo: window.location.origin } })
}
</script>

<style scoped>
.settings-page h2 {
  margin-bottom: 1.5rem;
}

.settings-section {
  margin-bottom: 1.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--color-border, #DFE2E6);
}

.settings-section:last-child {
  border-bottom: none;
}

.settings-section h3 {
  margin-bottom: 0.75rem;
  font-size: 1rem;
}

.muted {
  color: var(--color-text-muted, #5C6470);
  font-size: var(--text-sm);
}

.account-info {
  margin: 0;
}

.account-info dt {
  font-size: var(--text-xs);
  color: var(--color-text-muted, #5C6470);
  margin-bottom: 0.15rem;
}

.account-info dd {
  margin: 0 0 0.75rem;
  font-size: var(--text-sm);
}
</style>
```

- [ ] **Step 2: Lint**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npx eslint src/pages/admin/SettingsPage.vue`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/admin/SettingsPage.vue
git commit -m "feat: add SettingsPage with push notifications and account info"
```

---

## Task 4: Update router

**Files:**
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: Add new routes**

Add these routes to the admin section:

```javascript
{
  path: '/admin/events/:eventId',
  name: 'admin-event-detail',
  component: () => import('../pages/admin/EventDetailPage.vue'),
  beforeEnter: authGuard,
  props: true,
},
{
  path: '/admin/settings',
  name: 'admin-settings',
  component: () => import('../pages/admin/SettingsPage.vue'),
  beforeEnter: authGuard,
},
```

Place the event detail route AFTER `/admin/events` but BEFORE `/admin/events/:eventId/lottery` (the lottery route is more specific with its `/lottery` suffix, but ordering matters for readability).

- [ ] **Step 2: Lint**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npx eslint src/router/index.js`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/router/index.js
git commit -m "feat: add event detail and settings routes"
```

---

## Task 5: Simplify EventsPage

Remove EventDetailModal and all detail-related state. Event name click navigates to the detail page route.

**Files:**
- Modify: `frontend/src/pages/admin/EventsPage.vue`

- [ ] **Step 1: Remove from template**

Remove these template elements:
- The `<EventDetailModal>` component and all its props/events
- The `<dialog>` for cancel event, delete event, clone event, edit event, delete registration, discard unacknowledged, capacity warning, message composer, message log
- Keep ONLY: filter tabs, events table, create event modal, help panel

Change the event name click from `@click.prevent="viewRegistrations(event)"` to:
```html
<router-link :to="`/admin/events/${event.id}`">{{ event.name }}</router-link>
```

- [ ] **Step 2: Remove from script**

Remove these imports:
- `EventDetailModal`
- `RegistrationTable` (if imported here)
- `MessageComposer`
- `MessageLog`

Remove all refs related to:
- `selectedEvent`, `registrations`, `loadingRegistrations`, `registrationsError`
- `publishing`, `closing`, `completing`, `togglingPromotedId`
- `cancelEventData`, `cancelConfirmation`, `cancelling`, `cancelError`
- `editEventData`, `editing`, `editError`
- `deleteEventData`, `deleting`, `deleteError`
- `cloneEvent`, `cloneStartAt`, `cloning`, `cloneError`
- `showMessageComposer`, `showMessageLog`
- `showDiscardModal`, `discardSubject`, `discardMessage`, `selectedDiscardIds`, `discarding`, `discardError`, `discardEventRef`
- `deleteRegData`, `capacityWarning`

Remove all functions:
- `viewRegistrations`, `publishEvent`, `closeRegistration`, `completeEvent`
- `showCloneModal`, `handleClone`, `copyRegistrationLink`, `copyInviteText`
- `goToLottery`, `showCancelEventModal`, `handleCancelEvent`
- `showEditModal`, `handleEdit`, `showDeleteModal`, `handleDelete`
- `handleExportCsv`, `handleTogglePromoted`, `handlePromoteWaitlisted`
- `handleDiscardUnacknowledged`, `toggleAllDiscard`, `toggleDiscardId`, `handleDiscardConfirm`
- `handleDeleteRegistration`, `confirmDeleteRegistration`

Keep: `loadEvents`, `handleCreateEvent`, filter logic, `updateEventInList` (still used by create), `formatters`, `useHelp`, create modal state.

Also keep the `activeHelpKey` computed but simplify it — it only needs to check `showCreateModal` now.

- [ ] **Step 3: Remove unused styles**

Remove styles for elements that no longer exist (modal-specific styles). Keep filter tabs, events table, create modal styles.

- [ ] **Step 4: Build and lint**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npm run build && npm run lint`
Expected: Clean build, no lint errors, no unused import warnings

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/admin/EventsPage.vue
git commit -m "refactor: simplify EventsPage — remove detail modal, navigate to detail page"
```

---

## Task 6: Update App.vue tab bar

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add Settings tab, remove logout from tab bar**

Replace the logout button tab with a Settings tab. Remove the Abmelden tab — logout now lives in SettingsPage.

Update the tab bar to have 3 tabs:
1. **Events** → `/admin/events` (calendar icon)
2. **Einstellungen** → `/admin/settings` (gear icon)
3. **Debug** → `/admin/debug` (code icon)

Update active-state classes:
- Events: active when `route.path.startsWith('/admin/events')`
- Einstellungen: active when `route.path === '/admin/settings'`
- Debug: active when `route.path === '/admin/debug'`

Remove the `handleLogout` function from App.vue (moved to SettingsPage).

- [ ] **Step 2: Remove unused Auth0 imports**

Remove `logout` from the `useAuth0()` destructure since App.vue no longer handles logout.

- [ ] **Step 3: Build and lint**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npm run build && npm run lint`
Expected: Clean build, no lint errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.vue
git commit -m "feat: update tab bar — add Settings tab, remove logout button"
```

---

## Task 7: Clean up DebugPage and delete EventDetailModal

**Files:**
- Modify: `frontend/src/pages/admin/DebugPage.vue`
- Delete: `frontend/src/components/EventDetailModal.vue`

- [ ] **Step 1: Remove push notification section from DebugPage**

Remove the `<section class="push-section">` block from the template.
Remove the `usePushNotifications` import and related functions (`handleSubscribe`, `handleUnsubscribe`).
Remove `checkSubscription()` from `onMounted`.
Remove the `.push-section` CSS.

- [ ] **Step 2: Delete EventDetailModal.vue**

```bash
rm frontend/src/components/EventDetailModal.vue
```

- [ ] **Step 3: Build and lint**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npm run build && npm run lint`
Expected: Clean build, no lint errors. No references to EventDetailModal remain.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove EventDetailModal, move push settings to SettingsPage"
```

---

## Task 8: Final verification

- [ ] **Step 1: Full build**

Run: `cd /Users/arnemohr/git/arnemohr/funke/frontend && npm run build`
Expected: Clean build with no warnings

- [ ] **Step 2: Lint**

Run: `npm run lint`
Expected: No errors

- [ ] **Step 3: Run backend tests (regression check)**

Run: `cd /Users/arnemohr/git/arnemohr/funke/backend && python -m pytest tests/ -q -k "not test_registration_cancelled and not test_format_date_german"`
Expected: All tests pass (no backend changes)

- [ ] **Step 4: Manual smoke test checklist**

Using `npm run preview` in the frontend directory:
1. Open `/admin/events` — event list loads, filter tabs work
2. Click an event name — navigates to `/admin/events/:id`, event detail loads
3. Click "← Events" back button — returns to list
4. On detail page: switch between Details/Anmeldungen/Nachrichten tabs
5. On detail page: click Edit — modal opens, can save
6. On detail page: click primary CTA (publish/close/etc.) — works
7. Bottom tab: tap Events — goes to event list
8. Bottom tab: tap Einstellungen — shows settings page with push toggle and logout
9. Bottom tab: tap Debug — shows debug page (no push section)
10. Tap Einstellungen → Abmelden — logs out

- [ ] **Step 5: Final commit if any fixes needed**

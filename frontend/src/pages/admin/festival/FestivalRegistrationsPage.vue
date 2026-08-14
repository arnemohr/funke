<template>
  <article style="position: relative;">
    <PageHeader :back="`/admin/festival/${eventId}`" back-label="Zurück" :subtitle="event?.name || ''">
      <template #title>Anmeldungen</template>
      <template #actions>
        <button
          type="button"
          class="outline"
          :disabled="loading"
          :aria-busy="loading"
          @click="loadRegistrations"
        >
          Aktualisieren
        </button>
        <button
          type="button"
          :disabled="loading || registrations.length === 0"
          @click="showComposer = true"
        >
          Nachricht senden
        </button>
      </template>
    </PageHeader>

    <FestivalHelp title="Was geht hier?">
      <p>Anmeldungen suchen, absagen oder allen eine Nachricht schicken.</p>
      <p>Tage und Begleitungen ändern die Leute selbst — mit dem Link aus ihrer Bestätigungsmail, bis zum Schluss.</p>
      <p>Wenn du hier absagst, bekommt die Person automatisch eine Mail und ihr Platz auf dem Einladungslink wird wieder frei.</p>
      <p v-if="OVERNIGHT_ENABLED">Sagst du eine Übernachtung zu, geht automatisch eine Mail an die Person, die angemeldet hat. Zusagen von früher holst du mit dem Knopf im Tab „Übernachtungs-Anfragen“ nach.</p>
    </FestivalHelp>

    <!-- Loading -->
    <div v-if="loading && registrations.length === 0" aria-busy="true">
      Anmeldungen werden geladen...
    </div>

    <!-- Error -->
    <div v-else-if="loadError && registrations.length === 0" role="alert" class="error">
      {{ loadError }}
    </div>

    <template v-else>
      <!-- Filter tabs (EventsPage.vue pattern) -->
      <nav class="filter-nav">
        <ul class="filter-tabs">
          <li>
            <a href="#" :class="{ active: statusFilter === 'ALL' }" @click.prevent="statusFilter = 'ALL'">Alle ({{ filterCounts.all }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'ACTIVE' }" @click.prevent="statusFilter = 'ACTIVE'">Angemeldet ({{ filterCounts.active }})</a>
          </li>
          <li v-if="OVERNIGHT_ENABLED">
            <a href="#" :class="{ active: statusFilter === 'OVERNIGHT' }" @click.prevent="statusFilter = 'OVERNIGHT'">Übernachtungs-Anfragen ({{ filterCounts.overnight }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'CANCELLED' }" @click.prevent="statusFilter = 'CANCELLED'">Storniert ({{ filterCounts.cancelled }})</a>
          </li>
        </ul>
      </nav>

      <input
        v-model="search"
        type="search"
        placeholder="Suche nach Name oder E-Mail..."
        class="search-input"
      />

      <!-- F8 catch-up: only in the overnight work queue, where the approvals
           live. Hidden entirely when nobody is waiting for a mail. -->
      <div
        v-if="OVERNIGHT_ENABLED && statusFilter === 'OVERNIGHT' && unnotifiedApprovals.length > 0"
        class="notify-bar"
      >
        <p>
          {{ unnotifiedApprovals.length }}
          {{ unnotifiedApprovals.length === 1 ? 'Zusage hat' : 'Zusagen haben' }}
          noch keine E-Mail bekommen.
        </p>
        <button
          type="button"
          :disabled="notifying"
          :aria-busy="notifying"
          @click="showNotifyDialog = true"
        >
          Zusagen benachrichtigen ({{ unnotifiedApprovals.length }})
        </button>
      </div>

      <!-- Empty state -->
      <p v-if="filteredRegistrations.length === 0" class="empty-hint">
        In dieser Ansicht gibt es gerade keine Anmeldungen.
      </p>

      <div v-else class="table-scroll">
        <table class="mobile-card-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>E-Mail</th>
              <th>Personen</th>
              <th>Tier</th>
              <th>Einladung</th>
              <th v-for="slot in slotColumns" :key="slot.key">{{ slot.label }}</th>
              <th v-if="OVERNIGHT_ENABLED">Schlafplatz</th>
              <th>Telefon</th>
              <th v-if="OVERNIGHT_ENABLED && statusFilter === 'OVERNIGHT'">Übernachtung</th>
              <th>Status</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="reg in filteredRegistrations"
              :key="reg.id"
              :class="{ 'row-muted': reg.status === 'CANCELLED' }"
            >
              <td data-label="Name">
                <strong>{{ reg.name }}</strong>
                <template v-if="companionRows(reg).length > 0">
                  <br />
                  <!-- Spec 020: show which companions are reachable by mail, so
                       organizers know who got their own Eintritts-Code. -->
                  <small
                    v-for="row in companionRows(reg)"
                    :key="row.personIndex"
                    class="companion-row"
                  >
                    + {{ row.name }}<template v-if="row.email"> · {{ row.email }}</template>
                  </small>
                </template>
              </td>
              <td data-label="E-Mail">{{ reg.email }}</td>
              <td data-label="Personen">{{ reg.group_size }}</td>
              <td data-label="Tier">{{ tierLabel(reg.tier) }}</td>
              <td data-label="Einladung">{{ reg.invite_label || '–' }}</td>
              <td
                v-for="slot in slotColumns"
                :key="slot.key"
                :data-label="slot.label"
                class="slot-cell"
              >
                <span v-if="(reg.attendance_slots || []).includes(slot.key)" aria-label="dabei">✓</span>
              </td>
              <td v-if="OVERNIGHT_ENABLED" data-label="Schlafplatz">{{ accommodationLabel(reg) }}</td>
              <td data-label="Telefon">{{ reg.phone || '–' }}</td>
              <td v-if="OVERNIGHT_ENABLED && statusFilter === 'OVERNIGHT'" data-label="Übernachtung">
                <span :class="['chip', overnightChip(reg).cls]">{{ overnightChip(reg).label }}</span>
                <!-- Who already knows: an approval without a mail is still
                     news the group hasn't received. A refusal is only ever
                     recorded together with its mail, so it needs no such line. -->
                <span v-if="reg.overnight_approved" class="notify-state">
                  <template v-if="reg.overnight_notified_at">
                    ✉︎ benachrichtigt {{ formatDateTime(reg.overnight_notified_at) }}
                  </template>
                  <template v-else>⚠︎ noch nicht benachrichtigt</template>
                </span>
                <span v-else-if="reg.overnight_declined_at" class="notify-state">
                  ✉︎ abgelehnt {{ formatDateTime(reg.overnight_declined_at) }}
                </span>
                <button
                  type="button"
                  class="outline overnight-toggle"
                  :disabled="reg.status === 'CANCELLED' || togglingId === reg.id"
                  :aria-busy="togglingId === reg.id"
                  @click="toggleOvernightApproval(reg)"
                >
                  {{ reg.overnight_approved ? 'Zusage zurücknehmen' : 'Darf übernachten' }}
                </button>
                <!-- Refusing is only offered while not approved: the backend
                     rejects the combination outright, so the organizer takes the
                     approval back first. -->
                <button
                  v-if="!reg.overnight_approved"
                  type="button"
                  class="outline overnight-toggle decline-toggle"
                  :disabled="reg.status === 'CANCELLED' || togglingId === reg.id"
                  :aria-busy="togglingId === reg.id"
                  @click="reg.overnight_declined_at ? withdrawDecline(reg) : askDecline(reg)"
                >
                  {{ reg.overnight_declined_at ? 'Ablehnung zurücknehmen' : 'Kann nicht übernachten' }}
                </button>
              </td>
              <td data-label="Status">
                <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                  {{ formatRegistrationStatus(reg.status) }}
                </span>
              </td>
              <td data-label="Aktionen" class="row-actions">
                <router-link
                  :to="`/admin/events/${eventId}/registrations/${reg.id}`"
                  class="outline edit-link"
                >
                  Bearbeiten
                </router-link>
                <button
                  v-if="reg.status !== 'CANCELLED'"
                  type="button"
                  class="outline secondary"
                  @click="askCancel(reg)"
                >
                  Stornieren
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- Admin cancel confirmation dialog (structure copied from RegistrationManagePage.vue) -->
    <dialog :open="showCancelDialog || undefined">
      <article style="max-width: 500px;">
        <header>
          <button @click="closeCancelDialog" aria-label="Schließen" rel="prev"></button>
          <h3>Wirklich stornieren?</h3>
        </header>

        <p class="warning-box">{{ cancelWarningText }}</p>

        <div v-if="cancelError" role="alert" class="error">{{ cancelError }}</div>

        <footer>
          <button @click="closeCancelDialog" class="secondary">Nee, doch nicht</button>
          <button
            @click="confirmCancel"
            :disabled="cancelling"
            :aria-busy="cancelling"
            class="cancel-confirm-btn"
          >
            {{ cancelling ? 'Wird storniert...' : 'Ja, stornieren' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- F9 refusal confirmation — an irreversible-feeling mail to a named
         person, so never on a single click. -->
    <dialog :open="declineTarget !== null || undefined">
      <article style="max-width: 500px;">
        <header>
          <button @click="declineTarget = null" aria-label="Schließen" rel="prev"></button>
          <h3>Übernachtung ablehnen?</h3>
        </header>

        <p v-if="declineTarget">
          <strong>{{ declineTarget.name }}</strong> bekommt eine E-Mail, dass die
          Übernachtung ({{ accommodationLabel(declineTarget) }}) nicht möglich ist.
        </p>
        <p class="notify-hint">
          Die Anmeldung selbst bleibt bestehen — nur der Schlafplatz wird
          abgelehnt. Der Übernachtungswunsch bleibt sichtbar, damit die Zahlen
          weiter zeigen, was angefragt war.
        </p>

        <div v-if="declineError" role="alert" class="error">{{ declineError }}</div>

        <footer>
          <button @click="declineTarget = null" class="secondary">Nee, doch nicht</button>
          <button
            class="cancel-confirm-btn"
            :disabled="declining"
            :aria-busy="declining"
            @click="confirmDecline"
          >
            {{ declining ? 'Wird gesendet...' : 'Ja, ablehnen' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- F8 bulk confirmation — mail goes out to real people, so never on a
         single click (same guard as the cancel dialog above). -->
    <dialog :open="showNotifyDialog || undefined">
      <article style="max-width: 500px;">
        <header>
          <button @click="showNotifyDialog = false" aria-label="Schließen" rel="prev"></button>
          <h3>Zusagen benachrichtigen?</h3>
        </header>

        <p>
          {{ unnotifiedApprovals.length }}
          {{ unnotifiedApprovals.length === 1 ? 'Person' : 'Personen' }}
          bekommen jetzt eine E-Mail, dass ihre Übernachtung zugesagt ist:
        </p>
        <ul class="notify-list">
          <li v-for="reg in unnotifiedApprovals" :key="reg.id">
            {{ reg.name }} <small>({{ accommodationLabel(reg) }})</small>
          </li>
        </ul>
        <p class="notify-hint">
          Wer schon eine Mail bekommen hat, wird übersprungen. Künftige Zusagen
          gehen automatisch raus.
        </p>

        <div v-if="notifyError" role="alert" class="error">{{ notifyError }}</div>

        <footer>
          <button @click="showNotifyDialog = false" class="secondary">Nee, doch nicht</button>
          <button :disabled="notifying" :aria-busy="notifying" @click="confirmNotify">
            {{ notifying ? 'Wird gesendet...' : 'Ja, benachrichtigen' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Template-12 send surface (T211) — reuses the existing composer, no new backend -->
    <MessageComposer
      :open="showComposer"
      :event-id="eventId"
      :registrations="registrations"
      @close="showComposer = false"
      @sent="onMessageSent"
    />
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '../../../services/api'
import { OVERNIGHT_ENABLED } from '../../../config/festival.js'
import PageHeader from '../../../components/PageHeader.vue'
import FestivalHelp from '../../../components/help/FestivalHelp.vue'
import MessageComposer from '../../../components/MessageComposer.vue'
import { showToast } from '../../../composables/useToast.js'
import { formatRegistrationStatus, formatDateTime } from '../../../utils/formatters.js'

const props = defineProps({
  eventId: { type: String, default: null },
})

// State
const loading = ref(true)
const loadError = ref(null)
const event = ref(null)
const registrations = ref([])
const statusFilter = ref('ALL')
const search = ref('')
const showComposer = ref(false)

// Cancel dialog state
const cancelTarget = ref(null)
const cancelling = ref(false)
const cancelError = ref(null)
const showCancelDialog = computed(() => cancelTarget.value !== null)

// Overnight toggle state (Ä17)
const togglingId = ref(null)

// F8 bulk-notify state
const showNotifyDialog = ref(false)
const notifying = ref(false)
const notifyError = ref(null)

// F9 decline state
const declineTarget = ref(null)
const declining = ref(false)
const declineError = ref(null)

// Tier labels — mirrors HeadcountPage.vue / InvitesPage.vue's TIER_LABELS map.
const TIER_LABELS = {
  werft: 'Werft',
  volunteer: 'Helfer:in',
  org: 'Organisation',
  open: 'Offen',
  unknown: 'ohne Tier',
}

function tierLabel(tier) {
  return TIER_LABELS[tier] || tier || '–'
}

// Ä21: a registration may bring tents AND campers — render both counts.
function accommodationLabel(reg) {
  const parts = []
  if (reg.tent_count) parts.push(`${reg.tent_count} ${reg.tent_count === 1 ? 'Zelt' : 'Zelte'}`)
  if (reg.camper_count) parts.push(`${reg.camper_count} Camper`)
  return parts.length ? parts.join(', ') : 'Nein'
}

function hasOvernight(reg) {
  return !!(reg.tent_count || reg.camper_count)
}

// Three answers to one wish (Ä17 + F9). `overnight_approved` and
// `overnight_declined_at` are mutually exclusive server-side, so approved wins
// here only as belt-and-braces.
function overnightChip(reg) {
  if (reg.overnight_approved) return { label: 'zugesagt', cls: 'chip-success' }
  if (reg.overnight_declined_at) return { label: 'abgelehnt', cls: 'chip-declined' }
  return { label: 'angefragt', cls: 'chip-warn' }
}

// group_members is EXCLUSIVE of the contact and may contain `null` tombstones
// for removed companions (T109 append-only rule) — skip them when stacking.
function companions(reg) {
  return (reg.group_members || []).filter((m) => m !== null && m !== undefined)
}

// Spec 020 — companions paired with their own address, indices preserved.
// group_member_emails[i] belongs to group_members[i], so pair BEFORE filtering
// tombstones; filtering first would shift the addresses onto the wrong people.
function companionRows(reg) {
  const emails = reg.group_member_emails || []
  return (reg.group_members || [])
    .map((name, idx) => ({ name, email: emails[idx] || null, personIndex: idx + 1 }))
    .filter((row) => row.name !== null && row.name !== undefined)
}

// Slot columns in the event's own festival_slots order (not attendance_slots' order).
const slotColumns = computed(() => event.value?.festival_slots || [])

const filterCounts = computed(() => {
  const all = registrations.value
  return {
    all: all.length,
    active: all.filter((r) => r.status !== 'CANCELLED').length,
    overnight: all.filter(hasOvernight).length,
    cancelled: all.filter((r) => r.status === 'CANCELLED').length,
  }
})

// F8: approved groups that still owe a mail. Deliberately computed from ALL
// registrations, not the filtered view — the search box must not shrink what
// the bulk button will send, or the count would lie.
const unnotifiedApprovals = computed(() =>
  registrations.value.filter(
    (r) => r.overnight_approved && !r.overnight_notified_at && r.status !== 'CANCELLED',
  ),
)

const filteredRegistrations = computed(() => {
  let list = registrations.value

  if (statusFilter.value === 'ACTIVE') {
    list = list.filter((r) => r.status !== 'CANCELLED')
  } else if (statusFilter.value === 'OVERNIGHT') {
    list = list.filter(hasOvernight)
  } else if (statusFilter.value === 'CANCELLED') {
    list = list.filter((r) => r.status === 'CANCELLED')
  }

  const query = search.value.trim().toLowerCase()
  if (query) {
    list = list.filter(
      (r) => r.name.toLowerCase().includes(query) || r.email.toLowerCase().includes(query),
    )
  }

  // Ä17: within the Übernachtungs-Anfragen view, still-open requests sort
  // first — that's the organizers' work queue. Answered ones (refused, then
  // approved) sink below, since they need no further decision.
  if (statusFilter.value === 'OVERNIGHT') {
    const rank = (r) => (r.overnight_approved ? 2 : r.overnight_declined_at ? 1 : 0)
    list = [...list].sort((a, b) => rank(a) - rank(b))
  }

  return list
})

// Shared fetch, reused by the initial (blocking) load and by silent reloads
// after an action — a reload must never re-trigger the full-page spinner.
async function fetchData() {
  const [eventResult, regResult] = await Promise.all([
    adminApi.festival.getEvent(props.eventId),
    adminApi.festival.listRegistrations(props.eventId),
  ])
  event.value = eventResult
  registrations.value = regResult.items
}

async function loadRegistrations() {
  loading.value = true
  loadError.value = null
  try {
    await fetchData()
  } catch (err) {
    loadError.value = err.message || 'Anmeldungen konnten nicht geladen werden'
    showToast(loadError.value, 'error')
  } finally {
    loading.value = false
  }
}

async function reloadRegistrations() {
  try {
    await fetchData()
  } catch (err) {
    showToast(err.message || 'Aktualisieren fehlgeschlagen', 'error')
  }
}

function askCancel(reg) {
  cancelTarget.value = reg
  cancelError.value = null
}

function closeCancelDialog() {
  cancelTarget.value = null
  cancelError.value = null
}

const cancelWarningText = computed(() => {
  if (!cancelTarget.value) return ''
  const name = cancelTarget.value.name
  const n = companions(cancelTarget.value).length
  const lead =
    n === 0
      ? `${name} wird storniert.`
      : n === 1
        ? `${name} und 1 Begleitung werden storniert.`
        : `${name} und ${n} Begleitungen werden storniert.`
  return `${lead} Der Einladungs-Platz wird wieder frei. Die Person bekommt eine Absage-Mail.`
})

async function confirmCancel() {
  if (!cancelTarget.value) return
  cancelling.value = true
  cancelError.value = null
  try {
    await adminApi.festival.cancelRegistration(props.eventId, cancelTarget.value.id)
    showToast('Anmeldung storniert', 'success')
    cancelTarget.value = null
    await reloadRegistrations()
  } catch (err) {
    cancelError.value = err.message || 'Stornierung fehlgeschlagen'
    showToast(cancelError.value, 'error')
  } finally {
    cancelling.value = false
  }
}

// Ä17: the only write path for overnight_approved is the spec-018 admin
// patch (T205/T206) — no dedicated endpoint. Approving also sends F8; the
// toast reports what actually happened by reading the stamp off the response
// rather than promising a mail the backend may have failed to queue.
async function toggleOvernightApproval(reg) {
  const wasApproved = reg.overnight_approved
  togglingId.value = reg.id
  try {
    const updated = await adminApi.festival.updateRegistration(props.eventId, reg.id, {
      overnight_approved: !wasApproved,
    })
    if (wasApproved) {
      showToast('Zusage zurückgenommen', 'success')
    } else if (updated?.overnight_notified_at) {
      showToast('Übernachtung zugesagt — E-Mail ist raus', 'success')
    } else {
      // 'error' (not 'info'): the approval is saved but the guest doesn't know
      // it yet, and that needs the organizer's attention — the bulk button
      // below is the retry.
      showToast('Übernachtung zugesagt, aber die E-Mail ging nicht raus', 'error')
    }
    await reloadRegistrations()
  } catch (err) {
    showToast(err.message || 'Aktualisieren fehlgeschlagen', 'error')
  } finally {
    togglingId.value = null
  }
}

function askDecline(reg) {
  declineTarget.value = reg
  declineError.value = null
}

// F9: refuse the wish and mail the guest. The stamp is claimed server-side
// before the mail goes out, so a double click cannot mail twice.
async function confirmDecline() {
  const reg = declineTarget.value
  if (!reg) return
  declining.value = true
  declineError.value = null
  try {
    const updated = await adminApi.festival.updateRegistration(props.eventId, reg.id, {
      overnight_declined: true,
    })
    declineTarget.value = null
    if (updated?.overnight_declined_at) {
      showToast('Übernachtung abgelehnt — E-Mail ist raus', 'success')
    } else {
      showToast('Ablehnung gespeichert, aber die E-Mail ging nicht raus', 'error')
    }
    await reloadRegistrations()
  } catch (err) {
    declineError.value = err.message || 'Ablehnen fehlgeschlagen'
    showToast(declineError.value, 'error')
  } finally {
    declining.value = false
  }
}

// Undoing a refusal puts the request back to „angefragt" and mails nothing —
// there is no news to deliver, and the organizer usually follows up by phone.
async function withdrawDecline(reg) {
  togglingId.value = reg.id
  try {
    await adminApi.festival.updateRegistration(props.eventId, reg.id, {
      overnight_declined: false,
    })
    showToast('Ablehnung zurückgenommen', 'success')
    await reloadRegistrations()
  } catch (err) {
    showToast(err.message || 'Aktualisieren fehlgeschlagen', 'error')
  } finally {
    togglingId.value = null
  }
}

// F8 catch-up for approvals granted before the automatic mail existed (and a
// retry for failed sends). Idempotent server-side, so a double click is safe.
async function confirmNotify() {
  notifying.value = true
  notifyError.value = null
  try {
    const result = await adminApi.festival.notifyOvernightApprovals(props.eventId)
    showNotifyDialog.value = false
    const parts = [`${result.sent} benachrichtigt`]
    if (result.skipped) parts.push(`${result.skipped} übersprungen`)
    if (result.failed) parts.push(`${result.failed} fehlgeschlagen`)
    showToast(parts.join(', '), result.failed ? 'error' : 'success')
    await reloadRegistrations()
  } catch (err) {
    notifyError.value = err.message || 'Benachrichtigen fehlgeschlagen'
    showToast(notifyError.value, 'error')
  } finally {
    notifying.value = false
  }
}

function onMessageSent() {
  showComposer.value = false
}

onMounted(loadRegistrations)
</script>

<style scoped>
/* Spec 020 — one line per companion so name and address stay paired. */
.companion-row {
  display: block;
}

.error {
  color: var(--color-danger-text);
  padding: 1rem;
  background: var(--color-danger-bg);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.filter-nav {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 1rem;
}

.filter-tabs {
  display: flex;
  gap: 0.5rem;
  white-space: nowrap;
  list-style: none;
  padding: 0 2rem 2px 0;
  margin: 0;
}

.filter-tabs a {
  white-space: nowrap;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 0.875rem;
  text-decoration: none;
  border-radius: var(--pico-border-radius);
}

.filter-tabs a.active {
  background: var(--pico-primary);
  color: white;
}

.search-input {
  margin-bottom: 1rem;
}

.empty-hint {
  text-align: center;
  padding: 2rem;
  color: var(--color-text-muted);
}

.table-scroll {
  overflow-x: auto;
  margin-bottom: 1.5rem;
}

.slot-cell {
  text-align: center;
}

.row-muted {
  opacity: 0.6;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.row-actions button,
.row-actions .edit-link {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.edit-link {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  padding: 0.4rem 0.7rem;
  border-radius: var(--pico-border-radius);
}

/* Two answers stacked, deliberately small: they sit inside a table cell next to
   the status chip, and at full button size they dominated the row. `fit-content`
   rather than `auto` — a block-level button with `auto` stretches to the cell
   width in some browsers, which is what made them look like one wide block. */
.overnight-toggle {
  display: block;
  width: fit-content;
  margin-top: 0.3rem;
  padding: 0.2rem 0.55rem;
  font-size: var(--text-sm);
  line-height: 1.3;
  min-height: 0;
}

/* F8 notification state — a quiet second line under the zugesagt/angefragt
   chip, never competing with it for attention. */
.notify-state {
  display: block;
  margin-top: 0.2rem;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

.notify-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border-radius: var(--pico-border-radius);
}

.notify-bar p {
  margin: 0;
  font-size: 0.9em;
}

.notify-bar button {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.notify-list {
  max-height: 12rem;
  overflow-y: auto;
  margin-bottom: 0.75rem;
}

.notify-hint {
  font-size: 0.85em;
  color: var(--color-text-muted);
}

.chip {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.chip-warn {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
}

.chip-success {
  background: var(--color-success-bg);
  color: var(--color-success-text);
}

/* Refused: a settled answer, not an alarm — muted rather than red, so the
   still-open requests above it keep the organizer's attention. */
.chip-declined {
  background: var(--color-surface-muted, #e5e7eb);
  color: var(--color-text-muted);
}

.decline-toggle {
  --pico-primary: #6b7280;
}

.warning-box {
  background: var(--color-warning-bg);
  padding: 0.75rem;
  border-radius: var(--pico-border-radius);
  color: var(--color-warning-text);
  font-size: 0.9em;
}

.cancel-confirm-btn {
  --pico-primary: #dc2626;
  --pico-primary-hover: #b91c1c;
  --pico-primary-focus: rgba(220, 38, 38, 0.25);
}

@media (max-width: 640px) {
  tbody td[data-label="Status"]::before {
    display: none;
  }
}
</style>

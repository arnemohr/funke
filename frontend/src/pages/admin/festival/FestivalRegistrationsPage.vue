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
                <template v-if="companions(reg).length > 0">
                  <br />
                  <small>+ {{ companions(reg).join(', ') }}</small>
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
              <td v-if="OVERNIGHT_ENABLED" data-label="Schlafplatz">{{ accommodationLabel(reg.accommodation) }}</td>
              <td data-label="Telefon">{{ reg.phone || '–' }}</td>
              <td v-if="OVERNIGHT_ENABLED && statusFilter === 'OVERNIGHT'" data-label="Übernachtung">
                <span :class="['chip', reg.overnight_approved ? 'chip-success' : 'chip-warn']">
                  {{ reg.overnight_approved ? 'zugesagt' : 'angefragt' }}
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
import { formatRegistrationStatus } from '../../../utils/formatters.js'

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

function accommodationLabel(accommodation) {
  if (accommodation === 'TENT') return 'Zelt'
  if (accommodation === 'CAMPER') return 'Camper'
  return 'Nein'
}

// group_members is EXCLUSIVE of the contact and may contain `null` tombstones
// for removed companions (T109 append-only rule) — skip them when stacking.
function companions(reg) {
  return (reg.group_members || []).filter((m) => m !== null && m !== undefined)
}

// Slot columns in the event's own festival_slots order (not attendance_slots' order).
const slotColumns = computed(() => event.value?.festival_slots || [])

const filterCounts = computed(() => {
  const all = registrations.value
  return {
    all: all.length,
    active: all.filter((r) => r.status !== 'CANCELLED').length,
    overnight: all.filter((r) => !!r.accommodation).length,
    cancelled: all.filter((r) => r.status === 'CANCELLED').length,
  }
})

const filteredRegistrations = computed(() => {
  let list = registrations.value

  if (statusFilter.value === 'ACTIVE') {
    list = list.filter((r) => r.status !== 'CANCELLED')
  } else if (statusFilter.value === 'OVERNIGHT') {
    list = list.filter((r) => !!r.accommodation)
  } else if (statusFilter.value === 'CANCELLED') {
    list = list.filter((r) => r.status === 'CANCELLED')
  }

  const query = search.value.trim().toLowerCase()
  if (query) {
    list = list.filter(
      (r) => r.name.toLowerCase().includes(query) || r.email.toLowerCase().includes(query),
    )
  }

  // Ä17: within the Übernachtungs-Anfragen view, pending ("angefragt") rows
  // sort before approved ("zugesagt") ones — that's the organizers' work queue.
  if (statusFilter.value === 'OVERNIGHT') {
    list = [...list].sort((a, b) => Number(a.overnight_approved) - Number(b.overnight_approved))
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
// patch (T205/T206) — no dedicated endpoint.
async function toggleOvernightApproval(reg) {
  const wasApproved = reg.overnight_approved
  togglingId.value = reg.id
  try {
    await adminApi.festival.updateRegistration(props.eventId, reg.id, {
      overnight_approved: !wasApproved,
    })
    showToast(wasApproved ? 'Zusage zurückgenommen' : 'Übernachtung zugesagt', 'success')
    await reloadRegistrations()
  } catch (err) {
    showToast(err.message || 'Aktualisieren fehlgeschlagen', 'error')
  } finally {
    togglingId.value = null
  }
}

function onMessageSent() {
  showComposer.value = false
}

onMounted(loadRegistrations)
</script>

<style scoped>
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

.overnight-toggle {
  display: block;
  margin-top: 0.35rem;
  width: auto;
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

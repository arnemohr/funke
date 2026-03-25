<template>
  <article>
    <header>
      <hgroup>
        <h2>Veranstaltungen</h2>
        <p>Verwalte deine Veranstaltungen</p>
      </hgroup>
      <button v-if="!accessDenied" @click="showCreateModal = true">Neue Veranstaltung</button>
    </header>

    <!-- Loading state -->
    <div v-if="loading" aria-busy="true">
      Veranstaltungen werden geladen...
    </div>

    <!-- Access Denied state -->
    <div v-else-if="accessDenied" class="access-denied">
      <h3>Zugriff verweigert</h3>
      <p>{{ error }}</p>
      <p>Falls du denkst, dass das ein Fehler ist, melde dich bei uns.</p>
      <button @click="logout" class="secondary">Abmelden</button>
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="error">
      {{ error }}
    </div>

    <!-- Events list -->
    <template v-else>
      <!-- Filter tabs -->
      <nav>
        <ul>
          <li>
            <a href="#" :class="{ active: statusFilter === null }" @click.prevent="statusFilter = null">Alle</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'DRAFT' }" @click.prevent="statusFilter = 'DRAFT'">Entwurf</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'OPEN' }" @click.prevent="statusFilter = 'OPEN'">Offen</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'IN_PROGRESS' }" @click.prevent="statusFilter = 'IN_PROGRESS'">In Bearbeitung</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'COMPLETED' }" @click.prevent="statusFilter = 'COMPLETED'">Abgeschlossen</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'CANCELLED' }" @click.prevent="statusFilter = 'CANCELLED'">Abgesagt</a>
          </li>
        </ul>
      </nav>

      <!-- Empty state -->
      <p v-if="filteredEvents.length === 0">
        Noch keine Veranstaltungen. Leg los und erstelle deine erste!
      </p>

      <!-- Events table -->
      <table v-else>
        <thead>
          <tr>
            <th>Veranstaltung</th>
            <th>Datum</th>
            <th>Status</th>
            <th>Anmeldungen</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="event in filteredEvents" :key="event.id">
            <td>
              <a href="#" @click.prevent="viewRegistrations(event)">
                <strong>{{ event.name }}</strong>
              </a>
              <br />
              <small>{{ event.location || 'Kein Ort angegeben' }}</small>
            </td>
            <td>{{ formatDate(event.start_at) }}</td>
            <td>
              <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
                {{ event.status }}
              </span>
            </td>
            <td>
              {{ event.registration_spots }} Pers. ({{ event.registration_count }}) · {{ event.confirmed_spots }} Best. / {{ event.capacity }}
              <span v-if="event.waitlist_count"> (+{{ event.waitlist_spots }} WL)</span>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- Create Event Modal -->
    <dialog :open="showCreateModal">
      <article class="modal-wide">
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="showCreateModal = false" />
          <h3>Neue Veranstaltung</h3>
        </header>
        <EventForm
          :disabled="creating"
          :error="createError"
          submit-label="Erstellen"
          submit-busy-label="Wird erstellt..."
          @submit="handleCreate"
          @cancel="showCreateModal = false"
        />
      </article>
    </dialog>

    <!-- Edit Event Modal -->
    <dialog :open="editEventData !== null">
      <article class="modal-wide">
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="editEventData = null" />
          <h3>Veranstaltung bearbeiten</h3>
        </header>
        <EventForm
          :event="editEventData"
          :disabled="editing"
          :error="editError"
          submit-label="Speichern"
          submit-busy-label="Wird gespeichert..."
          @submit="handleEdit"
          @cancel="editEventData = null"
        />
      </article>
    </dialog>

    <!-- Clone Event Modal -->
    <dialog :open="cloneEvent !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="cloneEvent = null" />
          <h3>Veranstaltung duplizieren</h3>
        </header>
        <p>Erstelle eine Kopie von "{{ cloneEvent?.name }}" mit neuem Datum.</p>
        <form @submit.prevent="handleClone">
          <label for="cloneStartAt">
            Neues Datum & Uhrzeit *
            <input id="cloneStartAt" v-model="cloneStartAt" type="datetime-local" required :disabled="cloning" />
          </label>
          <div v-if="cloneError" role="alert" class="error">{{ cloneError }}</div>
          <footer>
            <button type="button" class="secondary" @click="cloneEvent = null" :disabled="cloning">Abbrechen</button>
            <button type="submit" :disabled="cloning" :aria-busy="cloning">
              {{ cloning ? 'Wird dupliziert...' : 'Duplizieren' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Event Detail Modal (registrations + actions) -->
    <EventDetailModal
      :event="selectedEvent"
      :registrations="registrations"
      :loading="loadingRegistrations"
      :error="registrationsError"
      :publishing="publishing === selectedEvent?.id"
      :closing-registration="closing === selectedEvent?.id"
      :completing="completing === selectedEvent?.id"
      :toggling-id="togglingPromotedId"
      @close="selectedEvent = null"
      @edit="showEditModal"
      @publish="publishEvent"
      @clone="showCloneModal"
      @cancel-event="showCancelEventModal"
      @delete="showDeleteModal"
      @close-registration="closeRegistration"
      @copy-link="copyRegistrationLink"
      @go-to-lottery="goToLottery"
      @complete-event="completeEvent"
      @export-csv="handleExportCsv"
      @send-message="showMessageComposer = true"
      @show-messages="showMessageLog = true"
      @toggle-promoted="handleTogglePromoted"
      @promote-waitlisted="handlePromoteWaitlisted"
      @discard-unacknowledged="handleDiscardUnacknowledged"
    />

    <!-- Cancel Event Confirmation Modal -->
    <dialog :open="cancelEventData !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="cancelEventData = null" />
          <h3>Veranstaltung absagen</h3>
        </header>
        <div class="cancel-warning">
          <p><strong>Achtung:</strong> Diese Aktion kann nicht rückgängig gemacht werden.</p>
          <p>Wenn du "{{ cancelEventData?.name }}" absagst:</p>
          <ul>
            <li>Wird der Status auf ABGESAGT gesetzt</li>
            <li>Werden alle Angemeldeten benachrichtigt</li>
            <li>Sind keine weiteren Anmeldungen möglich</li>
          </ul>
        </div>
        <form @submit.prevent="handleCancelEvent">
          <label for="cancelConfirmation">
            Tippe <strong>absagen</strong> zur Bestätigung:
            <input id="cancelConfirmation" v-model="cancelConfirmation" type="text" placeholder="absagen" autocomplete="off" :disabled="cancelling" />
          </label>
          <div v-if="cancelError" role="alert" class="error">{{ cancelError }}</div>
          <footer>
            <button type="button" class="secondary" @click="cancelEventData = null" :disabled="cancelling">Zurück</button>
            <button type="submit" class="cancel-confirm-btn" :disabled="cancelConfirmation !== 'absagen' || cancelling" :aria-busy="cancelling">
              {{ cancelling ? 'Wird abgesagt...' : 'Absage bestätigen' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Delete Event Confirmation Modal -->
    <dialog :open="deleteEventData !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="deleteEventData = null" />
          <h3>Veranstaltung löschen</h3>
        </header>
        <p>Möchtest du "{{ deleteEventData?.name }}" wirklich endgültig löschen?</p>
        <p><small>Diese Aktion kann nicht rückgängig gemacht werden.</small></p>
        <div v-if="deleteError" role="alert" class="error">{{ deleteError }}</div>
        <footer>
          <button type="button" class="secondary" @click="deleteEventData = null" :disabled="deleting">Abbrechen</button>
          <button @click="handleDelete" class="delete-btn" :disabled="deleting" :aria-busy="deleting">
            {{ deleting ? 'Wird gelöscht...' : 'Löschen' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Message Composer -->
    <MessageComposer
      :open="showMessageComposer"
      :event-id="selectedEvent?.id"
      :registrations="registrations"
      @close="showMessageComposer = false"
      @sent="onMessageSent"
    />

    <!-- Message Log -->
    <MessageLog
      :open="showMessageLog"
      :event-id="selectedEvent?.id"
      @close="showMessageLog = false"
    />

    <!-- Capacity Warning Popup -->
    <dialog :open="!!capacityWarning">
      <article v-if="capacityWarning">
        <header>
          <button aria-label="Schließen" rel="prev" @click="capacityWarning = null"></button>
          <h3>Kapazität überschritten</h3>
        </header>
        <p>
          <strong>{{ capacityWarning.name }}</strong> benötigt {{ capacityWarning.needed }}
          {{ capacityWarning.needed === 1 ? 'Platz' : 'Plätze' }}, aber nur
          {{ capacityWarning.remaining <= 0 ? 'keine' : capacityWarning.remaining }}
          {{ capacityWarning.remaining === 1 ? 'Platz ist' : 'Plätze sind' }} frei.
        </p>
        <footer>
          <button @click="capacityWarning = null">Verstanden</button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth0 } from '@auth0/auth0-vue'
import { adminApi } from '../../services/api'
import EventForm from '../../components/EventForm.vue'
import EventDetailModal from '../../components/EventDetailModal.vue'
import MessageComposer from '../../components/MessageComposer.vue'
import MessageLog from '../../components/MessageLog.vue'

const router = useRouter()
const { logout: auth0Logout } = useAuth0()

// Core state
const loading = ref(true)
const error = ref(null)
const accessDenied = ref(false)
const events = ref([])
const statusFilter = ref(null)

// Create modal
const showCreateModal = ref(false)
const creating = ref(false)
const createError = ref(null)

// Clone modal
const cloneEvent = ref(null)
const cloneStartAt = ref('')
const cloning = ref(false)
const cloneError = ref(null)

// Action states
const publishing = ref(null)
const closing = ref(null)
const completing = ref(null)

// Registrations / detail modal
const selectedEvent = ref(null)
const registrations = ref([])
const loadingRegistrations = ref(false)
const registrationsError = ref(null)

// Cancel event modal
const cancelEventData = ref(null)
const cancelConfirmation = ref('')
const cancelling = ref(false)
const cancelError = ref(null)

// Edit event modal
const editEventData = ref(null)
const editing = ref(false)
const editError = ref(null)

// Delete event modal
const deleteEventData = ref(null)
const deleting = ref(false)
const deleteError = ref(null)

// Messaging
const showMessageComposer = ref(false)
const showMessageLog = ref(false)

// Promoted toggle
const togglingPromotedId = ref(null)

// Discard unacknowledged
const discardPreview = ref(null)
const discarding = ref(false)

// Capacity warning popup
const capacityWarning = ref(null)

// Computed
const IN_PROGRESS_STATUSES = ['REGISTRATION_CLOSED', 'LOTTERY_PENDING', 'CONFIRMED']

const filteredEvents = computed(() => {
  if (!statusFilter.value) return events.value
  if (statusFilter.value === 'IN_PROGRESS') {
    return events.value.filter(e => IN_PROGRESS_STATUSES.includes(e.status))
  }
  return events.value.filter(e => e.status === statusFilter.value)
})

// Helpers
function formatDate(dateStr) {
  if (!dateStr) return 'Noch offen'
  return new Date(dateStr).toLocaleDateString('de-DE', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function logout() {
  auth0Logout({ logoutParams: { returnTo: window.location.origin } })
}

function updateEventInList(updated) {
  const index = events.value.findIndex(e => e.id === updated.id)
  if (index !== -1) events.value[index] = updated
  if (selectedEvent.value?.id === updated.id) selectedEvent.value = updated
}

// API actions
async function loadEvents() {
  loading.value = true
  error.value = null
  accessDenied.value = false
  try {
    const result = await adminApi.listEvents()
    events.value = result.items
  } catch (err) {
    const message = err.message || 'Veranstaltungen konnten nicht geladen werden'
    error.value = message
    if (message.includes('Access denied') || message.includes('403')) accessDenied.value = true
  } finally {
    loading.value = false
  }
}

async function handleCreate(formData) {
  creating.value = true
  createError.value = null
  try {
    const newEvent = await adminApi.createEvent(formData)
    events.value.unshift(newEvent)
    showCreateModal.value = false
  } catch (err) {
    createError.value = err.message || 'Erstellen fehlgeschlagen'
  } finally {
    creating.value = false
  }
}

async function publishEvent(event) {
  publishing.value = event.id
  try {
    updateEventInList(await adminApi.publishEvent(event.id))
  } catch (err) {
    alert(err.message || 'Veröffentlichung fehlgeschlagen')
  } finally {
    publishing.value = null
  }
}

async function closeRegistration(event) {
  closing.value = event.id
  try {
    updateEventInList(await adminApi.closeRegistration(event.id))
  } catch (err) {
    alert(err.message || 'Anmeldung konnte nicht geschlossen werden')
  } finally {
    closing.value = null
  }
}

async function completeEvent(event) {
  completing.value = event.id
  try {
    updateEventInList(await adminApi.completeEvent(event.id))
  } catch (err) {
    alert(err.message || 'Abschließen fehlgeschlagen')
  } finally {
    completing.value = null
  }
}

function showCloneModal(event) {
  cloneEvent.value = event
  cloneStartAt.value = ''
  cloneError.value = null
}

async function handleClone() {
  cloning.value = true
  cloneError.value = null
  try {
    events.value.unshift(await adminApi.cloneEvent(cloneEvent.value.id, new Date(cloneStartAt.value).toISOString()))
    cloneEvent.value = null
  } catch (err) {
    cloneError.value = err.message || 'Duplizieren fehlgeschlagen'
  } finally {
    cloning.value = false
  }
}

function copyRegistrationLink(event) {
  const link = `${window.location.origin}/register/${event.registration_link_token}`
  navigator.clipboard.writeText(link).then(
    () => alert('Anmeldelink wurde kopiert!'),
    () => prompt('Kopiere diesen Link:', link),
  )
}

function goToLottery(event) {
  router.push({ name: 'admin-event-lottery', params: { eventId: event.id } })
}

async function viewRegistrations(event) {
  selectedEvent.value = event
  loadingRegistrations.value = true
  registrationsError.value = null
  registrations.value = []
  try {
    registrations.value = (await adminApi.listRegistrations(event.id)).items
  } catch (err) {
    registrationsError.value = err.message || 'Anmeldungen konnten nicht geladen werden'
  } finally {
    loadingRegistrations.value = false
  }
}

function showCancelEventModal(event) {
  cancelEventData.value = event
  cancelConfirmation.value = ''
  cancelError.value = null
}

async function handleCancelEvent() {
  if (cancelConfirmation.value !== 'absagen') return
  cancelling.value = true
  cancelError.value = null
  try {
    const updated = await adminApi.cancelEvent(cancelEventData.value.id)
    updateEventInList(updated)
    cancelEventData.value = null
    selectedEvent.value = null
  } catch (err) {
    cancelError.value = err.message || 'Absage fehlgeschlagen'
  } finally {
    cancelling.value = false
  }
}

function showEditModal(event) {
  selectedEvent.value = null
  editEventData.value = event
  editError.value = null
}

async function handleEdit(formData) {
  editing.value = true
  editError.value = null
  try {
    updateEventInList(await adminApi.updateEvent(editEventData.value.id, formData))
    editEventData.value = null
  } catch (err) {
    editError.value = err.message || 'Änderungen konnten nicht gespeichert werden'
  } finally {
    editing.value = false
  }
}

function showDeleteModal(event) {
  deleteEventData.value = event
  deleteError.value = null
}

async function handleDelete() {
  deleting.value = true
  deleteError.value = null
  try {
    await adminApi.deleteEvent(deleteEventData.value.id)
    events.value = events.value.filter(e => e.id !== deleteEventData.value.id)
    deleteEventData.value = null
    selectedEvent.value = null
  } catch (err) {
    deleteError.value = err.message || 'Veranstaltung konnte nicht gelöscht werden'
  } finally {
    deleting.value = false
  }
}

async function handleExportCsv(event) {
  try {
    await adminApi.exportRegistrationsCsv(event.id)
  } catch (err) {
    alert(err.message || 'CSV Export fehlgeschlagen')
  }
}

function onMessageSent() {
  // Optionally refresh registrations after message sent
}

async function handleTogglePromoted({ registrationId, promoted }) {
  if (!selectedEvent.value) return
  togglingPromotedId.value = registrationId
  try {
    await adminApi.togglePromoted(selectedEvent.value.id, registrationId, promoted)
    // Refresh registrations and event
    const [regs, evt] = await Promise.all([
      adminApi.listRegistrations(selectedEvent.value.id),
      adminApi.getEvent(selectedEvent.value.id),
    ])
    registrations.value = regs.items
    updateEventInList(evt)
  } catch (err) {
    alert(err.message || 'Bevorzugung konnte nicht geändert werden')
  } finally {
    togglingPromotedId.value = null
  }
}

async function handlePromoteWaitlisted({ registrationId, targetStatus }) {
  if (!selectedEvent.value) return

  // Check capacity before promoting
  const reg = registrations.value.find(r => r.id === registrationId)
  if (reg) {
    const confirmedSpots = registrations.value
      .filter(r => ['CONFIRMED', 'PARTICIPATING'].includes(r.status))
      .reduce((sum, r) => sum + r.group_size, 0)
    const remaining = selectedEvent.value.capacity - confirmedSpots
    if (reg.group_size > remaining) {
      capacityWarning.value = {
        needed: reg.group_size,
        remaining,
        name: reg.name,
      }
      return
    }
  }

  try {
    await adminApi.promoteFromWaitlist(selectedEvent.value.id, registrationId, targetStatus)
    // Refresh registrations and event
    const [regs, evt] = await Promise.all([
      adminApi.listRegistrations(selectedEvent.value.id),
      adminApi.getEvent(selectedEvent.value.id),
    ])
    registrations.value = regs.items
    updateEventInList(evt)
  } catch (err) {
    alert(err.message || 'Nachrücken fehlgeschlagen')
  }
}

async function handleDiscardUnacknowledged(event) {
  if (!confirm('Alle unbestätigten Anmeldungen verwerfen und benachrichtigen? Diese Aktion kann nicht rückgängig gemacht werden.')) {
    return
  }
  discarding.value = true
  try {
    const result = await adminApi.discardUnacknowledged(event.id)
    alert(`${result.discarded_count} Anmeldungen verworfen (${result.discarded_spots} Plätze).`)
    // Refresh
    const [regs, evt] = await Promise.all([
      adminApi.listRegistrations(event.id),
      adminApi.getEvent(event.id),
    ])
    registrations.value = regs.items
    updateEventInList(evt)
  } catch (err) {
    alert(err.message || 'Verwerfen fehlgeschlagen')
  } finally {
    discarding.value = false
  }
}

watch(statusFilter, loadEvents)
onMounted(loadEvents)
</script>

<style scoped>
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

nav ul {
  list-style: none;
  padding: 0;
  display: flex;
  gap: 1rem;
  margin-bottom: 1rem;
}

nav a {
  text-decoration: none;
  padding: 0.5rem 1rem;
  border-radius: var(--pico-border-radius);
}

nav a.active {
  background: var(--pico-primary);
  color: white;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.75rem;
  font-weight: bold;
  text-transform: uppercase;
}

.status-draft { background: #e2e8f0; color: #64748b; }
.status-open { background: #dcfce7; color: #16a34a; }
.status-registration_closed { background: #fef3c7; color: #d97706; }
.status-lottery_pending { background: #ede9fe; color: #7c3aed; }
.status-confirmed { background: #d1fae5; color: #065f46; }
.status-completed { background: #dbeafe; color: #2563eb; }
.status-cancelled { background: #fee2e2; color: #dc2626; }

dialog article { max-width: 600px; }
dialog article.modal-wide { max-width: 750px; }

dialog footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.cancel-warning {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--pico-border-radius);
  padding: 1rem;
  margin-bottom: 1rem;
}

.cancel-warning p { margin-bottom: 0.5rem; }
.cancel-warning ul { margin: 0.5rem 0 0 1.5rem; padding: 0; }

.cancel-confirm-btn { background: #dc2626 !important; border-color: #dc2626 !important; }
.cancel-confirm-btn:hover:not(:disabled) { background: #b91c1c !important; border-color: #b91c1c !important; }
.cancel-confirm-btn:disabled { background: #fca5a5 !important; border-color: #fca5a5 !important; }

.delete-btn { background: #dc2626 !important; border-color: #dc2626 !important; color: white !important; }
.delete-btn:hover:not(:disabled) { background: #b91c1c !important; border-color: #b91c1c !important; }
.delete-btn:disabled { background: #fca5a5 !important; border-color: #fca5a5 !important; }

.access-denied {
  text-align: center;
  padding: 3rem 2rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--pico-border-radius);
  color: #991b1b;
}

.access-denied h3 { color: #dc2626; margin-bottom: 1rem; }
.access-denied p { margin-bottom: 0.5rem; }
.access-denied button { margin-top: 1.5rem; }
</style>

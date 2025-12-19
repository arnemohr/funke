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
            <a
              href="#"
              :class="{ active: statusFilter === null }"
              @click.prevent="statusFilter = null"
            >Alle</a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: statusFilter === 'DRAFT' }"
              @click.prevent="statusFilter = 'DRAFT'"
            >Entwurf</a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: statusFilter === 'OPEN' }"
              @click.prevent="statusFilter = 'OPEN'"
            >Offen</a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: statusFilter === 'COMPLETED' }"
              @click.prevent="statusFilter = 'COMPLETED'"
            >Abgeschlossen</a>
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
          <a
            href="#"
            aria-label="Schließen"
            class="close"
            @click.prevent="showCreateModal = false"
          />
          <h3>Neue Veranstaltung</h3>
        </header>

        <form @submit.prevent="handleCreate" class="compact-form">
          <div class="form-row">
            <label for="name">
              Name *
              <input
                id="name"
                v-model="createForm.name"
                type="text"
                required
                placeholder="Schaluppen Tour"
                :disabled="creating"
              />
            </label>
            <label for="location">
              Ort
              <input
                id="location"
                v-model="createForm.location"
                type="text"
                placeholder="Hamburger Hafen"
                :disabled="creating"
              />
            </label>
          </div>

          <label for="description">
            Beschreibung
            <textarea
              id="description"
              v-model="createForm.description"
              rows="2"
              placeholder="dies das ... "
              :disabled="creating"
            />
          </label>

          <div class="form-row">
            <label for="startAt">
              Datum & Uhrzeit *
              <input
                id="startAt"
                v-model="createForm.startAt"
                type="datetime-local"
                required
                :disabled="creating"
              />
            </label>
            <label for="capacity">
              Plätze *
              <input
                id="capacity"
                v-model.number="createForm.capacity"
                type="number"
                min="1"
                max="500"
                required
                :disabled="creating"
              />
            </label>
          </div>

          <div class="form-row">
            <label for="registrationDeadline">
              Anmeldeschluss *
              <input
                id="registrationDeadline"
                v-model="createForm.registrationDeadline"
                type="datetime-local"
                required
                :disabled="creating"
              />
            </label>
            <label for="reminderSchedule">
              Erinnerungen (Tage vorher)
              <input
                id="reminderSchedule"
                v-model="createForm.reminderSchedule"
                type="text"
                placeholder="7, 3, 1"
                :disabled="creating"
              />
            </label>
          </div>

          <label class="checkbox-label">
            <input
              v-model="createForm.autopromoteWaitlist"
              type="checkbox"
              :disabled="creating"
            />
            Automatisch von der Warteliste nachrücken lassen
          </label>

          <div v-if="createError" role="alert" class="error">
            {{ createError }}
          </div>

          <footer>
            <button
              type="button"
              class="secondary"
              @click="showCreateModal = false"
              :disabled="creating"
            >
              Abbrechen
            </button>
            <button type="submit" :disabled="creating" :aria-busy="creating">
              {{ creating ? 'Wird erstellt...' : 'Erstellen' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Clone Event Modal -->
    <dialog :open="cloneEvent !== null">
      <article>
        <header>
          <a
            href="#"
            aria-label="Schließen"
            class="close"
            @click.prevent="cloneEvent = null"
          />
          <h3>Veranstaltung duplizieren</h3>
        </header>

        <p>Erstelle eine Kopie von "{{ cloneEvent?.name }}" mit neuem Datum.</p>

        <form @submit.prevent="handleClone">
          <label for="cloneStartAt">
            Neues Datum & Uhrzeit *
            <input
              id="cloneStartAt"
              v-model="cloneStartAt"
              type="datetime-local"
              required
              :disabled="cloning"
            />
          </label>

          <div v-if="cloneError" role="alert" class="error">
            {{ cloneError }}
          </div>

          <footer>
            <button
              type="button"
              class="secondary"
              @click="cloneEvent = null"
              :disabled="cloning"
            >
              Abbrechen
            </button>
            <button type="submit" :disabled="cloning" :aria-busy="cloning">
              {{ cloning ? 'Wird dupliziert...' : 'Duplizieren' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Registrations Modal -->
    <dialog :open="selectedEvent !== null">
      <article style="max-width: 900px;">
        <header>
          <a
            href="#"
            aria-label="Schließen"
            class="close"
            @click.prevent="selectedEvent = null"
          />
          <h3>Anmeldungen: {{ selectedEvent?.name }}</h3>
        </header>

        <!-- Event Info Summary -->
        <div class="event-info-summary" v-if="selectedEvent">
          <div class="event-info-row">
            <span class="event-info-label">Datum:</span>
            <span>{{ formatDate(selectedEvent.start_at) }}</span>
          </div>
          <div class="event-info-row">
            <span class="event-info-label">Anmeldungen:</span>
            <span>{{ selectedEvent.registration_spots }} Personen ({{ selectedEvent.registration_count }} Buchungen)</span>
          </div>
          <div class="event-info-row">
            <span class="event-info-label">Bestätigt:</span>
            <span>{{ selectedEvent.confirmed_spots }} / {{ selectedEvent.capacity }} Plätze</span>
          </div>
          <div class="event-info-row" v-if="selectedEvent.waitlist_count > 0">
            <span class="event-info-label">Warteliste:</span>
            <span>{{ selectedEvent.waitlist_spots }} Personen ({{ selectedEvent.waitlist_count }} Buchungen)</span>
          </div>
          <div class="event-info-row">
            <span class="event-info-label">Erinnerungen:</span>
            <span>{{ formatReminderSchedule(selectedEvent.reminder_schedule_days) }} Tage vorher</span>
          </div>
        </div>

        <div v-if="loadingRegistrations" aria-busy="true">
          Anmeldungen werden geladen...
        </div>

        <div v-else-if="registrationsError" role="alert" class="error">
          {{ registrationsError }}
        </div>

        <template v-else>
          <p v-if="registrations.length === 0">
            Noch keine Anmeldungen für diese Veranstaltung.
          </p>

          <table v-else>
            <thead>
              <tr>
                <th>Name</th>
                <th>E-Mail</th>
                <th>Personen</th>
                <th>Status</th>
                <th>Angemeldet am</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="reg in registrations" :key="reg.id">
                <td>{{ reg.name }}</td>
                <td><a :href="`mailto:${reg.email}`">{{ reg.email }}</a></td>
                <td>{{ reg.group_size }}</td>
                <td>
                  <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                    {{ formatStatus(reg.status) }}
                    <template v-if="reg.status === 'WAITLISTED' && reg.waitlist_position">
                      (#{{ reg.waitlist_position }})
                    </template>
                  </span>
                </td>
                <td>{{ formatDate(reg.registered_at) }}</td>
              </tr>
            </tbody>
          </table>

          <p class="total-info">
            Gesamt: {{ registrations.length }} Anmeldung(en),
            {{ registrations.reduce((sum, r) => sum + r.group_size, 0) }} Platz/Plätze
          </p>

          <!-- Attendance summary for CONFIRMED events -->
          <div v-if="selectedEvent?.status === 'CONFIRMED'" class="confirmation-summary">
            <strong>Teilnahmestatus:</strong>
            <span class="confirmation-stat yes">
              {{ registrations.filter(r => r.status === 'PARTICIPATING').length }} bestätigt
            </span>
            <span class="confirmation-stat no">
              {{ registrations.filter(r => r.status === 'CANCELLED').length }} abgesagt
            </span>
            <span class="confirmation-stat pending">
              {{ registrations.filter(r => r.status === 'CONFIRMED').length }} ausstehend
            </span>
          </div>
        </template>

        <footer>
          <div class="modal-actions">
            <button
              v-if="['DRAFT', 'OPEN'].includes(selectedEvent?.status)"
              @click="showEditModal(selectedEvent)"
              class="outline"
            >
              Bearbeiten
            </button>
            <button
              v-if="selectedEvent?.status === 'DRAFT'"
              @click="publishEvent(selectedEvent)"
              class="secondary"
              :disabled="publishing === selectedEvent?.id"
            >
              {{ publishing === selectedEvent?.id ? 'Wird veröffentlicht...' : 'Veröffentlichen' }}
            </button>
            <button
              v-if="selectedEvent?.status === 'OPEN'"
              @click="copyRegistrationLink(selectedEvent)"
              class="outline"
            >
              Link kopieren
            </button>
            <button
              v-if="selectedEvent?.status === 'OPEN'"
              @click="closeRegistration(selectedEvent)"
              class="secondary"
              :disabled="closing === selectedEvent?.id"
            >
              {{ closing === selectedEvent?.id ? 'Wird geschlossen...' : 'Anmeldung schließen' }}
            </button>
            <button
              @click="showCloneModal(selectedEvent)"
              class="outline secondary"
            >
              Duplizieren
            </button>
            <button
              v-if="['REGISTRATION_CLOSED', 'LOTTERY_PENDING', 'CONFIRMED'].includes(selectedEvent?.status)"
              @click="goToLottery(selectedEvent)"
              class="outline"
            >
              Verlosung
            </button>
            <button
              v-if="!['COMPLETED', 'CANCELLED'].includes(selectedEvent?.status)"
              @click="showCancelEventModal(selectedEvent)"
              class="outline cancel-btn"
            >
              Absagen
            </button>
            <button
              v-if="selectedEvent?.status === 'CANCELLED'"
              @click="showDeleteModal(selectedEvent)"
              class="outline delete-btn"
            >
              Löschen
            </button>
          </div>
          <button @click="selectedEvent = null">Schließen</button>
        </footer>
      </article>
    </dialog>

    <!-- Cancel Event Confirmation Modal -->
    <dialog :open="cancelEventData !== null">
      <article>
        <header>
          <a
            href="#"
            aria-label="Schließen"
            class="close"
            @click.prevent="cancelEventData = null"
          />
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
            <input
              id="cancelConfirmation"
              v-model="cancelConfirmation"
              type="text"
              placeholder="absagen"
              autocomplete="off"
              :disabled="cancelling"
            />
          </label>

          <div v-if="cancelError" role="alert" class="error">
            {{ cancelError }}
          </div>

          <footer>
            <button
              type="button"
              class="secondary"
              @click="cancelEventData = null"
              :disabled="cancelling"
            >
              Zurück
            </button>
            <button
              type="submit"
              class="cancel-confirm-btn"
              :disabled="cancelConfirmation !== 'absagen' || cancelling"
              :aria-busy="cancelling"
            >
              {{ cancelling ? 'Wird abgesagt...' : 'Absage bestätigen' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Edit Event Modal -->
    <dialog :open="editEventData !== null">
      <article class="modal-wide">
        <header>
          <a
            href="#"
            aria-label="Schließen"
            class="close"
            @click.prevent="editEventData = null"
          />
          <h3>Veranstaltung bearbeiten</h3>
        </header>

        <form @submit.prevent="handleEdit" class="compact-form">
          <div class="form-row">
            <label for="editName">
              Name *
              <input
                id="editName"
                v-model="editForm.name"
                type="text"
                required
                placeholder="Schaluppen Tour"
                :disabled="editing"
              />
            </label>
            <label for="editLocation">
              Ort
              <input
                id="editLocation"
                v-model="editForm.location"
                type="text"
                placeholder="Hamburger Hafen"
                :disabled="editing"
              />
            </label>
          </div>

          <label for="editDescription">
            Beschreibung
            <textarea
              id="editDescription"
              v-model="editForm.description"
              rows="2"
              placeholder="dies das ..."
              :disabled="editing"
            />
          </label>

          <div class="form-row">
            <label for="editStartAt">
              Datum & Uhrzeit *
              <input
                id="editStartAt"
                v-model="editForm.startAt"
                type="datetime-local"
                required
                :disabled="editing"
              />
            </label>
            <label for="editCapacity">
              Plätze *
              <input
                id="editCapacity"
                v-model.number="editForm.capacity"
                type="number"
                min="1"
                max="500"
                required
                :disabled="editing"
              />
            </label>
          </div>

          <div class="form-row">
            <label for="editRegistrationDeadline">
              Anmeldeschluss *
              <input
                id="editRegistrationDeadline"
                v-model="editForm.registrationDeadline"
                type="datetime-local"
                required
                :disabled="editing"
              />
            </label>
            <label for="editReminderSchedule">
              Erinnerungen (Tage vorher)
              <input
                id="editReminderSchedule"
                v-model="editForm.reminderSchedule"
                type="text"
                placeholder="7, 3, 1"
                :disabled="editing"
              />
            </label>
          </div>

          <label class="checkbox-label">
            <input
              v-model="editForm.autopromoteWaitlist"
              type="checkbox"
              :disabled="editing"
            />
            Automatisch von der Warteliste nachrücken lassen
          </label>

          <div v-if="editError" role="alert" class="error">
            {{ editError }}
          </div>

          <footer>
            <button
              type="button"
              class="secondary"
              @click="editEventData = null"
              :disabled="editing"
            >
              Abbrechen
            </button>
            <button type="submit" :disabled="editing" :aria-busy="editing">
              {{ editing ? 'Wird gespeichert...' : 'Speichern' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Delete Event Confirmation Modal -->
    <dialog :open="deleteEventData !== null">
      <article>
        <header>
          <a
            href="#"
            aria-label="Schließen"
            class="close"
            @click.prevent="deleteEventData = null"
          />
          <h3>Veranstaltung löschen</h3>
        </header>

        <p>Möchtest du "{{ deleteEventData?.name }}" wirklich endgültig löschen?</p>
        <p><small>Diese Aktion kann nicht rückgängig gemacht werden.</small></p>

        <div v-if="deleteError" role="alert" class="error">
          {{ deleteError }}
        </div>

        <footer>
          <button
            type="button"
            class="secondary"
            @click="deleteEventData = null"
            :disabled="deleting"
          >
            Abbrechen
          </button>
          <button
            @click="handleDelete"
            class="delete-btn"
            :disabled="deleting"
            :aria-busy="deleting"
          >
            {{ deleting ? 'Wird gelöscht...' : 'Löschen' }}
          </button>
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

const router = useRouter()
const { logout: auth0Logout } = useAuth0()
const loading = ref(true)
const error = ref(null)
const accessDenied = ref(false)
const events = ref([])
const statusFilter = ref(null)

// Create modal state
const showCreateModal = ref(false)
const creating = ref(false)
const createError = ref(null)
const createForm = ref({
  name: '',
  description: '',
  location: '',
  startAt: '',
  capacity: 100,
  registrationDeadline: '',
  autopromoteWaitlist: true,
  reminderSchedule: '7, 3, 1',
})

// Clone modal state
const cloneEvent = ref(null)
const cloneStartAt = ref('')
const cloning = ref(false)
const cloneError = ref(null)

// Publishing state
const publishing = ref(null)
const closing = ref(null)

// Registrations modal state
const selectedEvent = ref(null)
const registrations = ref([])
const loadingRegistrations = ref(false)
const registrationsError = ref(null)

// Cancel event modal state
const cancelEventData = ref(null)
const cancelConfirmation = ref('')
const cancelling = ref(false)
const cancelError = ref(null)

// Edit event modal state
const editEventData = ref(null)
const editForm = ref({
  name: '',
  description: '',
  location: '',
  startAt: '',
  capacity: 100,
  registrationDeadline: '',
  autopromoteWaitlist: true,
  reminderSchedule: '7, 3, 1',
})
const editing = ref(false)
const editError = ref(null)

// Delete event modal state
const deleteEventData = ref(null)
const deleting = ref(false)
const deleteError = ref(null)

// Filter events by status
const filteredEvents = computed(() => {
  if (!statusFilter.value) return events.value
  return events.value.filter(e => e.status === statusFilter.value)
})

// Format date for display
function formatDate(dateStr) {
  if (!dateStr) return 'Noch offen'
  const date = new Date(dateStr)
  return date.toLocaleDateString('de-DE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Parse reminder schedule from comma-separated string to array of integers
function parseReminderSchedule(scheduleStr) {
  if (!scheduleStr || !scheduleStr.trim()) {
    return [7, 3, 1] // Default
  }
  const days = scheduleStr
    .split(',')
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n > 0)
  return days.length > 0 ? days : [7, 3, 1]
}

// Format reminder schedule from array to comma-separated string
function formatReminderSchedule(days) {
  if (!days || !Array.isArray(days) || days.length === 0) {
    return '7, 3, 1'
  }
  return days.join(', ')
}

// Format registration status for display
function formatStatus(status) {
  const statusLabels = {
    'REGISTERED': 'Angemeldet',
    'CONFIRMED': 'Wartet auf Bestätigung',
    'PARTICIPATING': 'Nimmt teil',
    'WAITLISTED': 'Warteliste',
    'CANCELLED': 'Abgesagt',
    'CHECKED_IN': 'Eingecheckt',
  }
  return statusLabels[status] || status
}

// Logout function
function logout() {
  auth0Logout({ logoutParams: { returnTo: window.location.origin } })
}

// Load events
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
    // Detect access denied (403) errors
    if (message.includes('Access denied') || message.includes('403')) {
      accessDenied.value = true
    }
  } finally {
    loading.value = false
  }
}

// Handle create event
async function handleCreate() {
  creating.value = true
  createError.value = null

  try {
    const newEvent = await adminApi.createEvent({
      name: createForm.value.name.trim(),
      description: createForm.value.description?.trim() || null,
      location: createForm.value.location?.trim() || null,
      start_at: new Date(createForm.value.startAt).toISOString(),
      capacity: createForm.value.capacity,
      registration_deadline: new Date(createForm.value.registrationDeadline).toISOString(),
      autopromote_waitlist: createForm.value.autopromoteWaitlist,
      reminder_schedule_days: parseReminderSchedule(createForm.value.reminderSchedule),
    })

    events.value.unshift(newEvent)
    showCreateModal.value = false

    // Reset form
    createForm.value = {
      name: '',
      description: '',
      location: '',
      startAt: '',
      capacity: 100,
      registrationDeadline: '',
      autopromoteWaitlist: true,
      reminderSchedule: '7, 3, 1',
    }
  } catch (err) {
    console.error('Create event error:', err)
    createError.value = typeof err === 'string' ? err : (err.message || JSON.stringify(err))
  } finally {
    creating.value = false
  }
}

// Publish event
async function publishEvent(event) {
  publishing.value = event.id

  try {
    const updated = await adminApi.publishEvent(event.id)
    const index = events.value.findIndex(e => e.id === event.id)
    if (index !== -1) {
      events.value[index] = updated
    }
    // Update selectedEvent if it's the same event (so modal reflects new state)
    if (selectedEvent.value?.id === event.id) {
      selectedEvent.value = updated
    }
  } catch (err) {
    alert(err.message || 'Veröffentlichung fehlgeschlagen')
  } finally {
    publishing.value = null
  }
}

// Close registration to enable lottery
async function closeRegistration(event) {
  closing.value = event.id

  try {
    const updated = await adminApi.closeRegistration(event.id)
    const index = events.value.findIndex(e => e.id === event.id)
    if (index !== -1) {
      events.value[index] = updated
    }
    // Update selectedEvent if it's the same event (so modal reflects new state)
    if (selectedEvent.value?.id === event.id) {
      selectedEvent.value = updated
    }
  } catch (err) {
    alert(err.message || 'Anmeldung konnte nicht geschlossen werden')
  } finally {
    closing.value = null
  }
}

// Show clone modal
function showCloneModal(event) {
  cloneEvent.value = event
  cloneStartAt.value = ''
  cloneError.value = null
}

// Handle clone event
async function handleClone() {
  cloning.value = true
  cloneError.value = null

  try {
    const newEvent = await adminApi.cloneEvent(
      cloneEvent.value.id,
      new Date(cloneStartAt.value).toISOString()
    )

    events.value.unshift(newEvent)
    cloneEvent.value = null
  } catch (err) {
    cloneError.value = err.message || 'Duplizieren fehlgeschlagen'
  } finally {
    cloning.value = false
  }
}

// Copy registration link
function copyRegistrationLink(event) {
  const baseUrl = window.location.origin
  const link = `${baseUrl}/register/${event.registration_link_token}`

  navigator.clipboard.writeText(link).then(() => {
    alert('Anmeldelink wurde kopiert!')
  }).catch(() => {
    prompt('Kopiere diesen Link:', link)
  })
}

function goToLottery(event) {
  router.push({ name: 'admin-event-lottery', params: { eventId: event.id } })
}

// View registrations for an event
async function viewRegistrations(event) {
  selectedEvent.value = event
  loadingRegistrations.value = true
  registrationsError.value = null
  registrations.value = []

  try {
    const result = await adminApi.listRegistrations(event.id)
    registrations.value = result.items
  } catch (err) {
    registrationsError.value = err.message || 'Anmeldungen konnten nicht geladen werden'
  } finally {
    loadingRegistrations.value = false
  }
}

// Show cancel event confirmation modal
function showCancelEventModal(event) {
  cancelEventData.value = event
  cancelConfirmation.value = ''
  cancelError.value = null
}

// Handle event cancellation
async function handleCancelEvent() {
  if (cancelConfirmation.value !== 'absagen') return

  cancelling.value = true
  cancelError.value = null

  try {
    const updated = await adminApi.cancelEvent(cancelEventData.value.id)

    // Update the event in the list
    const index = events.value.findIndex(e => e.id === cancelEventData.value.id)
    if (index !== -1) {
      events.value[index] = updated
    }

    // Close modals
    cancelEventData.value = null
    selectedEvent.value = null
  } catch (err) {
    cancelError.value = err.message || 'Absage fehlgeschlagen'
  } finally {
    cancelling.value = false
  }
}

// Helper to format datetime for input
function formatDateTimeLocal(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  // Format as YYYY-MM-DDTHH:mm for datetime-local input
  return date.toISOString().slice(0, 16)
}

// Show edit event modal
function showEditModal(event) {
  editEventData.value = event
  editForm.value = {
    name: event.name,
    description: event.description || '',
    location: event.location || '',
    startAt: formatDateTimeLocal(event.start_at),
    capacity: event.capacity,
    registrationDeadline: formatDateTimeLocal(event.registration_deadline),
    autopromoteWaitlist: event.autopromote_waitlist,
    reminderSchedule: formatReminderSchedule(event.reminder_schedule_days),
  }
  editError.value = null
}

// Handle edit event
async function handleEdit() {
  editing.value = true
  editError.value = null

  try {
    const updated = await adminApi.updateEvent(editEventData.value.id, {
      name: editForm.value.name,
      description: editForm.value.description || null,
      location: editForm.value.location || null,
      start_at: new Date(editForm.value.startAt).toISOString(),
      capacity: editForm.value.capacity,
      registration_deadline: new Date(editForm.value.registrationDeadline).toISOString(),
      autopromote_waitlist: editForm.value.autopromoteWaitlist,
      reminder_schedule_days: parseReminderSchedule(editForm.value.reminderSchedule),
    })

    // Update the event in the list
    const index = events.value.findIndex(e => e.id === editEventData.value.id)
    if (index !== -1) {
      events.value[index] = updated
    }

    // Update selectedEvent if it's the same event
    if (selectedEvent.value?.id === editEventData.value.id) {
      selectedEvent.value = updated
    }

    // Close edit modal
    editEventData.value = null
  } catch (err) {
    editError.value = err.message || 'Änderungen konnten nicht gespeichert werden'
  } finally {
    editing.value = false
  }
}

// Show delete event modal
function showDeleteModal(event) {
  deleteEventData.value = event
  deleteError.value = null
}

// Handle delete event
async function handleDelete() {
  deleting.value = true
  deleteError.value = null

  try {
    await adminApi.deleteEvent(deleteEventData.value.id)

    // Remove the event from the list
    events.value = events.value.filter(e => e.id !== deleteEventData.value.id)

    // Close modals
    deleteEventData.value = null
    selectedEvent.value = null
  } catch (err) {
    deleteError.value = err.message || 'Veranstaltung konnte nicht gelöscht werden'
  } finally {
    deleting.value = false
  }
}

// Reload events when status filter changes
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

.status-draft {
  background: #e2e8f0;
  color: #64748b;
}

.status-open {
  background: #dcfce7;
  color: #16a34a;
}

.status-registration_closed {
  background: #fef3c7;
  color: #d97706;
}

.status-completed {
  background: #dbeafe;
  color: #2563eb;
}

.status-cancelled {
  background: #fee2e2;
  color: #dc2626;
}

.modal-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.modal-actions button {
  margin: 0;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

dialog article {
  max-width: 600px;
}

dialog article.modal-wide {
  max-width: 750px;
}

.compact-form label {
  margin-bottom: 0.75rem;
}

.compact-form textarea {
  margin-bottom: 0;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.form-row label {
  margin-bottom: 0.75rem;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.checkbox-label input[type="checkbox"] {
  margin: 0;
  width: 1.25rem;
  height: 1.25rem;
  cursor: pointer;
}

dialog footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}

/* Registration status styles */
.status-registered {
  background: #e0e7ff;
  color: #4f46e5;
}

.status-confirmed {
  background: #fef3c7;
  color: #d97706;
}

.status-participating {
  background: #dcfce7;
  color: #16a34a;
}

.status-waitlisted {
  background: #e5e7eb;
  color: #6b7280;
}

.status-checked_in {
  background: #dbeafe;
  color: #2563eb;
}

.total-info {
  margin-top: 1rem;
  font-size: 0.875rem;
  color: var(--pico-muted-color);
}

/* Cancel event styles */
.cancel-btn {
  border-color: #dc2626 !important;
  color: #dc2626 !important;
}

.cancel-btn:hover {
  background: #dc2626 !important;
  color: white !important;
}

.cancel-warning {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--pico-border-radius);
  padding: 1rem;
  margin-bottom: 1rem;
}

.cancel-warning p {
  margin-bottom: 0.5rem;
}

.cancel-warning ul {
  margin: 0.5rem 0 0 1.5rem;
  padding: 0;
}

.cancel-confirm-btn {
  background: #dc2626 !important;
  border-color: #dc2626 !important;
}

.cancel-confirm-btn:hover:not(:disabled) {
  background: #b91c1c !important;
  border-color: #b91c1c !important;
}

.cancel-confirm-btn:disabled {
  background: #fca5a5 !important;
  border-color: #fca5a5 !important;
}

/* Delete button styles */
.delete-btn {
  background: #dc2626 !important;
  border-color: #dc2626 !important;
  color: white !important;
}

.delete-btn:hover:not(:disabled) {
  background: #b91c1c !important;
  border-color: #b91c1c !important;
}

.delete-btn:disabled {
  background: #fca5a5 !important;
  border-color: #fca5a5 !important;
}

.outline.delete-btn {
  background: transparent !important;
  color: #dc2626 !important;
}

.outline.delete-btn:hover {
  background: #dc2626 !important;
  color: white !important;
}

/* Attendance summary styles - kept for consistency */

.confirmation-summary {
  margin-top: 1rem;
  padding: 0.75rem;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  font-size: 0.875rem;
  color: #334155;
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
}

.confirmation-stat {
  padding: 0.25rem 0.5rem;
  border-radius: var(--pico-border-radius);
  font-weight: 500;
}

.confirmation-stat.yes {
  background: #dcfce7;
  color: #16a34a;
}

.confirmation-stat.no {
  background: #fee2e2;
  color: #dc2626;
}

.confirmation-stat.pending {
  background: #fef3c7;
  color: #d97706;
}

/* Event info summary styles */
.event-info-summary {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
  color: #334155;
}

.event-info-row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.event-info-row:last-child {
  margin-bottom: 0;
}

.event-info-label {
  font-weight: 600;
  color: #64748b;
  min-width: 120px;
}

/* Access denied styles */
.access-denied {
  text-align: center;
  padding: 3rem 2rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--pico-border-radius);
  color: #991b1b;
}

.access-denied h3 {
  color: #dc2626;
  margin-bottom: 1rem;
}

.access-denied p {
  margin-bottom: 0.5rem;
}

.access-denied button {
  margin-top: 1.5rem;
}
</style>

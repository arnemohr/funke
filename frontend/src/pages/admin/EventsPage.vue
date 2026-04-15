<template>
  <article style="position: relative;">
    <header>
      <hgroup>
        <h2>Veranstaltungen</h2>
        <p>Verwalte deine Veranstaltungen</p>
      </hgroup>
      <div class="header-actions">
        <HelpButton @click="help.toggle(activeHelpKey)" />
        <button v-if="!accessDenied" @click="showCreateModal = true">Neue Veranstaltung</button>
      </div>
    </header>

    <HelpPanel
      :help-key="help.helpKey.value"
      :open="help.isOpen.value"
      ref="helpPanelRef"
      @close="help.close()"
    />

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
      <nav class="filter-nav">
        <ul class="filter-tabs">
          <li>
            <a href="#" :class="{ active: statusFilter === null }" @click.prevent="statusFilter = null">Alle ({{ filterCounts.all }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'DRAFT' }" @click.prevent="statusFilter = 'DRAFT'">Entwurf ({{ filterCounts.DRAFT }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'OPEN' }" @click.prevent="statusFilter = 'OPEN'">Offen ({{ filterCounts.OPEN }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'IN_PROGRESS' }" @click.prevent="statusFilter = 'IN_PROGRESS'">In Bearbeitung ({{ filterCounts.IN_PROGRESS }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'COMPLETED' }" @click.prevent="statusFilter = 'COMPLETED'">Abgeschlossen ({{ filterCounts.COMPLETED }})</a>
          </li>
          <li>
            <a href="#" :class="{ active: statusFilter === 'CANCELLED' }" @click.prevent="statusFilter = 'CANCELLED'">Abgesagt ({{ filterCounts.CANCELLED }})</a>
          </li>
        </ul>
      </nav>

      <!-- Empty state -->
      <article v-if="filteredEvents.length === 0" style="text-align: center; padding: 2rem;">
        <p>Noch keine Veranstaltungen. Leg los und erstelle deine erste!</p>
        <button @click="showCreateModal = true">Neue Veranstaltung</button>
      </article>

      <!-- Events table -->
      <table v-else class="mobile-card-table">
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
            <td data-label="Veranstaltung">
              <a href="#" @click.prevent="viewRegistrations(event)">
                <strong>{{ event.name }}</strong>
              </a>
              <br />
              <small>{{ event.location || 'Kein Ort angegeben' }}</small>
            </td>
            <td data-label="Datum">{{ formatDate(event.start_at) }}</td>
            <td data-label="Status">
              <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
                {{ formatEventStatus(event.status) }}
              </span>
            </td>
            <td data-label="Anmeldungen">
              <div>{{ event.registration_count }} Anmeldungen ({{ event.registration_spots }} Pers.)</div>
              <div style="font-size: var(--text-sm); color: var(--pico-muted-color);">{{ event.confirmed_spots }} / {{ event.capacity }} bestätigt<span v-if="event.waitlist_count"> · {{ event.waitlist_spots }} Warteliste</span></div>
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
      @copy-invite="copyInviteText"
      @go-to-lottery="goToLottery"
      @complete-event="completeEvent"
      @export-csv="handleExportCsv"
      @send-message="showMessageComposer = true"
      @show-messages="showMessageLog = true"
      @toggle-promoted="handleTogglePromoted"
      @promote-waitlisted="handlePromoteWaitlisted"
      @discard-unacknowledged="handleDiscardUnacknowledged"
      @delete-registration="handleDeleteRegistration"
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
            <button type="submit" class="btn-danger" :disabled="cancelConfirmation !== 'absagen' || cancelling" :aria-busy="cancelling">
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
          <button @click="handleDelete" class="btn-danger" :disabled="deleting" :aria-busy="deleting">
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

    <!-- Discard Unacknowledged Modal -->
    <dialog :open="showDiscardModal">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="showDiscardModal = false" />
          <h3>Unbestätigte Anmeldungen verwerfen</h3>
        </header>
        <div v-if="discardCandidates.length === 0">
          <p>Keine unbestätigten Anmeldungen vorhanden.</p>
        </div>
        <template v-else>
          <p>
            <a href="#" @click.prevent="toggleAllDiscard">
              {{ selectedDiscardIds.size === discardCandidates.length ? 'Alle abwählen' : 'Alle auswählen' }}
            </a>
          </p>
          <div class="discard-list">
            <label v-for="reg in discardCandidates" :key="reg.id" class="discard-item">
              <input
                type="checkbox"
                :checked="selectedDiscardIds.has(reg.id)"
                @change="toggleDiscardId(reg.id)"
              />
              {{ reg.name }} ({{ reg.group_size }} Pers.)
            </label>
          </div>
          <label for="discardSubject">
            Betreff
            <input
              id="discardSubject"
              v-model="discardSubject"
              type="text"
            />
          </label>
          <label for="discardMessage">
            Nachricht an die Teilnehmer
            <textarea
              id="discardMessage"
              v-model="discardMessage"
              rows="4"
              placeholder="Optionale Nachricht an die Teilnehmer..."
            ></textarea>
          </label>
          <div v-if="discardError" role="alert" class="error">{{ discardError }}</div>
          <footer>
            <button type="button" class="secondary" @click="showDiscardModal = false" :disabled="discarding">Abbrechen</button>
            <button
              class="btn-danger"
              :disabled="selectedDiscardIds.size === 0 || discarding"
              :aria-busy="discarding"
              @click="handleDiscardConfirm"
            >
              {{ discarding ? 'Wird verworfen...' : `${selectedDiscardIds.size} Anmeldungen verwerfen` }}
            </button>
          </footer>
        </template>
      </article>
    </dialog>

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
    <!-- Delete Registration Confirmation -->
    <dialog :open="deleteRegData !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="deleteRegData = null" />
          <h3>Anmeldung löschen</h3>
        </header>
        <p>Anmeldung von "{{ deleteRegData?.name }}" unwiderruflich löschen?</p>
        <footer>
          <button type="button" class="secondary" @click="deleteRegData = null">Abbrechen</button>
          <button class="btn-danger" @click="confirmDeleteRegistration">Löschen</button>
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
import HelpButton from '../../components/help/HelpButton.vue'
import HelpPanel from '../../components/help/HelpPanel.vue'
import { useHelp } from '../../components/help/useHelp.js'
import { formatDate, formatEventStatus, berlinToUTCISO } from '../../utils/formatters.js'
import { showToast } from '../../composables/useToast.js'

const router = useRouter()
const { logout: auth0Logout } = useAuth0()

// Help system
const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const activeHelpKey = computed(() => {
  if (showDiscardModal.value) return 'discard-modal'
  if (showCreateModal.value || editEventData.value) return 'event-form'
  if (cloneEvent.value) return 'clone-event'
  if (showMessageComposer.value) return 'message-composer'
  return 'admin-events'
})

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
const showDiscardModal = ref(false)
const discardSubject = ref('')
const discardMessage = ref('')
const selectedDiscardIds = ref(new Set())
const discarding = ref(false)
const discardError = ref(null)
const discardEventRef = ref(null)

// Delete registration modal
const deleteRegData = ref(null)

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

const filterCounts = computed(() => {
  const all = events.value
  return {
    all: all.length,
    DRAFT: all.filter(e => e.status === 'DRAFT').length,
    OPEN: all.filter(e => e.status === 'OPEN').length,
    IN_PROGRESS: all.filter(e => IN_PROGRESS_STATUSES.includes(e.status)).length,
    COMPLETED: all.filter(e => e.status === 'COMPLETED').length,
    CANCELLED: all.filter(e => e.status === 'CANCELLED').length,
  }
})

const discardCandidates = computed(() =>
  registrations.value.filter(r => r.status === 'CONFIRMED'),
)

// Helpers
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
    selectedEvent.value = newEvent
    viewRegistrations(newEvent)
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
    showToast(err.message || 'Veröffentlichung fehlgeschlagen', 'error')
  } finally {
    publishing.value = null
  }
}

async function closeRegistration(event) {
  closing.value = event.id
  try {
    updateEventInList(await adminApi.closeRegistration(event.id))
  } catch (err) {
    showToast(err.message || 'Anmeldung konnte nicht geschlossen werden', 'error')
  } finally {
    closing.value = null
  }
}

async function completeEvent(event) {
  completing.value = event.id
  try {
    updateEventInList(await adminApi.completeEvent(event.id))
  } catch (err) {
    showToast(err.message || 'Abschließen fehlgeschlagen', 'error')
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
    events.value.unshift(await adminApi.cloneEvent(cloneEvent.value.id, berlinToUTCISO(cloneStartAt.value)))
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
    () => showToast('Anmeldelink wurde kopiert!', 'success'),
    () => prompt('Kopiere diesen Link:', link),
  )
}

function copyInviteText(event) {
  const link = `${window.location.origin}/register/${event.registration_link_token}`
  const date = new Date(event.start_at)
  const dateStr = date.toLocaleDateString('de-DE', {
    timeZone: 'Europe/Berlin',
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
  const timeStr = date.toLocaleTimeString('de-DE', {
    timeZone: 'Europe/Berlin',
    hour: '2-digit',
    minute: '2-digit',
  })

  let text = `⛵ ${event.name}\n\n`
  if (event.description) {
    text += `${event.description}\n\n`
  }
  text += `📅 ${dateStr} um ${timeStr} Uhr\n`
  if (event.location) {
    text += `📍 ${event.location}\n`
  }
  text += `👥 ${event.capacity} Plätze\n`
  text += `\n🔗 Jetzt anmelden: ${link}`

  navigator.clipboard.writeText(text).then(
    () => showToast('Einladungstext wurde kopiert!', 'success'),
    () => prompt('Kopiere diesen Text:', text),
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
    await adminApi.exportBoardingPdf(event.id)
  } catch (err) {
    showToast(err.message || 'Boardingzettel konnte nicht erstellt werden', 'error')
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
    showToast(err.message || 'Bevorzugung konnte nicht geändert werden', 'error')
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
    showToast(err.message || 'Nachrücken fehlgeschlagen', 'error')
  }
}

function handleDiscardUnacknowledged(event) {
  discardEventRef.value = event
  discardError.value = null
  discardSubject.value = `Dein Platz an Bord: ${event.name}`
  discardMessage.value = 'Leider haben wir innerhalb der Frist keine Rückmeldung von dir erhalten, ob du wirklich mit an Bord kommst. Daher mussten wir deinen Platz an einen anderen Fisch aus unserem Schwarm weitergeben.\n\nFalls du beim nächsten Mal wieder anheuern möchtest, freuen wir uns sehr auf dich!'
  selectedDiscardIds.value = new Set(
    registrations.value.filter(r => r.status === 'CONFIRMED').map(r => r.id),
  )
  showDiscardModal.value = true
}

function toggleAllDiscard() {
  if (selectedDiscardIds.value.size === discardCandidates.value.length) {
    selectedDiscardIds.value = new Set()
  } else {
    selectedDiscardIds.value = new Set(discardCandidates.value.map(r => r.id))
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
  if (!discardEventRef.value || selectedDiscardIds.value.size === 0) return
  discarding.value = true
  discardError.value = null
  try {
    const result = await adminApi.discardUnacknowledged(
      discardEventRef.value.id,
      [...selectedDiscardIds.value],
      discardMessage.value.trim() || undefined,
      discardSubject.value.trim() || undefined,
    )
    showDiscardModal.value = false
    showToast(`${result.discarded_count} Anmeldungen verworfen (${result.discarded_spots} Plätze).`, 'success')
    // Refresh
    const [regs, evt] = await Promise.all([
      adminApi.listRegistrations(discardEventRef.value.id),
      adminApi.getEvent(discardEventRef.value.id),
    ])
    registrations.value = regs.items
    updateEventInList(evt)
  } catch (err) {
    discardError.value = err.message || 'Verwerfen fehlgeschlagen'
  } finally {
    discarding.value = false
  }
}

async function handleDeleteRegistration({ registrationId, name }) {
  if (!selectedEvent.value) return
  deleteRegData.value = { registrationId, name }
}

async function confirmDeleteRegistration() {
  if (!selectedEvent.value || !deleteRegData.value) return
  const { registrationId } = deleteRegData.value
  deleteRegData.value = null
  try {
    await adminApi.deleteRegistration(selectedEvent.value.id, registrationId)
    const [regs, evt] = await Promise.all([
      adminApi.listRegistrations(selectedEvent.value.id),
      adminApi.getEvent(selectedEvent.value.id),
    ])
    registrations.value = regs.items
    updateEventInList(evt)
  } catch (err) {
    showToast(err.message || 'Löschen fehlgeschlagen', 'error')
  }
}

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

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
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

/* Ensure tab links are touch-friendly */
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

dialog article { max-width: min(600px, calc(100vw - 2rem)); }
dialog article.modal-wide { max-width: min(750px, calc(100vw - 2rem)); }

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


.discard-list {
  max-height: 250px;
  overflow-y: auto;
  margin-bottom: 1rem;
}

.discard-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
}

.discard-item input[type="checkbox"] {
  margin: 0;
}


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

@media (max-width: 768px) {
  .filter-nav {
    /* Scroll hint: fade out on the right */
    mask-image: linear-gradient(to right, #000 85%, transparent 100%);
    -webkit-mask-image: linear-gradient(to right, #000 85%, transparent 100%);
  }
}

@media (max-width: 640px) {
  tbody td[data-label="Veranstaltung"] {
    font-weight: 600;
    font-size: var(--text-base);
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 0.4rem;
  }
  tbody td[data-label="Veranstaltung"]::before {
    display: none;
  }
  /* Status badge is self-explanatory, hide label */
  tbody td[data-label="Status"]::before {
    display: none;
  }
}
</style>

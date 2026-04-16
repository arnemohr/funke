<template>
  <article class="event-detail-page">
    <!-- Page header -->
    <header class="page-header">
      <div class="header-left">
        <a href="#" class="back-link" @click.prevent="$router.push('/admin/events')">
          &larr; Events
        </a>
        <div v-if="event" class="header-title">
          <h2>{{ event.name }}</h2>
          <span :class="['status-badge', `status-${event.status.toLowerCase()}`]">
            {{ formatEventStatus(event.status) }}
          </span>
        </div>
      </div>
      <div class="header-actions">
        <HelpButton @click="help.toggle(activeHelpKey)" />
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
      Veranstaltung wird geladen...
    </div>

    <!-- Error state -->
    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <!-- Content -->
    <template v-else-if="event">
      <!-- Tabs -->
      <nav class="tab-nav">
        <ul class="tab-list">
          <li>
            <a href="#" :class="{ active: activeTab === 'details' }" @click.prevent="activeTab = 'details'">Details</a>
          </li>
          <li>
            <a href="#" :class="{ active: activeTab === 'registrations' }" @click.prevent="activeTab = 'registrations'">
              Anmeldungen ({{ registrations.length }})
            </a>
          </li>
          <li>
            <a href="#" :class="{ active: activeTab === 'messages' }" @click.prevent="activeTab = 'messages'">Nachrichten</a>
          </li>
        </ul>
      </nav>

      <!-- Details tab -->
      <div v-show="activeTab === 'details'" class="tab-content">
        <div class="event-info">
          <dl>
            <dt>Datum</dt>
            <dd>{{ formatDate(event.start_at) }}</dd>

            <dt>Ort</dt>
            <dd>{{ event.location || 'Kein Ort angegeben' }}</dd>

            <dt>Kapazität</dt>
            <dd>{{ participatingSpots }} / {{ event.capacity }} bestätigt, {{ pendingSpots }} ausstehend</dd>

            <dt>Warteliste</dt>
            <dd>{{ event.waitlist_spots || 0 }} Personen ({{ event.waitlist_count || 0 }} Buchungen)</dd>

            <dt>Bevorzugt</dt>
            <dd>{{ event.promoted_count || 0 }} Anmeldungen ({{ event.promoted_spots || 0 }} Plätze)</dd>

            <dt>Erinnerungen</dt>
            <dd>{{ event.reminder_schedule_days?.join(', ') || 'Keine' }} Tage vorher</dd>

            <dt>Beschreibung</dt>
            <dd>{{ event.description || 'Keine Beschreibung' }}</dd>
          </dl>
        </div>

        <div class="action-buttons">
          <button class="secondary outline" @click="actions.showEditModal(event)">Bearbeiten</button>
          <button class="secondary outline" @click="actions.showCloneModal(event)">Duplizieren</button>
          <button class="secondary outline" @click="actions.copyRegistrationLink(event)">Link kopieren</button>
          <button class="secondary outline" @click="actions.copyInviteText(event)">Einladungstext</button>
          <button class="secondary outline" @click="actions.handleExportPdf()">Boardingzettel PDF</button>
        </div>
      </div>

      <!-- Registrations tab -->
      <div v-show="activeTab === 'registrations'" class="tab-content">
        <RegistrationTable
          :registrations="registrations"
          :event-status="event.status"
          :loading="loadingRegistrations"
          :error="registrationsError"
          :toggling-id="actions.togglingPromotedId.value"
          @toggle-promoted="actions.handleTogglePromoted"
          @promote-waitlisted="actions.handlePromoteWaitlisted"
          @delete-registration="actions.handleDeleteRegistration"
        />
      </div>

      <!-- Messages tab -->
      <div v-show="activeTab === 'messages'" class="tab-content">
        <div class="messages-tab-header">
          <button @click="actions.showMessageComposer.value = true">Nachricht senden</button>
        </div>
        <MessageLog
          :open="true"
          :event-id="props.eventId"
          @close=""
        />
      </div>

      <!-- Sticky footer -->
      <div class="sticky-footer">
        <!-- Primary CTA -->
        <button
          v-if="event.status === 'DRAFT'"
          @click="actions.publishEvent(event)"
          :disabled="actions.publishing.value"
          :aria-busy="actions.publishing.value"
        >
          {{ actions.publishing.value ? 'Wird veröffentlicht...' : 'Veröffentlichen' }}
        </button>
        <button
          v-else-if="event.status === 'OPEN'"
          @click="actions.closeRegistration(event)"
          :disabled="actions.closingRegistration.value"
          :aria-busy="actions.closingRegistration.value"
        >
          {{ actions.closingRegistration.value ? 'Wird geschlossen...' : 'Anmeldung schließen' }}
        </button>
        <button
          v-else-if="event.status === 'REGISTRATION_CLOSED' || event.status === 'LOTTERY_PENDING'"
          @click="actions.goToLottery(event)"
        >
          Verlosung
        </button>
        <button
          v-else-if="event.status === 'CONFIRMED'"
          @click="actions.completeEvent(event)"
          :disabled="actions.completing.value"
          :aria-busy="actions.completing.value"
        >
          {{ actions.completing.value ? 'Wird abgeschlossen...' : 'Abschließen' }}
        </button>

        <!-- Destructive actions -->
        <details class="destructive-actions">
          <summary>Weitere Aktionen</summary>
          <div class="destructive-buttons">
            <button
              v-if="event.status === 'CONFIRMED'"
              class="btn-danger outline"
              @click="actions.handleDiscardUnacknowledged(event)"
            >
              Unbestätigte verwerfen
            </button>
            <button
              v-if="!['CANCELLED', 'COMPLETED'].includes(event.status)"
              class="btn-danger outline"
              @click="actions.showCancelEventModal(event)"
            >
              Absagen
            </button>
            <button
              class="btn-danger outline"
              @click="actions.showDeleteModal(event)"
            >
              Löschen
            </button>
          </div>
        </details>
      </div>
    </template>

    <!-- ===== Modals ===== -->

    <!-- Edit modal -->
    <dialog :open="actions.editEventData.value !== null">
      <article class="modal-wide">
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.editEventData.value = null" />
          <h3>Veranstaltung bearbeiten</h3>
        </header>
        <EventForm
          :event="actions.editEventData.value"
          :disabled="actions.editing.value"
          :error="actions.editError.value"
          submit-label="Speichern"
          submit-busy-label="Wird gespeichert..."
          @submit="actions.handleEdit"
          @cancel="actions.editEventData.value = null"
        />
      </article>
    </dialog>

    <!-- Clone modal -->
    <dialog :open="actions.cloneEvent.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.cloneEvent.value = null" />
          <h3>Veranstaltung duplizieren</h3>
        </header>
        <p>Erstelle eine Kopie von "{{ actions.cloneEvent.value?.name }}" mit neuem Datum.</p>
        <form @submit.prevent="actions.handleClone">
          <label for="cloneStartAt">
            Neues Datum &amp; Uhrzeit *
            <input id="cloneStartAt" v-model="actions.cloneStartAt.value" type="datetime-local" required :disabled="actions.cloning.value" />
          </label>
          <div v-if="actions.cloneError.value" role="alert" class="error">{{ actions.cloneError.value }}</div>
          <footer>
            <button type="button" class="secondary" @click="actions.cloneEvent.value = null" :disabled="actions.cloning.value">Abbrechen</button>
            <button type="submit" :disabled="actions.cloning.value" :aria-busy="actions.cloning.value">
              {{ actions.cloning.value ? 'Wird dupliziert...' : 'Duplizieren' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Cancel event modal -->
    <dialog :open="actions.cancelEventData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.cancelEventData.value = null" />
          <h3>Veranstaltung absagen</h3>
        </header>
        <div class="cancel-warning">
          <p><strong>Achtung:</strong> Diese Aktion kann nicht rückgängig gemacht werden.</p>
          <p>Wenn du "{{ actions.cancelEventData.value?.name }}" absagst:</p>
          <ul>
            <li>Wird der Status auf ABGESAGT gesetzt</li>
            <li>Werden alle Angemeldeten benachrichtigt</li>
            <li>Sind keine weiteren Anmeldungen möglich</li>
          </ul>
        </div>
        <form @submit.prevent="actions.handleCancelEvent">
          <label for="cancelConfirmation">
            Tippe <strong>absagen</strong> zur Bestätigung:
            <input id="cancelConfirmation" v-model="actions.cancelConfirmation.value" type="text" placeholder="absagen" autocomplete="off" :disabled="actions.cancelling.value" />
          </label>
          <div v-if="actions.cancelError.value" role="alert" class="error">{{ actions.cancelError.value }}</div>
          <footer>
            <button type="button" class="secondary" @click="actions.cancelEventData.value = null" :disabled="actions.cancelling.value">Zurück</button>
            <button type="submit" class="btn-danger" :disabled="actions.cancelConfirmation.value !== 'absagen' || actions.cancelling.value" :aria-busy="actions.cancelling.value">
              {{ actions.cancelling.value ? 'Wird abgesagt...' : 'Absage bestätigen' }}
            </button>
          </footer>
        </form>
      </article>
    </dialog>

    <!-- Delete event modal -->
    <dialog :open="actions.deleteEventData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.deleteEventData.value = null" />
          <h3>Veranstaltung löschen</h3>
        </header>
        <p>Möchtest du "{{ actions.deleteEventData.value?.name }}" wirklich endgültig löschen?</p>
        <p><small>Diese Aktion kann nicht rückgängig gemacht werden.</small></p>
        <div v-if="actions.deleteError.value" role="alert" class="error">{{ actions.deleteError.value }}</div>
        <footer>
          <button type="button" class="secondary" @click="actions.deleteEventData.value = null" :disabled="actions.deleting.value">Abbrechen</button>
          <button @click="actions.handleDelete" class="btn-danger" :disabled="actions.deleting.value" :aria-busy="actions.deleting.value">
            {{ actions.deleting.value ? 'Wird gelöscht...' : 'Löschen' }}
          </button>
        </footer>
      </article>
    </dialog>

    <!-- Discard unacknowledged modal -->
    <dialog :open="actions.showDiscardModal.value">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.showDiscardModal.value = false" />
          <h3>Unbestätigte Anmeldungen verwerfen</h3>
        </header>
        <div v-if="actions.discardCandidates.value.length === 0">
          <p>Keine unbestätigten Anmeldungen vorhanden.</p>
        </div>
        <template v-else>
          <p>
            <a href="#" @click.prevent="actions.toggleAllDiscard">
              {{ actions.selectedDiscardIds.value.size === actions.discardCandidates.value.length ? 'Alle abwählen' : 'Alle auswählen' }}
            </a>
          </p>
          <div class="discard-list">
            <label v-for="reg in actions.discardCandidates.value" :key="reg.id" class="discard-item">
              <input type="checkbox" :checked="actions.selectedDiscardIds.value.has(reg.id)" @change="actions.toggleDiscardId(reg.id)" />
              {{ reg.name }} ({{ reg.group_size }} Pers.)
            </label>
          </div>
          <label for="discardSubject">
            Betreff
            <input id="discardSubject" v-model="actions.discardSubject.value" type="text" />
          </label>
          <label for="discardMessage">
            Nachricht an die Teilnehmer
            <textarea id="discardMessage" v-model="actions.discardMessage.value" rows="4" placeholder="Optionale Nachricht an die Teilnehmer..."></textarea>
          </label>
          <div v-if="actions.discardError.value" role="alert" class="error">{{ actions.discardError.value }}</div>
          <footer>
            <button type="button" class="secondary" @click="actions.showDiscardModal.value = false" :disabled="actions.discarding.value">Abbrechen</button>
            <button class="btn-danger" :disabled="actions.selectedDiscardIds.value.size === 0 || actions.discarding.value" :aria-busy="actions.discarding.value" @click="actions.handleDiscardConfirm">
              {{ actions.discarding.value ? 'Wird verworfen...' : `${actions.selectedDiscardIds.value.size} Anmeldungen verwerfen` }}
            </button>
          </footer>
        </template>
      </article>
    </dialog>

    <!-- Capacity warning -->
    <dialog :open="!!actions.capacityWarning.value">
      <article v-if="actions.capacityWarning.value">
        <header>
          <button aria-label="Schließen" rel="prev" @click="actions.capacityWarning.value = null"></button>
          <h3>Kapazität überschritten</h3>
        </header>
        <p>
          <strong>{{ actions.capacityWarning.value.name }}</strong> benötigt {{ actions.capacityWarning.value.needed }}
          {{ actions.capacityWarning.value.needed === 1 ? 'Platz' : 'Plätze' }}, aber nur
          {{ actions.capacityWarning.value.remaining <= 0 ? 'keine' : actions.capacityWarning.value.remaining }}
          {{ actions.capacityWarning.value.remaining === 1 ? 'Platz ist' : 'Plätze sind' }} frei.
        </p>
        <footer>
          <button @click="actions.capacityWarning.value = null">Verstanden</button>
        </footer>
      </article>
    </dialog>

    <!-- Delete registration -->
    <dialog :open="actions.deleteRegData.value !== null">
      <article>
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="actions.deleteRegData.value = null" />
          <h3>Anmeldung löschen</h3>
        </header>
        <p>Anmeldung von "{{ actions.deleteRegData.value?.name }}" unwiderruflich löschen?</p>
        <footer>
          <button type="button" class="secondary" @click="actions.deleteRegData.value = null">Abbrechen</button>
          <button class="btn-danger" @click="actions.confirmDeleteRegistration">Löschen</button>
        </footer>
      </article>
    </dialog>

    <!-- Message Composer -->
    <MessageComposer
      :open="actions.showMessageComposer.value"
      :event-id="props.eventId"
      :registrations="registrations"
      @close="actions.showMessageComposer.value = false"
      @sent="onMessageSent"
    />
  </article>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { adminApi } from '../../services/api'
import { useEventActions } from '../../composables/useEventActions.js'
import { useHelp } from '../../components/help/useHelp.js'
import { formatDate, formatEventStatus } from '../../utils/formatters.js'
import { showToast } from '../../composables/useToast.js'
import EventForm from '../../components/EventForm.vue'
import RegistrationTable from '../../components/RegistrationTable.vue'
import MessageComposer from '../../components/MessageComposer.vue'
import MessageLog from '../../components/MessageLog.vue'
import HelpButton from '../../components/help/HelpButton.vue'
import HelpPanel from '../../components/help/HelpPanel.vue'

const props = defineProps({
  eventId: { type: String, required: true },
})

// State
const event = ref(null)
const registrations = ref([])
const loading = ref(true)
const loadError = ref(null)
const loadingRegistrations = ref(false)
const registrationsError = ref(null)
const activeTab = ref('details')

// Help system
const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const activeHelpKey = computed(() => {
  if (actions.showDiscardModal.value) return 'discard-modal'
  if (actions.editEventData.value) return 'event-form'
  if (actions.cloneEvent.value) return 'clone-event'
  if (actions.showMessageComposer.value) return 'message-composer'
  return 'event-detail'
})

// Data loading
async function refreshEvent() {
  try {
    event.value = await adminApi.getEvent(props.eventId)
  } catch (err) {
    loadError.value = err.message || 'Veranstaltung konnte nicht geladen werden'
  }
}

async function refreshRegistrations() {
  try {
    registrations.value = (await adminApi.listRegistrations(props.eventId)).items
  } catch (err) {
    registrationsError.value = err.message || 'Anmeldungen konnten nicht geladen werden'
  }
}

// Event actions composable
const actions = useEventActions({ event, registrations, refreshEvent, refreshRegistrations })

// Computed helpers
function spotsBy(status) {
  return registrations.value.filter(r => r.status === status).reduce((sum, r) => sum + r.group_size, 0)
}
const participatingSpots = computed(() => spotsBy('PARTICIPATING'))
const pendingSpots = computed(() => spotsBy('CONFIRMED'))

// Message sent handler
function onMessageSent() {
  showToast('Nachricht wurde gesendet', 'success')
  refreshRegistrations()
}

// Initial load
onMounted(async () => {
  loading.value = true
  loadError.value = null
  try {
    const [evt, regs] = await Promise.all([
      adminApi.getEvent(props.eventId),
      adminApi.listRegistrations(props.eventId),
    ])
    event.value = evt
    registrations.value = regs.items
  } catch (err) {
    loadError.value = err.message || 'Daten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.event-detail-page {
  padding-bottom: 6rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1rem;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.back-link {
  font-size: var(--text-sm, 0.875rem);
  text-decoration: none;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.header-title h2 {
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

/* Tabs */
.tab-nav {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 1rem;
}

.tab-list {
  display: flex;
  gap: 0.5rem;
  white-space: nowrap;
  list-style: none;
  padding: 0;
  margin: 0;
  border-bottom: 1px solid var(--pico-muted-border-color, #e2e8f0);
}

.tab-list a {
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 1rem;
  min-height: 44px;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-list a.active {
  border-bottom-color: var(--pico-primary);
  color: var(--pico-primary);
  font-weight: 600;
}

.tab-content {
  margin-bottom: 1rem;
}

/* Event info */
.event-info dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  margin: 0 0 1.5rem;
}

.event-info dt {
  font-weight: 600;
  color: var(--pico-muted-color);
}

.event-info dd {
  margin: 0;
}

/* Action buttons */
.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.action-buttons button {
  width: auto;
}

/* Messages tab */
.messages-tab-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}

.messages-tab-header button {
  width: auto;
}

/* Sticky footer */
.sticky-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--pico-background-color, #fff);
  border-top: 1px solid var(--pico-muted-border-color, #e2e8f0);
  padding: 0.75rem 1rem;
  z-index: 50;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.sticky-footer > button {
  width: auto;
  margin: 0;
}

.destructive-actions {
  margin-left: auto;
}

.destructive-actions summary {
  cursor: pointer;
  font-size: var(--text-sm, 0.875rem);
  color: var(--pico-muted-color);
}

.destructive-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding-top: 0.5rem;
}

.destructive-buttons button {
  width: auto;
  margin: 0;
}

/* Modal styles */
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

@media (max-width: 640px) {
  .event-info dl {
    grid-template-columns: 1fr;
    gap: 0.25rem;
  }

  .event-info dt {
    margin-top: 0.5rem;
  }

  .sticky-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .destructive-actions {
    margin-left: 0;
  }
}
</style>

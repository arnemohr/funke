<template>
  <article class="event-detail-page">
    <PageHeader back="/admin/events" back-label="Events">
      <template #title>
        <span v-if="event">{{ event.name }}</span>
        <span v-else-if="loading" class="skeleton skeleton-title" />
      </template>
      <template #chip>
        <span
          v-if="event"
          :class="['status-badge', `status-${event.status.toLowerCase()}`]"
        >
          {{ formatEventStatus(event.status) }}
        </span>
      </template>
      <template #actions>
        <HelpButton @click="help.toggle(activeHelpKey)" />
      </template>
    </PageHeader>

    <HelpPanel
      :help-key="help.helpKey.value"
      :open="help.isOpen.value"
      ref="helpPanelRef"
      @close="help.close()"
    />

    <!-- Skeleton while loading -->
    <div v-if="loading" class="skeleton-container" aria-busy="true" aria-label="Veranstaltung wird geladen">
      <div class="skeleton skeleton-tab-row" />
      <div class="skeleton-card">
        <div class="skeleton skeleton-row" />
        <div class="skeleton skeleton-row short" />
        <div class="skeleton skeleton-row" />
        <div class="skeleton skeleton-row short" />
      </div>
    </div>

    <div v-else-if="loadError" role="alert" class="error">
      {{ loadError }}
    </div>

    <template v-else-if="event">
      <!-- In-page tabs -->
      <nav class="tab-nav" aria-label="Tabs">
        <ul class="tab-list">
          <li>
            <a
              href="#"
              :class="{ active: activeTab === 'details' }"
              :aria-current="activeTab === 'details' ? 'page' : undefined"
              @click.prevent="activeTab = 'details'"
            >
              Details
            </a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: activeTab === 'registrations' }"
              :aria-current="activeTab === 'registrations' ? 'page' : undefined"
              @click.prevent="activeTab = 'registrations'"
            >
              Anmeldungen
              <span v-if="registrations.length" class="tab-badge">{{ registrations.length }}</span>
            </a>
          </li>
          <li>
            <a
              href="#"
              :class="{ active: activeTab === 'messages' }"
              :aria-current="activeTab === 'messages' ? 'page' : undefined"
              @click.prevent="activeTab = 'messages'"
            >
              Nachrichten
            </a>
          </li>
        </ul>
      </nav>

      <!-- Details tab -->
      <div v-show="activeTab === 'details'" class="tab-content">
        <!-- Info card -->
        <section class="card">
          <header class="card-header">
            <h3>Informationen</h3>
            <button
              type="button"
              class="link-btn"
              @click="actions.goToEdit(event)"
            >
              Bearbeiten
            </button>
          </header>
          <dl class="event-info">
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

            <dt v-if="event.description">Beschreibung</dt>
            <dd v-if="event.description">{{ event.description }}</dd>
          </dl>
        </section>

        <!-- Share card -->
        <section class="card">
          <header class="card-header">
            <h3>Teilen</h3>
          </header>
          <div class="action-row">
            <button class="secondary outline" @click="actions.copyRegistrationLink(event)">
              <span class="btn-icon" aria-hidden="true">🔗</span>
              Link kopieren
            </button>
            <button class="secondary outline" @click="actions.copyInviteText(event)">
              <span class="btn-icon" aria-hidden="true">✉️</span>
              Einladungstext
            </button>
          </div>
        </section>

        <!-- Export & duplicate card -->
        <section class="card">
          <header class="card-header">
            <h3>Weiteres</h3>
          </header>
          <div class="action-row">
            <button class="secondary outline" @click="actions.showCloneModal(event)">
              <span class="btn-icon" aria-hidden="true">📋</span>
              Duplizieren
            </button>
            <button class="secondary outline" @click="actions.handleExportPdf()">
              <span class="btn-icon" aria-hidden="true">📄</span>
              Boardingzettel PDF
            </button>
          </div>
        </section>

        <!-- Danger zone (only render if any destructive action applies) -->
        <section v-if="hasDangerActions" class="card card-danger">
          <header class="card-header">
            <h3>Gefahrenzone</h3>
          </header>
          <div class="action-row">
            <button
              v-if="event.status === 'CONFIRMED'"
              class="btn-danger outline"
              @click="actions.goToDiscard(event)"
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
        </section>
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
          <button @click="actions.showMessageComposer.value = true">
            Nachricht senden
          </button>
        </div>
        <MessageLog mode="inline" :event-id="props.eventId" />
      </div>

      <!-- Sticky primary CTA — single button, no dropdown -->
      <div v-if="primaryCta" class="sticky-cta">
        <button
          :disabled="primaryCta.busy"
          :aria-busy="primaryCta.busy"
          @click="primaryCta.run"
        >
          {{ primaryCta.busy ? primaryCta.busyLabel : primaryCta.label }}
        </button>
      </div>
    </template>

    <!-- ===== Confirm-only modals remain (lightweight) ===== -->

    <!-- Clone -->
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

    <!-- Cancel -->
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

    <!-- Delete -->
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
import PageHeader from '../../components/PageHeader.vue'
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

const hasDangerActions = computed(() => {
  if (!event.value) return false
  // Delete is always available; danger zone always shows.
  return true
})

// Primary CTA — one button in sticky footer, status-aware
const primaryCta = computed(() => {
  if (!event.value) return null
  const e = event.value
  if (e.status === 'DRAFT') {
    return {
      label: 'Veröffentlichen',
      busyLabel: 'Wird veröffentlicht…',
      busy: actions.publishing.value,
      run: () => actions.publishEvent(e),
    }
  }
  if (e.status === 'OPEN') {
    return {
      label: 'Anmeldung schließen',
      busyLabel: 'Wird geschlossen…',
      busy: actions.closingRegistration.value,
      run: () => actions.closeRegistration(e),
    }
  }
  if (e.status === 'REGISTRATION_CLOSED' || e.status === 'LOTTERY_PENDING') {
    return {
      label: 'Verlosung',
      busyLabel: '',
      busy: false,
      run: () => actions.goToLottery(e),
    }
  }
  if (e.status === 'CONFIRMED') {
    return {
      label: 'Abschließen',
      busyLabel: 'Wird abgeschlossen…',
      busy: actions.completing.value,
      run: () => actions.completeEvent(e),
    }
  }
  return null
})

function onMessageSent() {
  showToast('Nachricht wurde gesendet', 'success')
  refreshRegistrations()
}

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
  /* Space for sticky CTA (3.5rem) + bottom tab bar (3.5rem) + breathing room */
  padding-bottom: 8rem;
}

/* Tab nav */
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
  gap: 0.35rem;
  padding: 0.5rem 1rem;
  min-height: 44px;
  text-decoration: none;
  color: var(--color-text-muted, #5C6470);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-list a.active {
  border-bottom-color: var(--color-brand, #0C1E3C);
  color: var(--color-brand, #0C1E3C);
  font-weight: 600;
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.25rem;
  height: 1.25rem;
  padding: 0 0.35rem;
  background: var(--color-border, #DFE2E6);
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-brand, #0C1E3C);
}

.tab-list a.active .tab-badge {
  background: var(--color-brand, #0C1E3C);
  color: white;
}

.tab-content {
  margin-bottom: 1rem;
}

/* Cards */
.card {
  background: white;
  border: 1px solid var(--color-border, #DFE2E6);
  border-radius: var(--pico-border-radius);
  padding: 1rem;
  margin-bottom: 0.75rem;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.card-header h3 {
  margin: 0;
  font-size: 0.95rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--color-text-muted, #5C6470);
}

.card-danger {
  border-color: #fecaca;
  background: #fff9f9;
}

.card-danger .card-header h3 {
  color: var(--pico-color-red-500, #dc3545);
}

/* Info dl */
.event-info {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  margin: 0;
}

.event-info dt {
  font-weight: 600;
  color: var(--color-text-muted, #5C6470);
}

.event-info dd {
  margin: 0;
}

.link-btn {
  background: none;
  border: none;
  color: var(--color-brand, #0C1E3C);
  font-size: var(--text-sm, 0.875rem);
  font-weight: 500;
  padding: 0.25rem 0;
  cursor: pointer;
  width: auto;
  margin: 0;
  min-width: 0;
  min-height: 44px;
}

.link-btn:hover {
  text-decoration: underline;
}

/* Action rows */
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.action-row button {
  width: auto;
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-icon {
  display: inline-block;
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

/* Sticky CTA — sits directly above the bottom tab bar */
.sticky-cta {
  position: fixed;
  bottom: calc(3.5rem + env(safe-area-inset-bottom, 0));
  left: 0;
  right: 0;
  z-index: 50;
  padding: 0.75rem 1rem;
  background: white;
  border-top: 1px solid var(--color-border, #DFE2E6);
}

.sticky-cta button {
  width: 100%;
  margin: 0;
  min-height: 48px;
}

/* Skeleton loaders */
.skeleton-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.skeleton {
  background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%);
  background-size: 200% 100%;
  border-radius: 4px;
  animation: skeleton-shimmer 1.5s infinite;
}

.skeleton-title {
  display: inline-block;
  width: 12rem;
  height: 1.5rem;
  vertical-align: middle;
}

.skeleton-tab-row {
  height: 44px;
  width: 100%;
  max-width: 24rem;
}

.skeleton-card {
  padding: 1rem;
  border: 1px solid var(--color-border, #DFE2E6);
  border-radius: var(--pico-border-radius);
  background: white;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.skeleton-row {
  height: 1rem;
  width: 100%;
}

.skeleton-row.short {
  width: 60%;
}

@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Error state */
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

dialog article { max-width: min(600px, calc(100vw - 2rem)); }

dialog footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .event-info {
    grid-template-columns: 1fr;
    gap: 0.25rem;
  }

  .event-info dt {
    margin-top: 0.5rem;
  }

  .action-row button {
    flex: 1;
    justify-content: center;
  }
}
</style>

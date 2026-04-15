<template>
  <dialog :open="!!event">
    <article class="modal-article">
      <header class="modal-header">
        <a
          href="#"
          aria-label="Schließen"
          class="close"
          @click.prevent="$emit('close')"
        />
        <h3>Anmeldungen: {{ event?.name }}</h3>
        <HelpButton @click="help.toggle('event-detail')" />
      </header>

      <HelpPanel
        :help-key="help.helpKey.value"
        :open="help.isOpen.value"
        ref="helpPanelRef"
        @close="help.close()"
      />

      <!-- Event Info Summary -->
      <div class="event-info-summary" v-if="event">
        <div class="event-info-row">
          <span class="event-info-label">Datum:</span>
          <span>{{ formatDate(event.start_at) }}</span>
        </div>
        <div class="event-info-row">
          <span class="event-info-label">Kapazität:</span>
          <span>{{ participatingSpots }} / {{ event.capacity }} bestätigt<template v-if="pendingSpots > 0">, {{ pendingSpots }} ausstehend</template></span>
        </div>
        <div class="event-info-row" v-if="event.waitlist_count > 0">
          <span class="event-info-label">Warteliste:</span>
          <span>{{ event.waitlist_spots }} Personen ({{ event.waitlist_count }} Buchungen)</span>
        </div>
        <div class="event-info-row" v-if="event.promoted_count > 0">
          <span class="event-info-label">Bevorzugt:</span>
          <span>{{ event.promoted_count }} Anmeldungen ({{ event.promoted_spots }} Plätze)</span>
        </div>
        <div class="event-info-row">
          <span class="event-info-label">Erinnerungen:</span>
          <span>{{ formatReminderSchedule(event.reminder_schedule_days) }} Tage vorher</span>
        </div>
      </div>

      <div class="table-scroll-wrapper">
      <RegistrationTable
        :registrations="registrations"
        :event-status="event?.status"
        :loading="loading"
        :error="error"
        :toggling-id="togglingId"
        @toggle-promoted="$emit('toggle-promoted', $event)"
        @promote-waitlisted="$emit('promote-waitlisted', $event)"
        @delete-registration="$emit('delete-registration', $event)"
      />
      </div>

      <footer>
        <!-- Tier 1: Primary workflow action -->
        <div class="tier-primary" v-if="!['COMPLETED', 'CANCELLED'].includes(event?.status)">
          <button
            v-if="event?.status === 'DRAFT'"
            @click="$emit('publish', event)"
            :disabled="publishing"
          >
            {{ publishing ? 'Wird veröffentlicht...' : 'Veröffentlichen' }}
          </button>
          <button
            v-if="event?.status === 'OPEN'"
            @click="$emit('close-registration', event)"
            :disabled="closingRegistration"
          >
            {{ closingRegistration ? 'Wird geschlossen...' : 'Anmeldung schließen' }}
          </button>
          <button
            v-if="['REGISTRATION_CLOSED', 'LOTTERY_PENDING'].includes(event?.status)"
            @click="$emit('go-to-lottery', event)"
          >
            Verlosung
          </button>
          <button
            v-if="event?.status === 'CONFIRMED'"
            @click="$emit('complete-event', event)"
            :disabled="completing"
            :aria-busy="completing"
          >
            {{ completing ? 'Wird abgeschlossen...' : 'Abschließen' }}
          </button>
        </div>

        <!-- Tier 2: Common utility actions -->
        <div class="tier-utility">
          <div class="tier-utility-primary">
            <button
              v-if="['DRAFT', 'OPEN'].includes(event?.status)"
              @click="$emit('edit', event)"
              class="outline"
            >
              Bearbeiten
            </button>
            <button
              @click="$emit('clone', event)"
              class="outline secondary"
            >
              Duplizieren
            </button>
            <button
              @click="$emit('export-csv', event)"
              class="outline"
              :disabled="registrations.length === 0"
              title="PDF-Liste aller Teilnehmenden für den Check-in"
            >
              Boardingzettel
            </button>
          </div>
          <div class="tier-utility-secondary">
            <button
              v-if="event?.registration_link_token && !['DRAFT', 'COMPLETED', 'CANCELLED'].includes(event?.status)"
              @click="$emit('copy-link', event)"
              class="outline"
            >
              {{ event?.status === 'OPEN' ? 'Link kopieren' : 'Link kopieren (Warteliste)' }}
            </button>
            <button
              v-if="event?.registration_link_token && !['DRAFT', 'COMPLETED', 'CANCELLED'].includes(event?.status)"
              @click="$emit('copy-invite', event)"
              class="outline"
              title="Vorformulierter Text zum Teilen in Chats"
            >
              Einladungstext
            </button>
            <button
              @click="$emit('send-message', event)"
              class="outline"
              :disabled="registrations.length === 0"
            >
              Nachricht senden
            </button>
            <button
              @click="$emit('show-messages', event)"
              class="outline"
            >
              Nachrichten
            </button>
            <button
              v-if="event?.status === 'CONFIRMED'"
              @click="$emit('go-to-lottery', event)"
              class="outline secondary"
            >
              Verlosung ansehen
            </button>
          </div>
        </div>

        <!-- Tier 3: Destructive/rare actions -->
        <details
          v-if="event?.status !== 'COMPLETED'"
          class="tier-destructive"
        >
          <summary>Weitere Aktionen</summary>
          <div class="tier-destructive-actions">
            <button
              v-if="event?.status === 'CONFIRMED'"
              @click="$emit('discard-unacknowledged', event)"
              class="outline btn-danger"
            >
              Unbestätigte verwerfen
            </button>
            <button
              v-if="!['COMPLETED', 'CANCELLED'].includes(event?.status)"
              @click="$emit('cancel-event', event)"
              class="outline btn-danger"
            >
              Absagen
            </button>
            <button
              v-if="event?.status === 'CANCELLED'"
              @click="$emit('delete', event)"
              class="btn-danger"
            >
              Löschen
            </button>
          </div>
        </details>

      </footer>
    </article>
  </dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { formatDate } from '../utils/formatters.js'
import RegistrationTable from './RegistrationTable.vue'
import HelpButton from './help/HelpButton.vue'
import HelpPanel from './help/HelpPanel.vue'
import { useHelp } from './help/useHelp.js'

const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const props = defineProps({
  event: { type: Object, default: null },
  registrations: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  publishing: { type: Boolean, default: false },
  closingRegistration: { type: Boolean, default: false },
  completing: { type: Boolean, default: false },
  togglingId: { type: String, default: null },
})

defineEmits([
  'close', 'edit', 'publish', 'clone', 'cancel-event', 'delete',
  'close-registration', 'copy-link', 'copy-invite', 'go-to-lottery', 'complete-event',
  'export-csv', 'send-message', 'show-messages',
  'toggle-promoted', 'promote-waitlisted', 'discard-unacknowledged', 'delete-registration',
])

function spotsBy(status) {
  return props.registrations
    .filter(r => r.status === status)
    .reduce((sum, r) => sum + r.group_size, 0)
}

const participatingSpots = computed(() => spotsBy('PARTICIPATING'))
const pendingSpots = computed(() => spotsBy('CONFIRMED'))

function formatReminderSchedule(days) {
  if (!days || !Array.isArray(days) || days.length === 0) return '7, 3, 1'
  return days.join(', ')
}
</script>

<style scoped>
/* Modal article — replaces the old inline style */
.modal-article {
  max-width: min(1100px, calc(100vw - 2rem));
  width: 100%;
  position: relative;
}

/* Table scroll wrapper */
.table-scroll-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.modal-header h3 {
  flex: 1;
  margin: 0;
}

footer {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1rem;
}

.tier-primary {
  display: flex;
}

.tier-primary button {
  width: 100%;
  min-height: 44px;
  margin: 0;
}

.tier-utility {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.tier-utility-primary,
.tier-utility-secondary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.tier-utility button {
  margin: 0;
  min-height: 44px;
}

.tier-destructive {
  margin-bottom: 0;
}

.tier-destructive summary {
  cursor: pointer;
  color: #64748b;
  font-size: 0.875rem;
}

.tier-destructive-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}

.tier-destructive-actions button {
  margin: 0;
}

/* On desktop: restore horizontal layout with divider */
@media (min-width: 641px) {
  .tier-utility {
    flex-direction: row;
    align-items: flex-start;
    gap: 0.5rem;
  }
  .tier-utility-secondary {
    padding-left: 0.5rem;
    border-left: 1px solid var(--color-border);
  }
}

/* Mobile specific */
@media (max-width: 640px) {
  .event-info-label {
    min-width: 80px;
  }
  .tier-destructive-actions button {
    width: 100%;
    min-height: 44px;
  }
}

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
</style>

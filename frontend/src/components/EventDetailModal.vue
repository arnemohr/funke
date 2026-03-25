<template>
  <dialog :open="!!event">
    <article style="max-width: 900px;">
      <header>
        <a
          href="#"
          aria-label="Schließen"
          class="close"
          @click.prevent="$emit('close')"
        />
        <h3>Anmeldungen: {{ event?.name }}</h3>
      </header>

      <!-- Event Info Summary -->
      <div class="event-info-summary" v-if="event">
        <div class="event-info-row">
          <span class="event-info-label">Datum:</span>
          <span>{{ formatDate(event.start_at) }}</span>
        </div>
        <div class="event-info-row">
          <span class="event-info-label">Anmeldungen:</span>
          <span>{{ event.registration_spots }} Personen ({{ event.registration_count }} Buchungen)</span>
        </div>
        <div class="event-info-row">
          <span class="event-info-label">Bestätigt:</span>
          <span>{{ event.confirmed_spots }} / {{ event.capacity }} Plätze</span>
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

      <RegistrationTable
        :registrations="registrations"
        :event-status="event?.status"
        :loading="loading"
        :error="error"
        :toggling-id="togglingId"
        @toggle-promoted="$emit('toggle-promoted', $event)"
        @promote-waitlisted="$emit('promote-waitlisted', $event)"
      />

      <footer>
        <div class="modal-actions">
          <button
            v-if="['DRAFT', 'OPEN'].includes(event?.status)"
            @click="$emit('edit', event)"
            class="outline"
          >
            Bearbeiten
          </button>
          <button
            v-if="event?.status === 'DRAFT'"
            @click="$emit('publish', event)"
            class="secondary"
            :disabled="publishing"
          >
            {{ publishing ? 'Wird veröffentlicht...' : 'Veröffentlichen' }}
          </button>
          <button
            v-if="event?.registration_link_token && !['DRAFT', 'COMPLETED', 'CANCELLED'].includes(event?.status)"
            @click="$emit('copy-link', event)"
            class="outline"
          >
            {{ event?.status === 'OPEN' ? 'Link kopieren' : 'Link kopieren (Warteliste)' }}
          </button>
          <button
            v-if="event?.status === 'OPEN'"
            @click="$emit('close-registration', event)"
            class="secondary"
            :disabled="closingRegistration"
          >
            {{ closingRegistration ? 'Wird geschlossen...' : 'Anmeldung schließen' }}
          </button>
          <button
            @click="$emit('clone', event)"
            class="outline secondary"
          >
            Duplizieren
          </button>
          <button
            v-if="['REGISTRATION_CLOSED', 'LOTTERY_PENDING'].includes(event?.status)"
            @click="$emit('go-to-lottery', event)"
            class="outline"
          >
            Verlosung
          </button>
          <button
            v-if="event?.status === 'CONFIRMED'"
            @click="$emit('go-to-lottery', event)"
            class="outline secondary"
          >
            Verlosung ansehen
          </button>
          <button
            v-if="event?.status === 'CONFIRMED'"
            @click="$emit('discard-unacknowledged', event)"
            class="outline cancel-btn"
          >
            Unbestätigte verwerfen
          </button>
          <button
            v-if="event?.status === 'CONFIRMED'"
            @click="$emit('complete-event', event)"
            class="outline"
            :disabled="completing"
            :aria-busy="completing"
          >
            {{ completing ? 'Wird abgeschlossen...' : 'Abschließen' }}
          </button>
          <button
            @click="$emit('export-csv', event)"
            class="outline"
            :disabled="registrations.length === 0"
          >
            CSV Export
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
            v-if="!['COMPLETED', 'CANCELLED'].includes(event?.status)"
            @click="$emit('cancel-event', event)"
            class="outline cancel-btn"
          >
            Absagen
          </button>
          <button
            v-if="event?.status === 'CANCELLED'"
            @click="$emit('delete', event)"
            class="outline delete-btn"
          >
            Löschen
          </button>
        </div>
        <button @click="$emit('close')">Schließen</button>
      </footer>
    </article>
  </dialog>
</template>

<script setup>
import RegistrationTable from './RegistrationTable.vue'

defineProps({
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
  'close-registration', 'copy-link', 'go-to-lottery', 'complete-event',
  'export-csv', 'send-message', 'show-messages',
  'toggle-promoted', 'promote-waitlisted', 'discard-unacknowledged',
])

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

function formatReminderSchedule(days) {
  if (!days || !Array.isArray(days) || days.length === 0) return '7, 3, 1'
  return days.join(', ')
}
</script>

<style scoped>
.modal-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.modal-actions button {
  margin: 0;
}

.cancel-btn {
  border-color: #dc2626 !important;
  color: #dc2626 !important;
}

.cancel-btn:hover {
  background: #dc2626 !important;
  color: white !important;
}

.outline.delete-btn {
  background: transparent !important;
  color: #dc2626 !important;
  border-color: #dc2626 !important;
}

.outline.delete-btn:hover {
  background: #dc2626 !important;
  color: white !important;
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

footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}
</style>

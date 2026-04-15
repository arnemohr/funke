<template>
  <form @submit.prevent="$emit('submit', formData)" class="compact-form">
    <div class="form-row">
      <label :for="`${prefix}Name`">
        Name *
        <input
          :id="`${prefix}Name`"
          v-model="form.name"
          type="text"
          required
          placeholder="Schaluppen Tour"
          :disabled="disabled"
        />
      </label>
      <label :for="`${prefix}Location`">
        Ort
        <input
          :id="`${prefix}Location`"
          v-model="form.location"
          type="text"
          placeholder="Hamburger Hafen"
          :disabled="disabled"
        />
      </label>
    </div>

    <label :for="`${prefix}Description`">
      Beschreibung
      <textarea
        :id="`${prefix}Description`"
        v-model="form.description"
        rows="2"
        placeholder="dies das ..."
        :disabled="disabled"
      />
    </label>

    <div class="form-row">
      <label :for="`${prefix}StartAt`">
        Datum & Uhrzeit *
        <input
          :id="`${prefix}StartAt`"
          v-model="form.startAt"
          type="datetime-local"
          required
          :disabled="disabled"
        />
      </label>
      <label :for="`${prefix}Capacity`">
        Plätze *
        <input
          :id="`${prefix}Capacity`"
          v-model.number="form.capacity"
          type="number"
          min="1"
          max="500"
          required
          :disabled="disabled"
        />
      </label>
    </div>

    <div class="form-row">
      <label :for="`${prefix}RegistrationDeadline`">
        Anmeldeschluss *
        <input
          :id="`${prefix}RegistrationDeadline`"
          v-model="form.registrationDeadline"
          type="datetime-local"
          required
          :disabled="disabled"
        />
      </label>
      <label :for="`${prefix}ReminderSchedule`">
        Erinnerungen (Tage vorher)
        <input
          :id="`${prefix}ReminderSchedule`"
          v-model="form.reminderSchedule"
          type="text"
          placeholder="7, 3, 1"
          :disabled="disabled"
        />
      </label>
    </div>

    <label class="checkbox-label">
      <input
        v-model="form.autopromoteWaitlist"
        type="checkbox"
        :disabled="disabled"
      />
      Automatisch von der Warteliste nachrücken lassen
    </label>

    <div v-if="error" role="alert" class="error">
      {{ error }}
    </div>

    <footer>
      <button
        type="button"
        class="secondary"
        @click="$emit('cancel')"
        :disabled="disabled"
      >
        Abbrechen
      </button>
      <button type="submit" :disabled="disabled" :aria-busy="disabled">
        {{ disabled ? submitBusyLabel : submitLabel }}
      </button>
    </footer>
  </form>
</template>

<script setup>
import { reactive, computed, watch } from 'vue'
import { berlinToUTCISO } from '../utils/formatters.js'

const props = defineProps({
  event: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
  error: { type: String, default: null },
  submitLabel: { type: String, default: 'Erstellen' },
  submitBusyLabel: { type: String, default: 'Wird erstellt...' },
})

const emit = defineEmits(['submit', 'cancel'])

const prefix = computed(() => props.event ? 'edit' : 'create')

function formatDateTimeLocal(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const parts = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Berlin',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date)
  const get = (type) => parts.find(p => p.type === type).value
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
}

function formatReminderSchedule(days) {
  if (!days || !Array.isArray(days) || days.length === 0) return '7, 3, 1'
  return days.join(', ')
}

function parseReminderSchedule(scheduleStr) {
  if (!scheduleStr || !scheduleStr.trim()) return [7, 3, 1]
  const days = scheduleStr.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n) && n > 0)
  return days.length > 0 ? days : [7, 3, 1]
}

const form = reactive(
  props.event
    ? {
        name: props.event.name,
        description: props.event.description || '',
        location: props.event.location || '',
        startAt: formatDateTimeLocal(props.event.start_at),
        capacity: props.event.capacity,
        registrationDeadline: formatDateTimeLocal(props.event.registration_deadline),
        autopromoteWaitlist: props.event.autopromote_waitlist,
        reminderSchedule: formatReminderSchedule(props.event.reminder_schedule_days),
      }
    : {
        name: '',
        description: '',
        location: '',
        startAt: '',
        capacity: 80,
        registrationDeadline: '',
        autopromoteWaitlist: false,
        reminderSchedule: '7, 3, 1',
      },
)

// Re-initialize when event prop changes (e.g. opening edit modal for different event)
watch(
  () => props.event,
  (newEvent) => {
    if (newEvent) {
      form.name = newEvent.name
      form.description = newEvent.description || ''
      form.location = newEvent.location || ''
      form.startAt = formatDateTimeLocal(newEvent.start_at)
      form.capacity = newEvent.capacity
      form.registrationDeadline = formatDateTimeLocal(newEvent.registration_deadline)
      form.autopromoteWaitlist = newEvent.autopromote_waitlist
      form.reminderSchedule = formatReminderSchedule(newEvent.reminder_schedule_days)
    }
  },
)

const formData = computed(() => ({
  name: form.name.trim(),
  description: form.description?.trim() || null,
  location: form.location?.trim() || null,
  start_at: berlinToUTCISO(form.startAt),
  capacity: form.capacity,
  registration_deadline: berlinToUTCISO(form.registrationDeadline),
  autopromote_waitlist: form.autopromoteWaitlist,
  reminder_schedule_days: parseReminderSchedule(form.reminderSchedule),
}))
</script>

<style scoped>
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

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }

  input, textarea, select {
    font-size: 1rem;     /* prevents iOS Safari auto-zoom on focus */
    min-height: 48px;
  }
}
</style>

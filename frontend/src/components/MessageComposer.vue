<template>
  <dialog :open="open">
    <article>
      <header>
        <a
          href="#"
          aria-label="Schließen"
          class="close"
          @click.prevent="$emit('close')"
        />
        <h3>Nachricht senden</h3>
      </header>

      <form @submit.prevent="handleSend">
        <!-- Recipient selection -->
        <fieldset>
          <legend>Empfänger</legend>
          <label class="select-all-label">
            <input
              type="checkbox"
              :checked="allSelected"
              @change="toggleAll"
              :disabled="sending"
            />
            Alle auswählen ({{ registrations.length }})
          </label>
          <div class="recipient-list">
            <label v-for="reg in registrations" :key="reg.id" class="recipient-item">
              <input
                type="checkbox"
                :value="reg.id"
                v-model="selectedIds"
                :disabled="sending"
              />
              {{ reg.name }} ({{ reg.email }})
              <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                {{ reg.status }}
              </span>
            </label>
          </div>
        </fieldset>

        <label for="msgSubject">
          Betreff *
          <input
            id="msgSubject"
            v-model="subject"
            type="text"
            required
            placeholder="Betreff der Nachricht"
            :disabled="sending"
          />
        </label>

        <label for="msgBody">
          Nachricht *
          <textarea
            id="msgBody"
            v-model="body"
            rows="5"
            required
            placeholder="Deine Nachricht..."
            :disabled="sending"
          />
        </label>

        <div v-if="error" role="alert" class="error">
          {{ error }}
        </div>

        <div v-if="result" role="status" class="success">
          {{ result.sent }} von {{ result.total }} Nachrichten gesendet.
          <span v-if="result.failed"> ({{ result.failed }} fehlgeschlagen)</span>
        </div>

        <footer>
          <button
            type="button"
            class="secondary"
            @click="$emit('close')"
            :disabled="sending"
          >
            Abbrechen
          </button>
          <button
            type="submit"
            :disabled="sending || selectedIds.length === 0"
            :aria-busy="sending"
          >
            {{ sending ? 'Wird gesendet...' : `Senden (${selectedIds.length})` }}
          </button>
        </footer>
      </form>
    </article>
  </dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { adminApi } from '../services/api'

const props = defineProps({
  open: { type: Boolean, default: false },
  eventId: { type: String, default: null },
  registrations: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'sent'])

const selectedIds = ref([])
const subject = ref('')
const body = ref('')
const sending = ref(false)
const error = ref(null)
const result = ref(null)

const allSelected = computed(() =>
  props.registrations.length > 0 && selectedIds.value.length === props.registrations.length,
)

function toggleAll(e) {
  if (e.target.checked) {
    selectedIds.value = props.registrations.map(r => r.id)
  } else {
    selectedIds.value = []
  }
}

async function handleSend() {
  if (!props.eventId || selectedIds.value.length === 0) return

  sending.value = true
  error.value = null
  result.value = null

  try {
    const res = await adminApi.sendCustomMessage(props.eventId, {
      registration_ids: selectedIds.value,
      subject: subject.value,
      body: body.value,
    })
    result.value = res
    emit('sent', res)

    // Reset form on success
    if (res.failed === 0) {
      subject.value = ''
      body.value = ''
      selectedIds.value = []
    }
  } catch (err) {
    error.value = err.message || 'Nachricht konnte nicht gesendet werden'
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
fieldset {
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  padding: 0.75rem;
  margin-bottom: 1rem;
}

legend {
  font-weight: 600;
  padding: 0 0.5rem;
}

.select-all-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.recipient-list {
  max-height: 200px;
  overflow-y: auto;
}

.recipient-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
  font-size: 0.875rem;
}

.recipient-item input[type="checkbox"] {
  margin: 0;
}

.status-badge {
  display: inline-block;
  padding: 0.1rem 0.3rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.65rem;
  font-weight: bold;
  text-transform: uppercase;
}

.status-confirmed { background: #fef3c7; color: #d97706; }
.status-participating { background: #dcfce7; color: #16a34a; }
.status-waitlisted { background: #e5e7eb; color: #6b7280; }
.status-registered { background: #e0e7ff; color: #4f46e5; }

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.success {
  color: #16a34a;
  padding: 1rem;
  background: #f0fdf4;
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
}
</style>

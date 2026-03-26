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
          <select v-model="statusFilter" :disabled="sending" class="status-filter">
            <option value="">Alle Status</option>
            <option value="REGISTERED">Angemeldet</option>
            <option value="CONFIRMED">Bestätigung ausstehend</option>
            <option value="PARTICIPATING">Nimmt teil</option>
            <option value="WAITLISTED">Warteliste</option>
            <option value="CHECKED_IN">Eingecheckt</option>
          </select>
          <label class="select-all-label">
            <input
              type="checkbox"
              :checked="allSelected"
              @change="toggleAll"
              :disabled="sending"
            />
            Alle auswählen ({{ filteredRegistrations.length }})
          </label>
          <div class="recipient-list">
            <label v-for="reg in filteredRegistrations" :key="reg.id" class="recipient-item">
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

        <label class="checkbox-label">
          <input
            type="checkbox"
            v-model="includeLinks"
            :disabled="sending"
          />
          Verwaltungslink einfügen
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
import { ref, computed, watch } from 'vue'
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
const includeLinks = ref(false)
const sending = ref(false)
const error = ref(null)
const result = ref(null)
const statusFilter = ref('')

const activeRegistrations = computed(() =>
  props.registrations.filter(r => r.status !== 'CANCELLED'),
)

const filteredRegistrations = computed(() => {
  if (!statusFilter.value) return activeRegistrations.value
  return activeRegistrations.value.filter(r => r.status === statusFilter.value)
})

const allSelected = computed(() => {
  const visible = filteredRegistrations.value
  return visible.length > 0 && visible.every(r => selectedIds.value.includes(r.id))
})

function toggleAll(e) {
  const visibleIds = filteredRegistrations.value.map(r => r.id)
  if (e.target.checked) {
    const existing = selectedIds.value.filter(id => !visibleIds.includes(id))
    selectedIds.value = [...existing, ...visibleIds]
  } else {
    selectedIds.value = selectedIds.value.filter(id => !visibleIds.includes(id))
  }
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    statusFilter.value = ''
  }
})

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
      include_links: includeLinks.value,
    })
    result.value = res
    emit('sent', res)

    // Reset form on success
    if (res.failed === 0) {
      subject.value = ''
      body.value = ''
      includeLinks.value = false
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

.status-filter {
  margin-bottom: 0.5rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
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

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  margin-bottom: 1rem;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  margin: 0;
}

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

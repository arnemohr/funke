<template>
  <dialog :open="open">
    <article style="max-width: 800px;">
      <header>
        <a
          href="#"
          aria-label="Schließen"
          class="close"
          @click.prevent="$emit('close')"
        />
        <h3>Gesendete Nachrichten</h3>
      </header>

      <div v-if="loading" aria-busy="true">
        Nachrichten werden geladen...
      </div>

      <div v-else-if="error" role="alert" class="error">
        {{ error }}
      </div>

      <template v-else>
        <p v-if="messages.length === 0">
          Noch keine Nachrichten für diese Veranstaltung.
        </p>

        <table v-else>
          <thead>
            <tr>
              <th>Typ</th>
              <th>Betreff</th>
              <th>Empfänger</th>
              <th>Status</th>
              <th>Gesendet am</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="msg in messages" :key="msg.id">
              <td>
                <span class="type-badge">{{ formatType(msg.type) }}</span>
              </td>
              <td>{{ msg.subject }}</td>
              <td>{{ msg.recipient_email || '-' }}</td>
              <td>
                <span :class="['status-badge', `status-${msg.status}`]">
                  {{ formatMsgStatus(msg.status) }}
                </span>
              </td>
              <td>{{ formatDate(msg.sent_at) }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <footer>
        <button @click="$emit('close')">Schließen</button>
      </footer>
    </article>
  </dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { adminApi } from '../services/api'

const props = defineProps({
  open: { type: Boolean, default: false },
  eventId: { type: String, default: null },
})

defineEmits(['close'])

const messages = ref([])
const loading = ref(false)
const error = ref(null)

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen && props.eventId) {
      loading.value = true
      error.value = null
      try {
        const result = await adminApi.listMessages(props.eventId)
        messages.value = result.messages || result
      } catch (err) {
        error.value = err.message || 'Nachrichten konnten nicht geladen werden'
      } finally {
        loading.value = false
      }
    }
  },
)

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('de-DE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatType(type) {
  const labels = {
    'registration_confirmation': 'Bestätigung',
    'waitlist_notification': 'Warteliste',
    'lottery_result': 'Verlosung',
    'reminder': 'Erinnerung',
    'confirmation_request': 'Teilnahme-Anfrage',
    'cancellation': 'Stornierung',
    'custom': 'Eigene',
  }
  return labels[type] || type
}

function formatMsgStatus(status) {
  const labels = {
    'queued': 'In Warteschlange',
    'sent': 'Gesendet',
    'delivered': 'Zugestellt',
    'failed': 'Fehlgeschlagen',
    'bounced': 'Unzustellbar',
  }
  return labels[status] || status
}
</script>

<style scoped>
.type-badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.7rem;
  font-weight: 600;
  background: #e0e7ff;
  color: #4f46e5;
}

.status-badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.7rem;
  font-weight: 600;
}

.status-sent { background: #dcfce7; color: #16a34a; }
.status-delivered { background: #dbeafe; color: #2563eb; }
.status-failed { background: #fee2e2; color: #dc2626; }
.status-bounced { background: #fee2e2; color: #dc2626; }
.status-queued { background: #fef3c7; color: #d97706; }

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
}
</style>

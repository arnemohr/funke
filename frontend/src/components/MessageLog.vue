<template>
  <!-- Modal mode — legacy callers -->
  <dialog v-if="mode === 'modal'" :open="open">
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
      <MessageLogContent
        :messages="messages"
        :loading="loading"
        :error="error"
      />
      <footer>
        <button @click="$emit('close')">Schließen</button>
      </footer>
    </article>
  </dialog>

  <!-- Inline mode — embedded inside page tabs/sections -->
  <MessageLogContent
    v-else
    :messages="messages"
    :loading="loading"
    :error="error"
  />
</template>

<script setup>
import { ref, watch, computed, h } from 'vue'
import { adminApi } from '../services/api'
import { formatDate } from '../utils/formatters.js'

const props = defineProps({
  mode: { type: String, default: 'modal', validator: (v) => ['modal', 'inline'].includes(v) },
  open: { type: Boolean, default: false },
  eventId: { type: String, default: null },
})

defineEmits(['close'])

const messages = ref([])
const loading = ref(false)
const error = ref(null)

// Inline mode loads once when eventId is present; modal mode waits for open.
const shouldLoad = computed(() => {
  if (!props.eventId) return false
  if (props.mode === 'inline') return true
  return props.open
})

async function load() {
  if (!props.eventId) return
  loading.value = true
  error.value = null
  try {
    const result = await adminApi.listMessages(props.eventId)
    messages.value = result.items || []
  } catch (err) {
    error.value = err.message || 'Nachrichten konnten nicht geladen werden'
  } finally {
    loading.value = false
  }
}

watch(shouldLoad, (v) => { if (v) load() }, { immediate: true })
watch(() => props.eventId, () => { if (shouldLoad.value) load() })

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

// Inline render helper — table/empty/error/loading all handled here
const MessageLogContent = {
  props: ['messages', 'loading', 'error'],
  setup(p) {
    return () => {
      if (p.loading) {
        return h('div', { 'aria-busy': 'true' }, 'Nachrichten werden geladen…')
      }
      if (p.error) {
        return h('div', { role: 'alert', class: 'error' }, p.error)
      }
      if (!p.messages || p.messages.length === 0) {
        return h('p', { class: 'muted' }, 'Noch keine Nachrichten für diese Veranstaltung.')
      }
      return h('div', { class: 'message-log-wrap' }, [
        h('table', null, [
          h('thead', null,
            h('tr', null, [
              h('th', null, 'Typ'),
              h('th', null, 'Betreff'),
              h('th', null, 'Empfänger'),
              h('th', null, 'Status'),
              h('th', null, 'Gesendet am'),
            ]),
          ),
          h('tbody', null, p.messages.map(msg =>
            h('tr', { key: msg.id }, [
              h('td', null, h('span', { class: 'type-badge' }, formatType(msg.type))),
              h('td', null, msg.subject),
              h('td', null, msg.recipient_email || '-'),
              h('td', null,
                h('span', { class: ['status-badge', `status-${msg.status}`] }, formatMsgStatus(msg.status)),
              ),
              h('td', null, formatDate(msg.sent_at)),
            ]),
          )),
        ]),
      ])
    }
  },
}
</script>

<style scoped>
.type-badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: var(--pico-border-radius);
  font-size: 0.7rem;
  font-weight: 600;
  background: var(--color-indigo-bg);
  color: var(--color-indigo-text);
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 1rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.muted {
  color: var(--color-text-muted, #5C6470);
}

.message-log-wrap {
  overflow-x: auto;
}

footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
}
</style>

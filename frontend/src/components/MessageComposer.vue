<template>
  <dialog :open="open">
    <article style="position: relative;">
      <header class="modal-header">
        <a
          href="#"
          aria-label="Schließen"
          class="close"
          @click.prevent="$emit('close')"
        />
        <h3>Nachricht senden</h3>
        <HelpButton @click="help.toggle('message-composer')" />
      </header>

      <HelpPanel
        :help-key="help.helpKey.value"
        :open="help.isOpen.value"
        ref="helpPanelRef"
        @close="help.close()"
      />

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
              <span v-if="companionCount(reg)" class="companion-count">
                +{{ companionCount(reg) }}&nbsp;Begleitung{{ companionCount(reg) === 1 ? '' : 'en' }}
                mit E-Mail
              </span>
              <span :class="['status-badge', `status-${reg.status.toLowerCase()}`]">
                {{ formatRegistrationStatus(reg.status) }}
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

        <!-- Spec 020: companions who gave an address are recipients in their own
             right. Their copy carries their read-only Eintritts-Code link, never
             the group's Verwaltungslink. -->
        <label v-if="totalCompanions > 0" class="checkbox-label">
          <input
            type="checkbox"
            v-model="includeCompanions"
            :disabled="sending"
          />
          Begleitungen mit E-Mail mitschicken ({{ totalCompanions }})
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
            {{ sending ? 'Wird gesendet...' : `Senden (${recipientCount})` }}
          </button>
        </footer>
      </form>
    </article>
  </dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { adminApi } from '../services/api'
import { formatRegistrationStatus } from '../utils/formatters.js'
import HelpButton from './help/HelpButton.vue'
import HelpPanel from './help/HelpPanel.vue'
import { useHelp } from './help/useHelp.js'

const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

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
// Default ON: the whole point of collecting companion addresses is that the
// Orga-Rundmail reaches them (spec 020).
const includeCompanions = ref(true)
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

// Spec 020 — how many companions of this registration have their own address.
// Mirrors the backend's `companion_recipients`: an address equal to the
// contact's is skipped there, so skip it here too or the count would overstate.
function companionCount(registration) {
  const contact = (registration.email || '').trim().toLowerCase()
  const seen = new Set()
  for (const email of registration.group_member_emails || []) {
    const normalized = (email || '').trim().toLowerCase()
    if (!normalized || normalized === contact || seen.has(normalized)) continue
    seen.add(normalized)
  }
  return seen.size
}

const totalCompanions = computed(() =>
  activeRegistrations.value
    .filter(r => selectedIds.value.includes(r.id))
    .reduce((sum, r) => sum + companionCount(r), 0),
)

// What the backend will report as `total`, so the button doesn't undercount.
const recipientCount = computed(
  () => selectedIds.value.length + (includeCompanions.value ? totalCompanions.value : 0),
)

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
    subject.value = ''
    body.value = ''
    selectedIds.value = []
    includeLinks.value = false
    includeCompanions.value = true
    error.value = null
    result.value = null
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
      include_companions: includeCompanions.value,
    })
    result.value = res
    emit('sent', res)

    // Reset form on success
    if (res.failed === 0) {
      subject.value = ''
      body.value = ''
      includeLinks.value = false
      includeCompanions.value = true
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
/* Spec 020 — companion count per recipient row, quieter than the status badge. */
.companion-count {
  font-size: 0.8rem;
  color: var(--pico-muted-color, #6b7280);
  margin-left: 0.35rem;
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
  -webkit-overflow-scrolling: touch;
}

.recipient-item {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  min-height: 44px;
  gap: 0.5rem;
  padding: 0.25rem 0;
  font-size: 0.875rem;
}

.recipient-item input[type="checkbox"] {
  margin: 0;
}

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
  color: var(--color-success-text);
  padding: 1rem;
  background: var(--color-success-bg);
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

@media (max-width: 640px) {
  .recipient-list {
    mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
    padding-bottom: 1rem;
  }
}

@media (max-width: 480px) {
  footer {
    flex-direction: column-reverse;
  }
  footer button {
    width: 100%;
    min-height: 44px;
  }
}
</style>

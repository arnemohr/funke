<template>
  <dialog :open="open">
    <article class="batch-modal-article" style="position: relative;">
      <header class="modal-header">
        <a href="#" aria-label="Schließen" class="close" @click.prevent="handleClose"></a>
        <h3>Neue Gästeliste</h3>
      </header>

      <form @submit.prevent="handleCreate">
        <div class="form-row">
          <label for="batchLabel">
            Name der Liste *
            <input
              id="batchLabel"
              v-model="batchLabel"
              type="text"
              required
              placeholder="z.B. Werft-Crew"
              :disabled="creating"
            />
          </label>
          <label for="batchTier">
            Kategorie
            <select id="batchTier" v-model="tier" :disabled="creating">
              <option value="werft">Werft</option>
              <option value="volunteer">Helfer:in</option>
              <option value="org">Organisation</option>
              <option value="open">Offen</option>
            </select>
          </label>
        </div>

        <fieldset class="guests-section">
          <legend>Verantwortliche</legend>

          <div v-for="(guest, i) in guests" :key="guest.key" class="guest-row">
            <div class="guest-inputs">
              <input
                type="text"
                v-model="guest.name"
                placeholder="Name"
                :aria-label="`Name Gast ${i + 1}`"
                :disabled="creating"
                autocomplete="off"
                autocapitalize="words"
                @paste="handleNamePaste($event, i)"
              />
              <input
                type="email"
                v-model="guest.email"
                placeholder="E-Mail (optional)"
                :aria-label="`E-Mail Gast ${i + 1}`"
                :disabled="creating"
                autocomplete="off"
                autocapitalize="off"
              />
            </div>
            <button
              type="button"
              class="outline secondary remove-guest"
              :aria-label="`Gast ${i + 1} entfernen`"
              title="Entfernen"
              :disabled="creating"
              @click="removeGuest(i)"
            >
              <X :size="18" aria-hidden="true" />
            </button>
          </div>

          <button type="button" class="outline add-guest" :disabled="creating" @click="addGuest">
            <Plus :size="18" aria-hidden="true" />
            Verantwortliche:n hinzufügen
          </button>

          <p class="field-hint">
            Jede verantwortliche Person bekommt einen eigenen Einladungslink — für sich selbst
            oder zum Weiterverteilen (je nach Kontingent). Mit E-Mail-Adresse kannst du ihn
            direkt aus der App verschicken, ohne teilst du ihn selbst — z.B. per Telegram.
          </p>
        </fieldset>

        <fieldset class="guests-section">
          <legend>Kontingent pro Link</legend>
          <div class="form-row">
            <label for="batchMaxUses">
              Anmeldungen pro Link
              <input id="batchMaxUses" v-model.number="maxUses" type="number" min="1" :disabled="creating" />
            </label>
            <label for="batchMaxGroupSize">
              Personen pro Anmeldung
              <input id="batchMaxGroupSize" v-model.number="maxGroupSize" type="number" min="1" max="20" :disabled="creating" />
            </label>
          </div>
          <p class="field-hint">
            Beispiel Ticket-Kontingent: 10 Anmeldungen × 2 Personen = die verantwortliche Person
            kann ihren Link an bis zu 10 Leute weitergeben, jede:r darf eine Begleitung mitbringen
            (max. {{ maxSeats }} Plätze). Für persönliche Einzel-Einladungen: beides auf 1 lassen.
          </p>
        </fieldset>

        <label class="send-toggle">
          <input type="checkbox" v-model="sendEmails" role="switch" :disabled="creating" />
          Einladungen direkt per E-Mail verschicken
        </label>
        <p class="field-hint send-hint">
          <template v-if="emailCount > 0">
            {{ emailCount === 1 ? '1 Person hat' : `${emailCount} Personen haben` }} eine E-Mail-Adresse
            — {{ emailCount === 1 ? 'sie bekommt' : 'sie bekommen' }} die Einladung sofort.
            Verantwortliche ohne Adresse teilst du den Link selbst (Kopieren).
          </template>
          <template v-else>
            Noch keine E-Mail-Adressen eingetragen — es wird nichts verschickt. Du kannst die Links
            später mit „Kopieren" selbst teilen.
          </template>
        </p>

        <div v-if="error" role="alert" class="error">{{ error }}</div>

        <footer>
          <button type="button" class="secondary" @click="handleClose" :disabled="creating">
            Abbrechen
          </button>
          <button type="submit" :disabled="creating || validGuests.length === 0" :aria-busy="creating">
            {{ creating ? 'Wird angelegt...' : submitLabel }}
          </button>
        </footer>
      </form>
    </article>
  </dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Plus, X } from 'lucide-vue-next'
import { adminApi } from '../../../services/api'

const props = defineProps({
  open: { type: Boolean, default: false },
  eventId: { type: String, default: null },
})

const emit = defineEmits(['close', 'created'])

let guestKey = 0
function emptyGuest() {
  return { key: guestKey++, name: '', email: '' }
}

const guests = ref([emptyGuest()])
const batchLabel = ref('')
const tier = ref('werft')
const maxUses = ref(1)
const maxGroupSize = ref(1)
const sendEmails = ref(true)
const creating = ref(false)
const error = ref(null)

const validGuests = computed(() =>
  guests.value
    .map((g) => ({ label: g.name.trim(), email: g.email.trim() || null }))
    .filter((g) => g.label),
)

const emailCount = computed(() => validGuests.value.filter((g) => g.email).length)

const maxSeats = computed(() => (maxUses.value || 1) * (maxGroupSize.value || 1))

const submitLabel = computed(() => {
  const n = validGuests.value.length
  if (n === 0) return 'Gästeliste anlegen'
  return n === 1 ? 'Gästeliste anlegen (1 Person)' : `Gästeliste anlegen (${n} Personen)`
})

function addGuest() {
  guests.value.push(emptyGuest())
}

function removeGuest(index) {
  guests.value.splice(index, 1)
  if (guests.value.length === 0) guests.value.push(emptyGuest())
}

const EMAIL_RE = /\S+@\S+\.\S+/

// One pasted line → { name, email }. Accepts "Name <email>", "Name, email",
// "Name; email", tab-separated, "Name email", or a bare email address —
// so a list copied from a spreadsheet, mail client, or chat just works.
function parseGuestLine(line) {
  const trimmed = line.trim()
  if (!trimmed) return null

  let m = trimmed.match(/^(.*?)\s*<\s*(\S+@\S+)\s*>$/)
  if (m) return { name: m[1].trim(), email: m[2] }

  m = trimmed.match(/^(.*?)[,;\t]\s*(\S+@\S+\.\S+)\s*$/)
  if (m) return { name: m[1].trim(), email: m[2] }

  m = trimmed.match(/^(.*\S)\s+(\S+@\S+\.\S+)$/)
  if (m) return { name: m[1].trim(), email: m[2] }

  if (EMAIL_RE.test(trimmed) && !trimmed.includes(' ')) {
    return { name: trimmed.split('@')[0], email: trimmed }
  }

  return { name: trimmed, email: '' }
}

// Pasting multi-line text into a name field expands it into one row per line
// instead of dumping everything into a single input.
function handleNamePaste(event, index) {
  const text = event.clipboardData?.getData('text') ?? ''
  if (!text.includes('\n')) return

  const parsed = text
    .split('\n')
    .map(parseGuestLine)
    .filter(Boolean)
    .map((g) => ({ key: guestKey++, name: g.name, email: g.email }))
  if (parsed.length === 0) return

  event.preventDefault()
  const current = guests.value[index]
  const replaceCount = current && !current.name.trim() && !current.email.trim() ? 1 : 0
  guests.value.splice(index + (1 - replaceCount), replaceCount, ...parsed)
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      guests.value = [emptyGuest()]
      batchLabel.value = ''
      tier.value = 'werft'
      maxUses.value = 1
      maxGroupSize.value = 1
      sendEmails.value = true
      creating.value = false
      error.value = null
    }
  },
)

function handleClose() {
  emit('close')
}

async function handleCreate() {
  if (!props.eventId || validGuests.value.length === 0) return

  creating.value = true
  error.value = null

  try {
    const batch = {
      batch_label: batchLabel.value.trim(),
      send_emails: sendEmails.value,
      invites: validGuests.value.map((row) => ({
        label: row.label,
        email: row.email,
        tier: tier.value,
        max_uses: maxUses.value,
        max_group_size: maxGroupSize.value,
      })),
    }
    const result = await adminApi.festival.createInvites(props.eventId, batch)
    emit('created', result)
  } catch (err) {
    error.value = err.message || 'Gästeliste konnte nicht angelegt werden'
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.batch-modal-article {
  max-width: min(650px, calc(100vw - 2rem));
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.modal-header h3 {
  margin: 0;
  flex: 1;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.guests-section {
  margin: 0 0 1rem;
  padding: 0;
  border: none;
}

.guests-section legend {
  font-weight: 600;
  padding: 0;
  margin-bottom: 0.5rem;
}

.guest-row {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.guest-inputs {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.guest-inputs input {
  margin: 0;
}

.remove-guest {
  width: auto;
  min-width: 44px;
  min-height: 44px;
  margin: 0;
  padding: 0.4rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.add-guest {
  width: auto;
  min-height: 44px;
  margin: 0 0 0.75rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.field-hint {
  font-size: var(--text-sm, 0.875rem);
  color: var(--color-text-muted);
  margin: 0 0 0.5rem;
}

.send-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  margin-bottom: 0.35rem;
}

.send-hint {
  margin-bottom: 1rem;
}

.error {
  color: var(--color-danger-text);
  padding: 0.75rem;
  background: var(--color-danger-bg);
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

footer button {
  min-height: 44px;
}

@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }

  .guest-inputs {
    grid-template-columns: 1fr;
  }

  .guest-row {
    padding: 0.6rem;
    background: var(--color-surface-raised, var(--pico-card-background-color));
    border: 1px solid var(--color-border, var(--pico-muted-border-color));
    border-radius: var(--radius-md, 0.5rem);
  }
}
</style>

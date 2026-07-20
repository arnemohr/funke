<template>
  <article>
    <PageHeader back="/admin/festival" back-label="Festivals">
      <template #title>Neues Festival</template>
    </PageHeader>

    <FestivalHelp title="Kurz erklärt">
      <p>Die Zeitfenster sind später die Kästchen, die Gäste beim Anmelden ankreuzen — normalerweise einfach Freitag, Samstag, Sonntag.</p>
      <p>Kontakt-Adresse und Mitmach-Hinweis bauen wir automatisch in die Mails und die Anmeldeseite ein.</p>
      <p>Anmelden geht bis zum Ende des Festivals. Willst du früher dicht machen: „Anmeldung schließen".</p>
      <p>Gäste sehen erst was, wenn du das Festival auf „Offen" stellst und Links verschickst.</p>
    </FestivalHelp>

    <form class="compact-form" @submit.prevent="handleSubmit">
      <label for="festName">
        Name *
        <input id="festName" v-model="form.name" type="text" required placeholder="Betriebsfeier Julius Grube Schiffswerft" :disabled="submitting" />
      </label>

      <label for="festDescription">
        Beschreibung
        <textarea id="festDescription" v-model="form.description" rows="2" :disabled="submitting" />
      </label>

      <div class="form-row">
        <label for="festLocation">
          Ort
          <input id="festLocation" v-model="form.location" type="text" :disabled="submitting" />
        </label>
        <label for="festCapacity">
          Gesamt-Kapazität
          <input id="festCapacity" v-model.number="form.capacity" type="number" min="1" max="2000" :disabled="submitting" />
          <small>Richtwert für euch — blockiert nie eine Anmeldung</small>
        </label>
      </div>

      <div class="form-row">
        <label for="festStartAt">
          Beginn *
          <input id="festStartAt" v-model="form.startAt" type="datetime-local" required :disabled="submitting" />
        </label>
        <label for="festEndAt">
          Ende *
          <input id="festEndAt" v-model="form.endAt" type="datetime-local" required :disabled="submitting" />
        </label>
      </div>

      <label for="festContactHint">
        Kontakt-Adresse
        <input id="festContactHint" v-model="form.contactHint" type="text" placeholder="z.B. werft@funke.example" :disabled="submitting" />
        <small>Für Rückfragen der Gäste — landet in den Mails und auf der Anmeldeseite</small>
      </label>

      <label for="festParticipationHint">
        Mitmach-Hinweis
        <textarea id="festParticipationHint" v-model="form.participationHint" rows="3" :disabled="submitting" />
        <small>Steht auf der Anmeldeseite und in der Bestätigungs-Mail — am besten mit Schichtplan-Link</small>
      </label>

      <fieldset class="slot-editor">
        <legend>Zeitfenster</legend>

        <div v-for="(slot, i) in form.slots" :key="i" class="slot-row">
          <input
            v-model="slot.label"
            type="text"
            placeholder="Label, z.B. Freitag"
            required
            :disabled="submitting"
            class="slot-label"
          />
          <input v-model="slot.date" type="date" required :disabled="submitting" class="slot-date" />
          <label class="slot-night">
            <input type="checkbox" v-model="slot.is_night" :disabled="submitting" />
            Nacht
          </label>
          <input
            v-model.number="slot.capacity"
            type="number"
            min="1"
            placeholder="Kapazität (optional)"
            :disabled="submitting"
            class="slot-capacity"
          />
          <div class="slot-row-actions">
            <button type="button" class="outline slot-btn" title="Nach oben" :disabled="submitting || i === 0" @click="moveSlot(i, -1)">↑</button>
            <button type="button" class="outline slot-btn" title="Nach unten" :disabled="submitting || i === form.slots.length - 1" @click="moveSlot(i, 1)">↓</button>
            <button type="button" class="outline slot-btn remove-btn" title="Zeitfenster entfernen" :disabled="submitting" @click="removeSlot(i)">✕</button>
          </div>
        </div>

        <button type="button" class="outline" :disabled="submitting" @click="addSlot">
          + Zeitfenster hinzufügen
        </button>

        <p v-if="slotsUnsorted" class="hint-warning">
          Zeitfenster sind nicht chronologisch nach Datum sortiert — das Anlegen wird abgelehnt.
        </p>
      </fieldset>

      <footer>
        <button type="submit" :disabled="submitting" :aria-busy="submitting">
          {{ submitting ? 'Wird angelegt ...' : 'Festival anlegen' }}
        </button>
      </footer>
    </form>
  </article>
</template>

<script setup>
import { reactive, computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi } from '../../../services/api'
import PageHeader from '../../../components/PageHeader.vue'
import FestivalHelp from '../../../components/help/FestivalHelp.vue'
import { showToast } from '../../../composables/useToast.js'
import { berlinToUTCISO } from '../../../utils/formatters.js'

const router = useRouter()

const submitting = ref(false)

const DEFAULT_SLOT_LABELS = ['Freitag', 'Samstag', 'Sonntag']

function emptySlot() {
  return { label: '', date: '', is_night: false, capacity: null, _key: null, _persisted: false }
}

function defaultSlots() {
  return DEFAULT_SLOT_LABELS.map((label) => ({ ...emptySlot(), label }))
}

const form = reactive({
  name: '',
  description: '',
  location: '',
  capacity: 500,
  startAt: '',
  endAt: '',
  contactHint: '',
  participationHint: '',
  slots: defaultSlots(),
})

const slotsUnsorted = computed(() => {
  const dates = form.slots.map((s) => s.date).filter(Boolean)
  const sorted = [...dates].sort()
  return dates.length > 1 && JSON.stringify(dates) !== JSON.stringify(sorted)
})

function slugifyBase(label) {
  return (
    (label || '')
      .trim()
      .toLowerCase()
      .replace(/ä/g, 'ae')
      .replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue')
      .replace(/ß/g, 'ss')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'zeitfenster'
  )
}

function buildSlotsPayload() {
  const usedKeys = new Set()
  return form.slots.map((slot) => {
    const base = slugifyBase(slot.label)
    let candidate = base
    let i = 2
    while (usedKeys.has(candidate)) {
      candidate = `${base}-${i}`
      i += 1
    }
    usedKeys.add(candidate)
    return {
      key: candidate,
      label: slot.label.trim(),
      date: slot.date,
      is_night: slot.is_night,
      capacity: slot.capacity || null,
    }
  })
}

function buildPayload() {
  return {
    name: form.name.trim(),
    description: form.description?.trim() || null,
    location: form.location?.trim() || null,
    capacity: form.capacity,
    event_type: 'FESTIVAL',
    start_at: berlinToUTCISO(form.startAt),
    end_at: berlinToUTCISO(form.endAt),
    // Anmeldeschluss knob removed (Ä14/Ä20) — registration simply runs
    // until the festival ends, so the deadline always equals end_at.
    registration_deadline: berlinToUTCISO(form.endAt),
    contact_hint: form.contactHint?.trim() || null,
    participation_hint: form.participationHint?.trim() || null,
    festival_slots: buildSlotsPayload(),
  }
}

function addSlot() {
  form.slots.push(emptySlot())
}

function removeSlot(index) {
  form.slots.splice(index, 1)
}

function moveSlot(index, delta) {
  const target = index + delta
  if (target < 0 || target >= form.slots.length) return
  const slots = form.slots
  const [moved] = slots.splice(index, 1)
  slots.splice(target, 0, moved)
}

async function handleSubmit() {
  submitting.value = true
  try {
    const payload = buildPayload()
    const created = await adminApi.festival.createEvent(payload)
    showToast('Festival angelegt', 'success')
    router.push(`/admin/festival/${created.id}`)
  } catch (err) {
    showToast(err.message || 'Anlegen fehlgeschlagen', 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.compact-form label {
  margin-bottom: 0.75rem;
}

.compact-form textarea {
  margin-bottom: 0;
}

.compact-form small {
  color: var(--color-text-muted);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.form-row label {
  margin-bottom: 0.75rem;
}

.slot-editor {
  border: none;
  padding: 0;
  margin: 0 0 var(--pico-spacing);
}

.slot-editor legend {
  padding: 0;
  font-weight: bold;
  margin-bottom: 0.5rem;
}

.slot-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--pico-border-radius);
}

.slot-row input {
  margin-bottom: 0;
}

.slot-label {
  flex: 2;
  min-width: 8rem;
}

.slot-date {
  flex: 1;
  min-width: 9rem;
}

.slot-night {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  white-space: nowrap;
  margin-bottom: 0;
}

.slot-capacity {
  flex: 1;
  min-width: 8rem;
}

.slot-row-actions {
  display: flex;
  gap: 0.25rem;
  margin-left: auto;
}

.slot-btn {
  width: auto;
  min-width: 2.25rem;
  padding: 0.4rem 0.6rem;
  margin: 0;
}

.remove-btn {
  color: var(--color-danger-text);
  border-color: var(--color-danger-text);
}

.hint-warning {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  padding: 0.5rem 0.75rem;
  border-radius: var(--pico-border-radius);
  font-size: var(--text-sm);
}

footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
}

@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }

  /* Slot rows stack into a card on phones — full-width inputs, 44px targets. */
  .slot-label,
  .slot-date,
  .slot-capacity {
    flex: 1 1 100%;
    min-width: 0;
  }

  .slot-night {
    width: 100%;
    min-height: 44px;
  }

  .slot-row-actions {
    margin-left: 0;
    width: 100%;
    justify-content: flex-end;
  }

  .slot-btn {
    min-height: 44px;
    min-width: 44px;
  }
}
</style>

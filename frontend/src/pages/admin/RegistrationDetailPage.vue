<template>
  <article class="registration-detail-page">
    <header class="page-header">
      <div class="header-top">
        <a href="#" class="back-link" @click.prevent="goBack" aria-label="Zurück zur Anmeldeliste">
          <ChevronLeft :size="20" aria-hidden="true" />
          <span>Zurück zur Anmeldeliste</span>
        </a>
      </div>
      <p v-if="event" class="event-line">
        {{ event.name }} {{ formatDate(event.start_at) }}
      </p>
      <div class="header-title">
        <h2>
          <span v-if="registration">{{ formA.name || registration.name }}</span>
          <span v-else-if="loading" class="skeleton skeleton-title" />
        </h2>
        <span
          v-if="registration"
          :class="['status-badge', `status-${registration.status.toLowerCase()}`]"
        >
          {{ formatRegistrationStatus(registration.status) }}
        </span>
      </div>
    </header>

    <div v-if="loading" aria-busy="true">Anmeldung wird geladen…</div>

    <div v-else-if="loadError === 'not_found'" class="not-found">
      <p>Diese Anmeldung existiert nicht mehr.</p>
      <p><router-link :to="`/admin/events/${eventId}`">Zurück zur Veranstaltung</router-link></p>
    </div>

    <div v-else-if="loadError" role="alert" class="error-message">
      {{ loadError }}
    </div>

    <template v-else-if="registration">
      <div v-if="frozenReason" class="frozen-banner" role="status">
        {{ frozenReason }}
      </div>

      <div v-if="conflictBanner" class="conflict-banner" role="alert">
        <span>Die Anmeldung wurde zwischenzeitlich aktualisiert. Aktuelle Daten geladen — bitte erneut prüfen.</span>
        <button type="button" class="banner-close" aria-label="Schließen" @click="conflictBanner = false">×</button>
      </div>

      <!-- Section A: Anmeldedaten -->
      <section class="detail-section">
        <h3>Anmeldedaten</h3>
        <dl class="field-grid">
          <dt><label for="reg-name">Name</label></dt>
          <dd>
            <input
              v-if="!frozenReason"
              id="reg-name"
              v-model="formA.name"
              type="text"
              maxlength="200"
              :class="{ invalid: errorsA.name }"
            />
            <span v-else class="static">{{ registration.name }}</span>
            <p v-if="errorsA.name" class="field-error">{{ errorsA.name }}</p>
          </dd>

          <dt>E-Mail</dt>
          <dd><a :href="`mailto:${registration.email}`">{{ registration.email }}</a></dd>

          <dt><label for="reg-phone">Telefon</label></dt>
          <dd>
            <input
              v-if="!frozenReason"
              id="reg-phone"
              v-model="formA.phone"
              type="tel"
              maxlength="50"
            />
            <span v-else class="static">{{ registration.phone || '–' }}</span>
          </dd>

          <dt><label for="reg-notes">Notizen</label></dt>
          <dd>
            <textarea
              v-if="!frozenReason"
              id="reg-notes"
              v-model="formA.notes"
              maxlength="500"
              rows="3"
            />
            <span v-else class="static">{{ registration.notes || '–' }}</span>
          </dd>

          <dt>Angemeldet am</dt>
          <dd>{{ formatDate(registration.registered_at) }}</dd>

          <template v-if="registration.responded_at">
            <dt>Bestätigt am</dt>
            <dd>{{ formatDate(registration.responded_at) }}</dd>
          </template>

          <template v-if="showPromotedToggle">
            <dt>Bevorzugt</dt>
            <dd>
              <label class="promoted-toggle" :title="'Garantierte Teilnahme bei der Verlosung'">
                <input
                  type="checkbox"
                  role="switch"
                  :checked="registration.promoted"
                  :disabled="togglingPromoted"
                  @change="togglePromoted(!registration.promoted)"
                />
              </label>
            </dd>
          </template>
        </dl>

        <p v-if="errorA" class="error-message" role="alert">{{ errorA }}</p>

        <div v-if="!frozenReason" class="section-actions">
          <button
            type="button"
            class="secondary"
            :disabled="!isDirtyA || savingA"
            v-if="isDirtyA"
            @click="resetA"
          >
            Verwerfen
          </button>
          <button
            type="button"
            :disabled="!isDirtyA || savingA"
            :aria-busy="savingA"
            @click="saveA"
          >
            {{ savingA ? 'Wird gespeichert…' : 'Änderungen speichern' }}
          </button>
        </div>
      </section>

      <!-- Section B: Gäste auf der Bordliste -->
      <section class="detail-section">
        <h3>Gäste auf der Bordliste</h3>
        <p class="muted">{{ usedCount }} von {{ effectiveSize }} Plätzen genutzt</p>

        <ul class="slot-list">
          <li
            v-for="(slot, idx) in slots"
            :key="`${slot.kind}-${slot.localKey}`"
            :class="['slot', `slot-${slot.kind}`, { staged: slot.staged }]"
          >
            <template v-if="confirming && confirming.kind === slot.kind && confirming.index === slot.index">
              <span class="slot-confirm">Gast entfernen?</span>
              <div class="slot-confirm-actions">
                <button type="button" class="btn-danger" @click="commitDelete(slot)">Entfernen</button>
                <button type="button" class="secondary" @click="confirming = null">Abbrechen</button>
              </div>
            </template>
            <template v-else>
              <!-- Registrant slot: bound to formA.name -->
              <template v-if="slot.kind === 'registrant'">
                <span class="slot-num">1.</span>
                <input
                  v-if="!frozenReason"
                  v-model="formA.name"
                  type="text"
                  maxlength="200"
                  class="slot-input"
                  aria-label="Name (Anmeldende:r)"
                />
                <span v-else class="slot-name static">{{ formA.name || registration.name }}</span>
                <span class="slot-tag">Anmeldung</span>
              </template>

              <!-- Named guest slot: editable -->
              <template v-else-if="slot.kind === 'named'">
                <span class="slot-num">{{ idx + 1 }}.</span>
                <input
                  v-if="!frozenReason"
                  v-model="guestNames[slot.index]"
                  type="text"
                  maxlength="200"
                  class="slot-input"
                  :class="{ invalid: errorsB.guests[slot.index] }"
                  :disabled="slot.staged"
                  :aria-label="`Gast ${idx + 1}`"
                />
                <span v-else class="slot-name static">{{ guestNames[slot.index] }}</span>
                <button
                  v-if="!frozenReason && !slot.staged"
                  type="button"
                  class="slot-trash"
                  aria-label="Entfernen"
                  @click="confirming = { kind: 'named', index: slot.index }"
                >
                  <Trash2 :size="16" aria-hidden="true" />
                </button>
              </template>

              <!-- Placeholder slot: muted, non-editable -->
              <template v-else>
                <span class="slot-num">{{ idx + 1 }}.</span>
                <span class="slot-placeholder">Gast {{ idx + 1 }}</span>
                <button
                  v-if="!frozenReason"
                  type="button"
                  class="slot-trash"
                  aria-label="Entfernen"
                  @click="confirming = { kind: 'placeholder', index: slot.index }"
                >
                  <Trash2 :size="16" aria-hidden="true" />
                </button>
              </template>
            </template>
            <p v-if="slot.kind === 'named' && errorsB.guests[slot.index]" class="field-error">
              {{ errorsB.guests[slot.index] }}
            </p>
          </li>
        </ul>

        <p v-if="hasPlaceholders" class="muted helper-line">
          Gastnamen werden von der Person eingetragen, die sich angemeldet hat.
        </p>

        <p v-if="errorB" class="error-message" role="alert">{{ errorB }}</p>

        <div v-if="!frozenReason" class="section-actions">
          <button
            type="button"
            class="secondary"
            :disabled="!isDirtyB || savingB"
            v-if="isDirtyB"
            @click="resetB"
          >
            Verwerfen
          </button>
          <button
            type="button"
            :disabled="!isDirtyB || savingB"
            :aria-busy="savingB"
            @click="saveB"
          >
            {{ savingB ? 'Wird gespeichert…' : saveBLabel }}
          </button>
        </div>
      </section>

      <!-- Section C: Aktionen -->
      <section class="detail-section">
        <h3>Aktionen</h3>
        <div class="actions-stack">
          <template v-if="canPromoteFromWaitlist">
            <button
              type="button"
              :disabled="promotingFromWaitlist"
              @click="promoteFromWaitlist('CONFIRMED')"
            >
              Nachrücken
            </button>
            <button
              type="button"
              class="secondary"
              :disabled="promotingFromWaitlist"
              @click="promoteFromWaitlist('PARTICIPATING')"
            >
              Direkt bestätigen
            </button>
          </template>

          <button
            v-if="canDelete"
            type="button"
            class="btn-danger"
            @click="showDeleteModal = true"
          >
            Anmeldung löschen
          </button>
        </div>
      </section>
    </template>

    <!-- Delete registration confirmation -->
    <dialog :open="showDeleteModal">
      <article v-if="registration">
        <header>
          <a href="#" aria-label="Schließen" class="close" @click.prevent="showDeleteModal = false" />
          <h3>Anmeldung löschen</h3>
        </header>
        <p>Anmeldung von "{{ registration.name }}" unwiderruflich löschen?</p>
        <footer>
          <button type="button" class="secondary" :disabled="deleting" @click="showDeleteModal = false">Abbrechen</button>
          <button class="btn-danger" :disabled="deleting" :aria-busy="deleting" @click="confirmDelete">Löschen</button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ChevronLeft, Trash2 } from 'lucide-vue-next'
import { adminApi } from '../../services/api'
import { showToast } from '../../composables/useToast.js'
import { formatDate, formatRegistrationStatus } from '../../utils/formatters.js'

const props = defineProps({
  eventId: { type: String, required: true },
  registrationId: { type: String, required: true },
})

const router = useRouter()

// --- Server state ---
const event = ref(null)
const registration = ref(null)
const loading = ref(true)
const loadError = ref(null)

// --- Section A form ---
const formA = reactive({ name: '', phone: '', notes: '' })
const initialA = reactive({ name: '', phone: '', notes: '' })
const errorsA = reactive({ name: null })
const errorA = ref(null)
const savingA = ref(false)

// --- Section B form ---
const initialGuestNames = ref([])
const guestNames = ref([])
const stagedGuests = ref(new Set())
const placeholdersTotal = ref(0)
const placeholdersDelta = ref(0)
const errorsB = reactive({ guests: {} })
const errorB = ref(null)
const savingB = ref(false)
const confirming = ref(null)

// --- Section C ---
const togglingPromoted = ref(false)
const promotingFromWaitlist = ref(false)
const showDeleteModal = ref(false)
const deleting = ref(false)

// --- Banners ---
const conflictBanner = ref(false)

// --- Loading / hydration ---
async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [eventResp, regResp] = await Promise.all([
      adminApi.getEvent(props.eventId),
      adminApi.getAdminRegistration(props.eventId, props.registrationId),
    ])
    event.value = eventResp
    hydrate(regResp)
  } catch (err) {
    if (err?.status === 404) {
      loadError.value = 'not_found'
    } else {
      loadError.value = err?.message || 'Anmeldung konnte nicht geladen werden.'
    }
  } finally {
    loading.value = false
  }
}

function refreshA(reg) {
  formA.name = reg.name
  formA.phone = reg.phone || ''
  formA.notes = reg.notes || ''
  initialA.name = reg.name
  initialA.phone = reg.phone || ''
  initialA.notes = reg.notes || ''
  errorsA.name = null
  errorA.value = null
}

function refreshB(reg) {
  const namedRest = reg.group_members ? reg.group_members.slice(1) : []
  initialGuestNames.value = [...namedRest]
  guestNames.value = [...namedRest]
  stagedGuests.value = new Set()
  // group_size = 1 (registrant) + named guests + placeholders
  placeholdersTotal.value = Math.max(0, reg.group_size - 1 - namedRest.length)
  placeholdersDelta.value = 0
  errorsB.guests = {}
  errorB.value = null
  confirming.value = null
}

function hydrate(reg) {
  registration.value = reg
  refreshA(reg)
  refreshB(reg)
}

// --- Computed: dirty flags ---
const isDirtyA = computed(() =>
  formA.name !== initialA.name
  || formA.phone !== initialA.phone
  || formA.notes !== initialA.notes,
)

const isDirtyB = computed(() => {
  if (stagedGuests.value.size > 0) return true
  if (placeholdersDelta.value !== 0) return true
  for (let i = 0; i < guestNames.value.length; i++) {
    if (guestNames.value[i] !== initialGuestNames.value[i]) return true
  }
  return false
})

// --- Computed: slots, sizes, frozen state ---
const remainingPlaceholders = computed(() =>
  Math.max(0, placeholdersTotal.value + placeholdersDelta.value),
)

const effectiveSize = computed(() => {
  if (!registration.value) return 0
  const namedRetained = guestNames.value.length - stagedGuests.value.size
  return 1 + namedRetained + remainingPlaceholders.value
})

const usedCount = computed(() => {
  if (!registration.value) return 0
  const namedRetained = guestNames.value.length - stagedGuests.value.size
  return 1 + namedRetained
})

const slots = computed(() => {
  if (!registration.value) return []
  const result = [{ kind: 'registrant', index: 0, localKey: 'reg', staged: false }]
  guestNames.value.forEach((_, i) => {
    result.push({ kind: 'named', index: i, localKey: `g${i}`, staged: stagedGuests.value.has(i) })
  })
  for (let p = 0; p < remainingPlaceholders.value; p++) {
    result.push({ kind: 'placeholder', index: p, localKey: `p${p}`, staged: false })
  }
  return result
})

const hasPlaceholders = computed(() => remainingPlaceholders.value > 0)

const totalStagedDeletes = computed(() => stagedGuests.value.size + Math.max(0, -placeholdersDelta.value))

const saveBLabel = computed(() => {
  const n = totalStagedDeletes.value
  if (n === 1) return '1 Gast entfernen und speichern'
  if (n > 1) return `${n} Gäste entfernen und speichern`
  return 'Änderungen speichern'
})

const frozenReason = computed(() => {
  if (!registration.value || !event.value) return null
  if (registration.value.status === 'CANCELLED') {
    return 'Diese Anmeldung wurde storniert. Änderungen sind nicht möglich.'
  }
  if (registration.value.status === 'CHECKED_IN') {
    return 'Diese Person ist bereits eingecheckt. Änderungen sind nicht mehr möglich.'
  }
  if (event.value.status === 'COMPLETED') {
    return 'Die Veranstaltung ist abgeschlossen. Änderungen sind nicht mehr möglich.'
  }
  return null
})

// --- Promoted toggle visibility (mirrors RegistrationTable) ---
const showPromotedToggle = computed(() => {
  if (!event.value || frozenReason.value) return false
  return ['OPEN', 'REGISTRATION_CLOSED'].includes(event.value.status)
})

// --- Actions: waitlist / delete visibility ---
const canPromoteFromWaitlist = computed(() =>
  registration.value?.status === 'WAITLISTED' && event.value?.status === 'CONFIRMED',
)

const canDelete = computed(() => {
  if (!registration.value || !event.value) return false
  if (event.value.status === 'COMPLETED') return false
  if (registration.value.status === 'CHECKED_IN') return false
  return true
})

// --- Slot delete handlers ---
function commitDelete(slot) {
  if (slot.kind === 'named') {
    stagedGuests.value = new Set(stagedGuests.value).add(slot.index)
  } else if (slot.kind === 'placeholder') {
    placeholdersDelta.value -= 1
  }
  confirming.value = null
}

// --- Section A actions ---
function resetA() {
  formA.name = initialA.name
  formA.phone = initialA.phone
  formA.notes = initialA.notes
  errorsA.name = null
  errorA.value = null
}

function validateA() {
  errorsA.name = null
  if (!formA.name.trim()) {
    errorsA.name = 'Name darf nicht leer sein.'
    return false
  }
  return true
}

async function saveA() {
  if (!validateA()) return
  errorA.value = null
  savingA.value = true
  const patch = {}
  if (formA.name !== initialA.name) patch.name = formA.name.trim()
  if (formA.phone !== initialA.phone) patch.phone = formA.phone
  if (formA.notes !== initialA.notes) patch.notes = formA.notes
  try {
    const updated = await adminApi.updateAdminRegistration(props.eventId, props.registrationId, patch)
    registration.value = updated
    refreshA(updated)
    showToast('Änderungen gespeichert.', 'success')
  } catch (err) {
    handleSaveError(err, 'A')
  } finally {
    savingA.value = false
  }
}

// --- Section B actions ---
function resetB() {
  guestNames.value = [...initialGuestNames.value]
  stagedGuests.value = new Set()
  placeholdersDelta.value = 0
  errorsB.guests = {}
  errorB.value = null
  confirming.value = null
}

function validateB() {
  errorsB.guests = {}
  let ok = true
  for (let i = 0; i < guestNames.value.length; i++) {
    if (stagedGuests.value.has(i)) continue
    if (!guestNames.value[i].trim()) {
      errorsB.guests[i] = 'Name darf nicht leer sein.'
      ok = false
    }
  }
  return ok
}

async function saveB() {
  if (!validateB()) return
  errorB.value = null
  savingB.value = true
  const remainingGuests = guestNames.value
    .map((name, i) => ({ name: name.trim(), staged: stagedGuests.value.has(i) }))
    .filter(g => !g.staged)
    .map(g => g.name)

  const targetSize = 1 + remainingGuests.length + remainingPlaceholders.value
  const patch = { group_size: targetSize }
  if (registration.value.group_members) {
    patch.group_members = [formA.name.trim() || initialA.name, ...remainingGuests]
  }
  // Section A and B share formA.name (registrant slot is bound to it). If Section A
  // is dirty when saving B, persist the name change atomically — otherwise the
  // post-save hydrate from the server would clobber the unsaved edit.
  if (formA.name.trim() && formA.name !== initialA.name) {
    patch.name = formA.name.trim()
  }

  const patchedName = 'name' in patch
  try {
    const updated = await adminApi.updateAdminRegistration(props.eventId, props.registrationId, patch)
    registration.value = updated
    refreshB(updated)
    if (patchedName) refreshA(updated)
    showToast('Änderungen gespeichert.', 'success')
  } catch (err) {
    handleSaveError(err, 'B')
  } finally {
    savingB.value = false
  }
}

// --- Save error handling ---
function handleSaveError(err, section) {
  if (err?.status === 409 && err?.data?.registration) {
    hydrate(err.data.registration)
    conflictBanner.value = true
    return
  }
  const msg = err?.message || 'Speichern fehlgeschlagen.'
  if (section === 'A') errorA.value = msg
  else errorB.value = msg
}

// --- Section C actions ---
async function togglePromoted(value) {
  if (!registration.value) return
  togglingPromoted.value = true
  try {
    const updated = await adminApi.togglePromoted(props.eventId, props.registrationId, value)
    // Only update the server-snapshot ref — leave any dirty form state in A/B alone.
    registration.value = updated
    showToast('Bevorzugung aktualisiert.', 'success')
  } catch (err) {
    showToast(err?.message || 'Bevorzugung konnte nicht geändert werden.', 'error')
  } finally {
    togglingPromoted.value = false
  }
}

async function promoteFromWaitlist(targetStatus) {
  promotingFromWaitlist.value = true
  try {
    const updated = await adminApi.promoteFromWaitlist(props.eventId, props.registrationId, targetStatus)
    registration.value = updated
    showToast('Anmeldung nachgerückt.', 'success')
  } catch (err) {
    showToast(err?.message || 'Nachrücken fehlgeschlagen.', 'error')
  } finally {
    promotingFromWaitlist.value = false
  }
}

async function confirmDelete() {
  deleting.value = true
  try {
    await adminApi.deleteRegistration(props.eventId, props.registrationId)
    showDeleteModal.value = false
    router.push(`/admin/events/${props.eventId}`)
  } catch (err) {
    showToast(err?.message || 'Löschen fehlgeschlagen.', 'error')
    deleting.value = false
  }
}

// --- Back navigation ---
function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push(`/admin/events/${props.eventId}`)
  }
}

onMounted(load)
</script>

<style scoped>
.registration-detail-page {
  max-width: 720px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-4);
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 2.25rem;
  margin-bottom: var(--space-2);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-height: 44px;
  padding: var(--space-1) var(--space-2);
  margin-left: calc(var(--space-2) * -1);
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: var(--text-base);
  font-weight: 500;
  border-radius: var(--radius-md);
}

.back-link:hover,
.back-link:focus-visible {
  color: var(--color-brand);
  background: var(--color-bg-muted);
  outline: none;
}

.event-line {
  margin: 0 0 var(--space-1);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.header-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.header-title h2 {
  margin: 0;
  font-size: var(--text-xl);
  line-height: 1.2;
  font-weight: 600;
}

.frozen-banner,
.conflict-banner {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--pico-border-radius);
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
}

.frozen-banner {
  background: var(--color-neutral-bg);
  color: var(--color-neutral-text);
  border: 1px solid var(--color-border);
}

.conflict-banner {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border: 1px solid var(--color-warning-text);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.banner-close {
  all: unset;
  cursor: pointer;
  font-size: 1.25rem;
  line-height: 1;
  padding: 0 var(--space-1);
  color: inherit;
}

.detail-section {
  margin-bottom: var(--space-6);
}

.detail-section h3 {
  font-size: var(--text-lg);
  margin: 0 0 var(--space-3);
}

.field-grid {
  display: grid;
  grid-template-columns: max-content 1fr;
  column-gap: var(--space-4);
  row-gap: var(--space-3);
  margin: 0 0 var(--space-3);
}

.field-grid dt {
  font-weight: 500;
  color: var(--color-text-muted);
  align-self: center;
}

.field-grid dd {
  margin: 0;
}

.field-grid input[type="text"],
.field-grid input[type="tel"],
.field-grid textarea {
  width: 100%;
  margin: 0;
}

.field-grid input.invalid {
  border-color: var(--color-danger-text);
}

.static {
  color: var(--color-text);
}

.field-error {
  margin: var(--space-1) 0 0;
  color: var(--color-danger-text);
  font-size: var(--text-sm);
}

.error-message {
  color: var(--color-danger-text);
  background: var(--color-danger-bg);
  padding: var(--space-2);
  border-radius: var(--pico-border-radius);
  margin: var(--space-3) 0 0;
}

.section-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
  justify-content: flex-end;
}

.muted {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  margin: 0 0 var(--space-3);
}

.helper-line {
  margin-top: var(--space-2);
}

.slot-list {
  list-style: none;
  margin: 0 0 var(--space-3);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.slot {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--pico-border-radius);
  background: var(--color-surface);
}

.slot.staged .slot-input,
.slot.staged .slot-name,
.slot.staged .slot-placeholder {
  text-decoration: line-through;
  color: var(--color-text-muted);
}

.slot-num {
  font-variant-numeric: tabular-nums;
  color: var(--color-text-muted);
  min-width: 1.5rem;
}

.slot-input {
  flex: 1;
  margin: 0;
}

.slot-input.invalid {
  border-color: var(--color-danger-text);
}

.slot-name {
  flex: 1;
}

.slot-placeholder {
  flex: 1;
  color: var(--color-text-muted);
  font-style: italic;
}

.slot-tag {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.slot-trash {
  all: unset;
  cursor: pointer;
  padding: var(--space-1);
  color: var(--color-text-muted);
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
}

.slot-trash:hover,
.slot-trash:focus-visible {
  color: var(--color-danger-text);
  background: var(--color-danger-bg);
  outline: none;
}

.slot-confirm {
  flex: 1;
  color: var(--color-danger-text);
  font-weight: 500;
}

.slot-confirm-actions {
  display: flex;
  gap: var(--space-2);
}

.slot-confirm-actions button {
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  margin: 0;
}

.actions-stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: flex-start;
}

.actions-stack button {
  margin: 0;
}

.btn-danger {
  background: var(--color-danger-text);
  border-color: var(--color-danger-text);
  color: white;
}

.btn-danger:hover {
  filter: brightness(1.05);
}

.not-found {
  text-align: center;
  margin-top: var(--space-6);
  color: var(--color-text-muted);
}

.promoted-toggle input[type="checkbox"] {
  margin: 0;
}
</style>

<template>
  <article style="position: relative;">
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true" class="loading-state">
      Einen Moment — deine Einladung wird geladen ...
    </div>

    <!-- Error state -->
    <div v-else-if="error" role="alert" class="invite-error">
      <h2>Diese Einladung lässt sich nicht öffnen</h2>
      <p>{{ error }}</p>
    </div>

    <!-- Event info and registration form -->
    <template v-else-if="invite">
      <header class="festival-header">
        <p class="eyebrow">Du bist eingeladen</p>
        <h2>{{ invite.event_name }}</h2>
        <dl class="event-facts">
          <dt>Wann</dt>
          <dd>
            {{ formatDateLong(invite.start_at) }}
            <template v-if="invite.end_at"> – {{ formatDateLong(invite.end_at) }}</template>
          </dd>
          <dt>Anmelden bis</dt>
          <dd>{{ formatDateLong(invite.registration_deadline) }}</dd>
        </dl>
      </header>

      <!-- Mitmach-Hinweis box (Ä16) -->
      <section v-if="invite.participation_hint && !submitted" class="callout callout-warm">
        <p class="callout-title">Pack mit an!</p>
        <p class="participation-hint-text">{{ invite.participation_hint }}</p>
      </section>

      <!-- Registration form -->
      <section v-if="!submitted" class="registration-section">
        <h3>Sag uns, dass du kommst</h3>

        <FestivalHelp title="Wie läuft das?">
          <p>Du meldest dich an und bekommst eine Mail mit deinem persönlichen Link.</p>
          <p>Über den Link kannst du alles jederzeit ändern — Tage, Begleitungen, absagen. Bis zum Ende des Festivals.</p>
          <p>Da findest du später auch die Eintritts-Codes für dich und deine Leute.</p>
        </FestivalHelp>

        <form @submit.prevent="handleSubmit">
          <label for="name">
            Dein Name *
            <input
              id="name"
              v-model="form.name"
              type="text"
              required
              placeholder="Vor- und Nachname"
              :disabled="submitting"
            />
          </label>
          <small v-if="form.name && !hasTwoWords(form.name)" class="field-hint">
            Bitte Vor- und Nachnamen angeben
          </small>

          <label for="email">
            Deine E-Mail *
            <input
              id="email"
              v-model="form.email"
              type="email"
              required
              placeholder="deine@email.de"
              :disabled="submitting"
            />
          </label>

          <label for="phone">
            Deine Telefonnummer *
            <input
              id="phone"
              v-model="form.phone"
              type="tel"
              required
              placeholder="+49 123 456789"
              :disabled="submitting"
            />
          </label>

          <fieldset v-if="maxExtraMembers > 0" class="extra-members">
            <legend>Wen bringst du mit? <span class="legend-optional">(optional)</span></legend>
            <div v-for="(_, i) in form.extraMembers" :key="i" class="extra-member-row">
              <input
                v-model="form.extraMembers[i]"
                type="text"
                maxlength="200"
                placeholder="Vor- und Nachname"
                :disabled="submitting"
              />
              <small v-if="form.extraMembers[i] && !hasTwoWords(form.extraMembers[i])" class="field-hint">
                Bitte Vor- und Nachnamen angeben
              </small>
            </div>
            <small class="field-note">
              Du kannst {{ maxExtraMembers === 1 ? 'eine Person' : `bis zu ${maxExtraMembers} Personen` }} mitbringen — einfach Namen eintragen.
            </small>
          </fieldset>

          <fieldset class="slot-grid">
            <legend>Wann bist du dabei? *</legend>
            <div v-for="group in slotsByDate" :key="group.date" class="slot-day-group">
              <p class="slot-day-heading">{{ formatWeekdayHeading(group.date) }}</p>
              <label
                v-for="slot in group.slots"
                :key="slot.key"
                class="slot-checkbox"
                @mouseenter="hoveredSlotKey = slot.key"
                @mouseleave="hoveredSlotKey = null"
              >
                <input
                  type="checkbox"
                  v-model="form.slots[slot.key]"
                  :disabled="submitting"
                />
                <span class="slot-checkbox-label">
                  {{ slot.label }}
                  <small
                    v-if="slot.very_full && (form.slots[slot.key] || hoveredSlotKey === slot.key)"
                    class="very-full-hint"
                  >
                    Dieses Zeitfenster ist schon ziemlich voll — du kannst dich trotzdem anmelden.
                  </small>
                </span>
              </label>
            </div>
          </fieldset>

          <fieldset v-if="OVERNIGHT_ENABLED" class="overnight-fieldset">
            <legend>Übernachtest du auf dem Gelände?</legend>
            <label class="slot-checkbox">
              <input
                type="radio"
                name="accommodation"
                value="NONE"
                v-model="form.accommodation"
                :disabled="submitting"
              />
              <span class="slot-checkbox-label">Nein</span>
            </label>
            <label class="slot-checkbox">
              <input
                type="radio"
                name="accommodation"
                value="TENT"
                v-model="form.accommodation"
                :disabled="submitting"
              />
              <span class="slot-checkbox-label">Zelt — wir bringen unser eigenes Zelt mit</span>
            </label>
            <label class="slot-checkbox">
              <input
                type="radio"
                name="accommodation"
                value="CAMPER"
                v-model="form.accommodation"
                :disabled="submitting"
              />
              <span class="slot-checkbox-label">Camper/Bus — wir schlafen im eigenen Fahrzeug</span>
            </label>

            <p v-if="form.accommodation !== 'NONE'" class="callout callout-warning request-copy">
              Schlafplätze sind begrenzt — deine Angabe ist eine Anfrage, keine Zusage. Wir melden uns bei dir.
            </p>
          </fieldset>

          <div v-if="submitError" role="alert" class="error">
            {{ submitError }}
          </div>

          <div class="submit-bar">
            <button type="submit" :disabled="submitting" :aria-busy="submitting">
              {{ submitting ? 'Wird gesendet ...' : 'Jetzt anmelden' }}
            </button>
          </div>
        </form>
      </section>

      <!-- Success state -->
      <section v-if="submitted" class="success">
        <p class="success-emoji" aria-hidden="true">🎉</p>
        <h3>Du bist dabei!</h3>

        <p class="success-lead">
          Schön, dass du kommst — deine Anmeldung für <strong>{{ invite?.event_name }}</strong> steht.
        </p>

        <div v-if="registration" class="registration-details">
          <dl>
            <dt>Name</dt><dd>{{ registration.name }}</dd>
            <dt>E-Mail</dt><dd><a :href="`mailto:${registration.email}`">{{ registration.email }}</a></dd>
            <dt>Personen</dt><dd>{{ registration.group_size }}</dd>
          </dl>
        </div>

        <div class="callout callout-info mail-note">
          <p>
            Wir haben dir eine Bestätigung an <strong>{{ registration?.email }}</strong> geschickt —
            da steht alles nochmal drin.
          </p>
        </div>

        <div v-if="manageUrl" class="callout callout-warm manage-link-box">
          <p class="callout-title">Speicher dir diesen Link!</p>
          <p class="manage-link-text">
            <template v-if="OVERNIGHT_ENABLED">
              Damit kannst du deine Anmeldung später ändern — Zeiten, Übernachtung, Begleitungen:
            </template>
            <template v-else>
              Damit kannst du deine Anmeldung später ändern — Zeiten und Begleitungen:
            </template>
          </p>
          <div class="manage-link-row">
            <code class="manage-link-url">{{ manageUrl }}</code>
            <button type="button" @click="copyManageUrl">
              {{ manageUrlCopied ? 'Kopiert ✓' : 'Link kopieren' }}
            </button>
          </div>
        </div>
      </section>
    </template>
  </article>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { publicApi } from '../../services/api'
import { formatDateLong } from '../../utils/formatters.js'
import { OVERNIGHT_ENABLED } from '../../config/festival.js'
import FestivalHelp from '../../components/help/FestivalHelp.vue'

const props = defineProps({
  inviteToken: { type: String, required: true },
})

const loading = ref(true)
const error = ref(null)
const invite = ref(null)
const submitted = ref(false)
const submitting = ref(false)
const submitError = ref(null)
const registration = ref(null)
const manageUrl = ref('')
const manageUrlCopied = ref(false)
// Ä4 (if-time): tracks which slot label is currently hovered, so the
// reassuring "very_full" note can show on hover as well as when checked —
// soft, informational, never blocking (see `.very-full-hint` styling).
const hoveredSlotKey = ref(null)

const form = ref({
  name: '',
  email: '',
  extraMembers: [],
  slots: {},
  accommodation: 'NONE',
  phone: '',
})

const maxExtraMembers = computed(() => Math.max(0, (invite.value?.max_group_size || 1) - 1))

// Group slots by day, weekday heading via Intl (formatters.js has no per-day-only helper).
const slotsByDate = computed(() => {
  if (!invite.value) return []
  const groups = new Map()
  for (const slot of invite.value.slots) {
    if (!groups.has(slot.date)) groups.set(slot.date, [])
    groups.get(slot.date).push(slot)
  }
  return Array.from(groups.entries()).map(([date, slots]) => ({ date, slots }))
})

function formatWeekdayHeading(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('de-DE', {
    timeZone: 'Europe/Berlin',
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

function hasTwoWords(value) {
  return (value || '').trim().split(/\s+/).filter(Boolean).length >= 2
}

async function loadInvite() {
  const inviteToken = props.inviteToken
  if (!inviteToken) {
    error.value = 'Ungültiger Einladungslink.'
    loading.value = false
    return
  }

  try {
    invite.value = await publicApi.getInviteInfo(inviteToken)
    const slotMap = {}
    for (const slot of invite.value.slots) {
      slotMap[slot.key] = false
    }
    form.value.slots = slotMap
    form.value.extraMembers = Array(maxExtraMembers.value).fill('')
  } catch (err) {
    // Backend already returns a distinct, contact-hint-aware German message
    // for every 404/410 state (unknown/revoked, exhausted, expired, deadline).
    error.value = err.message || 'Einladung konnte nicht geladen werden.'
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  submitError.value = null

  const trimmedName = form.value.name.trim()
  if (!hasTwoWords(trimmedName)) {
    submitError.value = 'Bitte Vor- und Nachnamen angeben'
    return
  }

  const filledExtras = form.value.extraMembers.map((n) => n.trim()).filter(Boolean)
  if (filledExtras.some((n) => !hasTwoWords(n))) {
    submitError.value = 'Bitte Vor- und Nachnamen angeben'
    return
  }

  const selectedSlotKeys = Object.keys(form.value.slots).filter((key) => form.value.slots[key])
  if (selectedSlotKeys.length === 0) {
    submitError.value = 'Bitte wähle mindestens einen Zeitraum aus.'
    return
  }

  // OVERNIGHT_ENABLED gate (Stellplatz ungeklärt, 19.7.): while disabled,
  // accommodation never leaves this form, regardless of form state. Phone
  // is required independently of accommodation/OVERNIGHT_ENABLED.
  const accommodation = OVERNIGHT_ENABLED && form.value.accommodation !== 'NONE' ? form.value.accommodation : null
  const trimmedPhone = form.value.phone.trim()
  if (!trimmedPhone) {
    submitError.value = 'Bitte gib deine Telefonnummer an.'
    return
  }

  submitting.value = true

  const payload = {
    name: trimmedName,
    email: form.value.email.trim().toLowerCase(),
    group_size: 1 + filledExtras.length,
    attendance_slots: selectedSlotKeys,
    accommodation,
    phone: trimmedPhone,
  }
  if (filledExtras.length > 0) {
    // EXCLUSIVE convention (spec §QR payload): group_members are the
    // companions only — person_index 0 (the contact) is `name` itself.
    payload.group_members = filledExtras
  }

  try {
    const result = await publicApi.createFestivalRegistration(props.inviteToken, payload)
    registration.value = result
    manageUrl.value = result.manage_url
    submitted.value = true
  } catch (err) {
    if (err.status === 409) {
      submitError.value = 'Mit dieser E-Mail-Adresse bist du schon angemeldet — schau mal in dein Postfach, da liegt dein Verwaltungslink.'
    } else if (err.status === 410) {
      submitError.value = err.message
    } else {
      submitError.value = err.message || 'Das hat leider nicht geklappt — probier es gleich nochmal.'
    }
  } finally {
    submitting.value = false
  }
}

function copyManageUrl() {
  navigator.clipboard.writeText(manageUrl.value).then(
    () => {
      manageUrlCopied.value = true
      setTimeout(() => { manageUrlCopied.value = false }, 2500)
    },
    () => {},
  )
}

onMounted(loadInvite)
</script>

<style scoped>
.loading-state {
  padding: var(--space-6) var(--space-3);
  text-align: center;
  color: var(--color-text-muted);
}

.invite-error {
  padding: var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-lg);
}

.invite-error h2 {
  color: var(--color-danger-text);
  font-size: var(--text-xl);
  margin-bottom: var(--space-2);
}

.invite-error p {
  color: var(--color-danger-text);
  margin: 0;
}

/* === Header: the invitation moment === */
.festival-header {
  margin-bottom: var(--space-5);
}

.eyebrow {
  color: var(--color-accent);
  font-size: var(--text-sm);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 0 0 var(--space-1);
}

.festival-header h2 {
  margin-bottom: var(--space-3);
}

.event-facts {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-4);
  margin: 0;
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.event-facts dt {
  font-weight: 600;
  color: var(--color-text-muted);
}

.event-facts dd {
  margin: 0;
}

/* === Callouts: one recipe, three tones === */
.callout {
  border-radius: var(--radius-md);
  border-left: 4px solid;
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-5);
}

.callout p {
  margin: 0;
}

.callout-title {
  font-weight: 700;
  margin: 0 0 var(--space-1);
}

.callout-warm {
  background: var(--color-accent-subtle);
  border-left-color: var(--color-accent);
}

.callout-warm .callout-title {
  color: var(--color-accent-hover);
}

.callout-info {
  background: var(--color-info-bg);
  border-left-color: var(--color-info-text);
  color: var(--color-info-text);
}

.callout-warning {
  background: var(--color-warning-bg);
  border-left-color: var(--color-warning-text);
  color: var(--color-warning-text);
}

.participation-hint-text {
  white-space: pre-wrap;
}

/* === Form === */
.registration-section h3 {
  margin-bottom: var(--space-4);
}

.field-hint {
  display: block;
  color: var(--color-warning-text);
  margin: -0.5rem 0 var(--space-4);
}

.field-note {
  display: block;
  color: var(--color-text-muted);
  margin-top: var(--space-1);
}

.legend-optional {
  font-weight: 400;
  color: var(--color-text-muted);
}

.extra-members {
  border: none;
  padding: 0;
  margin: 0 0 var(--space-5);
}

.extra-members legend {
  padding: 0;
  font-weight: 700;
  margin-bottom: var(--space-2);
}

.extra-member-row input {
  margin-bottom: var(--space-2);
}

.slot-grid,
.overnight-fieldset {
  border: none;
  padding: 0;
  margin: 0 0 var(--space-5);
}

.slot-grid legend,
.overnight-fieldset legend {
  padding: 0;
  font-weight: 700;
  margin-bottom: var(--space-2);
}

.slot-day-group {
  margin-bottom: var(--space-4);
}

.slot-day-heading {
  font-weight: 600;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
  text-transform: capitalize;
}

/* Slot options as thumb-sized tap cards — state readable at arm's length. */
.slot-checkbox {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  min-height: 48px;
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-2);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease;
}

.slot-checkbox input {
  margin: 0.15rem 0 0;
  flex-shrink: 0;
}

.slot-checkbox-label {
  flex: 1;
  line-height: 1.4;
}

.slot-checkbox:has(input:checked) {
  border-color: var(--color-brand);
  background: var(--color-brand-subtle);
}

.slot-checkbox:has(input:focus-visible) {
  outline: 2px solid var(--color-brand);
  outline-offset: 2px;
}

/* Ä4 (if-time): reassuring, non-blocking "very_full" note — info tokens,
   never warning/danger (deterring copy would corrupt honest slot
   declarations, spec 019 §Ä4). */
.very-full-hint {
  display: block;
  margin-top: var(--space-1);
  color: var(--color-info-text);
  font-size: var(--text-sm);
  font-weight: 400;
}

.request-copy {
  font-size: var(--text-sm);
  margin: var(--space-2) 0 var(--space-4);
}

.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}

/* Primary action stays under the thumb on phones. */
.submit-bar button {
  margin-bottom: 0;
}

@media (max-width: 640px) {
  .submit-bar {
    position: sticky;
    bottom: 0;
    z-index: 10;
    background: var(--color-surface);
    padding: var(--space-3) 0 var(--space-2);
    margin: 0 calc(var(--space-2) * -1);
    padding-inline: var(--space-2);
    box-shadow: var(--shadow-sticky);
  }
}

/* === Success: the celebration === */
.success {
  text-align: center;
  padding: var(--space-6) var(--space-4);
  background: var(--color-success-bg);
  border-radius: var(--radius-lg);
}

.success-emoji {
  font-size: 3.5rem;
  line-height: 1;
  margin: 0 0 var(--space-2);
}

.success h3 {
  color: var(--color-success-text);
  font-size: 1.6rem;
  margin-bottom: var(--space-2);
}

.success-lead {
  margin-bottom: var(--space-5);
}

.registration-details {
  text-align: left;
  background: var(--color-surface-raised);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-4);
}

.registration-details dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-1) var(--space-4);
  margin: 0;
}

.registration-details dt {
  font-weight: 600;
  color: var(--color-text-muted);
}

.registration-details dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.mail-note {
  text-align: left;
  font-size: 0.9em;
}

.manage-link-box {
  text-align: left;
  margin-bottom: 0;
}

.manage-link-text {
  font-size: var(--text-sm);
  margin-bottom: var(--space-2);
}

.manage-link-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}

.manage-link-url {
  flex: 1 1 100%;
  word-break: break-all;
  font-size: var(--text-xs);
  padding: var(--space-2);
  background: var(--color-surface-raised);
  border-radius: var(--radius-sm);
}

.manage-link-row button {
  flex: 1;
  margin: 0;
  min-height: 44px;
  white-space: nowrap;
}
</style>

<template>
  <article style="position: relative;">
    <!-- Loading -->
    <div v-if="loading" aria-busy="true">
      Anmeldung wird geladen...
    </div>

    <!-- Error -->
    <div v-else-if="error" role="alert" class="error">
      <h2>Fehler</h2>
      <p>{{ error }}</p>
    </div>

    <template v-else>
      <!-- Event info bar (shown on all states) -->
      <div v-if="eventInfo" class="event-info-bar">
        <div class="event-info-text">
          <strong>{{ eventInfo.name }}</strong>
          <span class="event-meta">{{ formatDate(eventInfo.start_at) }}<template v-if="eventInfo.location"> · {{ eventInfo.location }}</template></span>
        </div>
        <HelpButton @click="help.toggle(currentHelpKey)" />
      </div>

      <HelpPanel
        :help-key="help.helpKey.value"
        :open="help.isOpen.value"
        ref="helpPanelRef"
        @close="help.close()"
      />

      <!-- CANCELLED -->
      <template v-if="registration?.status === 'CANCELLED'">
        <section class="status-banner cancelled">
          <h2>Deine Anmeldung wurde storniert.</h2>
          <p>Über diesen Link ist keine neue Anmeldung möglich.</p>
        </section>
        <div class="registration-details">
          <dl>
            <dt>Name</dt><dd>{{ registration.name }}</dd>
            <dt>E-Mail</dt><dd>{{ registration.email }}</dd>
          </dl>
        </div>
        <router-link to="/" class="button secondary">Zur Startseite</router-link>
      </template>

      <!-- CHECKED_IN -->
      <template v-else-if="registration?.status === 'CHECKED_IN'">
        <section class="status-banner success">
          <h2>Du bist eingecheckt. Viel Spaß an Bord!</h2>
        </section>
        <div class="registration-details" v-if="groupMembers.length > 0">
          <h3>Passagierliste</h3>
          <ul class="group-list">
            <li v-for="(name, i) in groupMembers" :key="i">{{ name }}</li>
          </ul>
        </div>
      </template>

      <!-- REGISTERED -->
      <template v-else-if="registration?.status === 'REGISTERED'">
        <section class="status-banner info">
          <div class="status-icon">⏳</div>
          <h2>Anmeldung eingegangen</h2>
          <p>{{ statusMessage }}</p>
        </section>
        <div class="registration-details">
          <dl>
            <dt>Name</dt><dd>{{ registration.name }}</dd>
            <dt>E-Mail</dt><dd>{{ registration.email }}</dd>
            <dt>Personen</dt><dd>{{ registration.group_size }}</dd>
          </dl>
        </div>
        <div class="secondary-actions">
          <button @click="showCancelDialog = true" class="outline secondary cancel-btn">
            Doch nicht dabei
          </button>
        </div>
      </template>

      <!-- WAITLISTED -->
      <template v-else-if="registration?.status === 'WAITLISTED'">
        <section class="status-banner neutral">
          <div class="status-icon">📋</div>
          <h2>Du stehst auf der Warteliste</h2>
          <p>{{ statusMessage }}</p>
          <p class="waitlist-hint">Falls jemand absagt, rückst du automatisch nach.</p>
        </section>
        <div class="registration-details">
          <dl>
            <dt>Name</dt><dd>{{ registration.name }}</dd>
            <dt>E-Mail</dt><dd>{{ registration.email }}</dd>
            <dt>Personen</dt><dd>{{ registration.group_size }}</dd>
          </dl>
        </div>
        <div class="secondary-actions">
          <button @click="showCancelDialog = true" class="outline secondary cancel-btn">
            Doch nicht dabei
          </button>
        </div>
      </template>

      <!-- CONFIRMED (lottery winner, needs to confirm + enter names) -->
      <template v-else-if="registration?.status === 'CONFIRMED'">
        <section class="status-banner action-needed">
          <div class="status-icon">🎉</div>
          <h2>Platz reserviert — bitte bestätigen</h2>
          <p v-if="originalGroupSize > 1">
            Du hast bei der Verlosung einen Platz bekommen! Bestätige jetzt, dass du dabei bist, und trag die Namen aller Mitfahrenden ein.
          </p>
          <p v-else>
            Du hast bei der Verlosung einen Platz bekommen! Bestätige jetzt, dass du dabei bist.
          </p>
        </section>

        <div class="primary-action">
          <template v-if="originalGroupSize > 1">
            <h3>Passagierliste ({{ editableMembers.length }} von {{ originalGroupSize }} Personen)</h3>
            <p class="hint-text">
              Für die Passagierliste benötigen wir von allen Mitfahrenden den vollständigen
              Vor- und Nachnamen.
            </p>
          </template>

          <div v-if="confirmError" role="alert" class="error">{{ confirmError }}</div>

          <div class="name-fields">
            <div v-for="(_, i) in editableMembers" :key="i" class="name-field-row">
              <label :for="`member-${i}`">
                {{ i === 0 ? 'Dein Name (Vor- & Nachname)' : `Mitfahrer:in ${i + 1} (Vor- & Nachname)` }}
              </label>
              <div class="name-field-input">
                <input
                  :id="`member-${i}`"
                  v-model="editableMembers[i]"
                  type="text"
                  :placeholder="i === 0 ? 'z.B. Lena Schmidt' : `z.B. Jan Hansen`"
                  required
                />
                <button
                  v-if="i > 0 && editableMembers.length > 1"
                  @click="removeMember(i)"
                  class="remove-btn outline"
                  title="Person entfernen"
                  type="button"
                >✕</button>
              </div>
            </div>
          </div>

          <p v-if="originalGroupSize > 1 && editableMembers.length < originalGroupSize" class="hint-text hint-warning">
            Entfernte Personen können nicht wieder hinzugefügt werden — der Platz geht zurück an die Warteliste.
          </p>

          <button
            @click="handleConfirmWithNames"
            :disabled="confirming"
            :aria-busy="confirming"
            class="confirm-btn"
          >
            {{ confirming ? 'Wird bestätigt...' : 'Ja, ich bin dabei!' }}
          </button>
        </div>

        <div class="secondary-actions">
          <button @click="showCancelDialog = true" class="outline secondary cancel-btn">
            Doch nicht dabei
          </button>
        </div>
      </template>

      <!-- PARTICIPATING (confirmed, can edit names / remove members / cancel) -->
      <template v-else-if="registration?.status === 'PARTICIPATING'">
        <section class="status-banner success">
          <div class="status-icon">✓</div>
          <h2>Du bist dabei!</h2>
        </section>

        <!-- Festival branch (spec 019) — additive, keyed on event_type; SINGLE below is untouched -->
        <template v-if="isFestival">
          <!-- Mitmach-Hinweis (Ä16) — shown here + on the success screen, not
               on the empty registration form. -->
          <section v-if="eventInfo?.participation_hint" class="mitmach-box">
            <p class="mitmach-title">Pack mit an!</p>
            <p class="mitmach-text" v-html="linkify(eventInfo.participation_hint)"></p>
          </section>

          <div class="primary-action">
            <div class="registration-details festival-summary">
              <p><strong>Wann:</strong> {{ chosenSlotLabels.length ? chosenSlotLabels.join(', ') : '–' }}</p>
              <p><strong>Telefon:</strong> {{ phone || '–' }}</p>
              <p v-if="OVERNIGHT_ENABLED">
                <strong>{{ overnightStatusLine }}</strong>
              </p>
              <p><strong>Wer dabei ist:</strong></p>
              <ul class="group-list">
                <li>{{ registration?.name }} <span class="member-note">(du)</span></li>
                <!-- Spec 020: say per companion whether their code went out, so
                     the contact knows exactly whom they still have to chase. -->
                <li v-for="entry in companionStatuses" :key="entry.personIndex">
                  {{ entry.name }}
                  <span v-if="entry.email" class="member-note member-note-sent">
                    Code an {{ maskEmail(entry.email) }} geschickt
                  </span>
                  <span v-else class="member-note">
                    Kein Code verschickt — leite ihren QR weiter
                  </span>
                </li>
              </ul>
            </div>

            <!-- Entry-code QR cards (spec 019 §P3, T309) — absent when the P3
                 backend isn't live yet (qr_payloads not present), matching
                 the F2 email variant note (spec.md:205). -->
            <div v-if="qrPayloads.length" class="qr-codes-section">
              <h3>Eure Eintritts-Codes</h3>
              <p class="hint-text">
                Schick jeder Begleitung ihren Code — am Einlass zeigt jede Person ihren
                eigenen vor. Ein Screenshot reicht völlig.
              </p>
              <!-- All codes stay here even when a companion got their own mail:
                   the contact can always forward, and a badge marks who already
                   has theirs (spec 020). -->
              <div class="qr-card-grid">
                <div v-for="payload in qrPayloads" :key="payload.person_index" class="qr-card">
                  <canvas :ref="(el) => setQrCanvasRef(payload.person_index, el)"></canvas>
                  <p class="qr-card-name">{{ payload.name }}</p>
                  <p v-if="emailedPersonIndices.has(payload.person_index)" class="qr-card-sent">
                    hat ihren Code per Mail
                  </p>
                </div>
              </div>
            </div>

            <div class="festival-edit-controls">
              <button
                v-if="isEditable && !editingFestival"
                @click="startEditingFestival"
                class="outline festival-edit-btn"
                type="button"
              >
                {{ OVERNIGHT_ENABLED ? 'Zeiten, Übernachtung oder Begleitungen ändern' : 'Zeiten oder Begleitungen ändern' }}
              </button>
              <p v-else-if="!isEditable && eventInfo?.contact_hint" class="hint-text hint-warning">
                Deine Zeiten kannst du nicht mehr selbst ändern — schreib uns einfach an {{ eventInfo.contact_hint }}
              </p>
            </div>

            <div v-if="editingFestival" class="festival-edit-form">
              <div v-if="saveError" role="alert" class="error">{{ saveError }}</div>
              <div v-if="saveSuccess" role="status" class="success-msg">{{ saveSuccess }}</div>

              <fieldset class="slot-grid">
                <legend>Wann bist du dabei?</legend>
                <div v-for="group in editSlotsByDate" :key="group.date" class="slot-day-group">
                  <p class="slot-day-heading">{{ formatWeekdayHeading(group.date) }}</p>
                  <label v-for="slot in group.slots" :key="slot.key" class="slot-checkbox">
                    <input type="checkbox" v-model="editSlots[slot.key]" :disabled="saving" />
                    <span class="slot-checkbox-label">{{ slot.label }}</span>
                  </label>
                </div>
              </fieldset>

              <label for="edit-phone">
                Telefonnummer *
                <input id="edit-phone" v-model="editPhone" type="tel" required :disabled="saving" />
              </label>

              <fieldset v-if="OVERNIGHT_ENABLED" class="overnight-fieldset">
                <legend>Übernachtest du auf dem Gelände?</legend>
                <p class="field-note">
                  Wie viele Zelte und/oder Camper/Wohnwagen bringt ihr mit? Gezählt werden
                  Zelte/Fahrzeuge (für die Stellplatz-Planung), nicht Personen. Beides möglich.
                  Nichts eintragen = keine Übernachtung.
                </p>
                <div class="overnight-counts">
                  <label class="accommodation-count">
                    Zelte
                    <input v-model.number="editTentCount" type="number" min="0" :max="editGroupSize" :disabled="saving" />
                  </label>
                  <label class="accommodation-count">
                    Camper/Wohnwagen
                    <input v-model.number="editCamperCount" type="number" min="0" :max="editGroupSize" :disabled="saving" />
                  </label>
                </div>

                <p v-if="editWantsOvernight" class="request-copy">
                  Schlafplätze sind begrenzt — deine Angabe ist eine Anfrage, keine Zusage. Wir melden uns bei dir.
                </p>
              </fieldset>

              <fieldset class="extra-members">
                <legend>Wen bringst du mit?</legend>
                <p class="field-note">
                  E-Mail (optional) — dann schicken wir den Eintritts-Code direkt an die Person.
                  Ohne E-Mail bekommst du alle Codes und leitest sie selbst weiter.
                </p>
                <div v-for="(entry, i) in memberEntries" :key="entry.index" class="name-field-row">
                  <label :for="`festival-member-${entry.index}`">
                    {{ entry.index === 0 ? 'Dein Name (Vor- & Nachname)' : `Begleitung (Vor- & Nachname)` }}
                  </label>
                  <div class="name-field-input">
                    <input
                      :id="`festival-member-${entry.index}`"
                      v-model="entry.value"
                      type="text"
                      maxlength="200"
                      :disabled="saving || entry.index === 0"
                    />
                    <button
                      v-if="entry.index > 0"
                      @click="removeFestivalMember(i)"
                      :disabled="saving"
                      class="remove-btn outline"
                      title="Person entfernen"
                      type="button"
                    >✕</button>
                  </div>
                  <!-- Spec 020: give a companion an address and they get their
                       own Eintritts-Code by mail instead of you forwarding it. -->
                  <input
                    v-if="entry.index > 0"
                    v-model="entry.email"
                    type="email"
                    maxlength="200"
                    placeholder="E-Mail (optional)"
                    :disabled="saving"
                    class="member-email-input"
                  />
                  <small
                    v-if="entry.index > 0 && entry.email && !looksLikeEmail(entry.email)"
                    class="hint-text hint-warning"
                  >
                    Diese E-Mail-Adresse sieht nicht richtig aus
                  </small>
                </div>
                <button type="button" class="outline" @click="addFestivalMember" :disabled="saving">
                  + Noch jemand kommt mit
                </button>
              </fieldset>

              <button
                @click="handleSaveFestival"
                :disabled="saving"
                :aria-busy="saving"
                class="save-btn"
              >
                {{ saving ? 'Wird gespeichert...' : 'Speichern' }}
              </button>
              <button type="button" class="secondary outline" @click="editingFestival = false" :disabled="saving">
                Abbrechen
              </button>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="primary-action">
            <h3>Passagierliste</h3>
            <p class="hint-text">
              Für die Passagierliste brauchen wir von allen Mitfahrenden den vollständigen
              Vor- und Nachnamen.
            </p>

            <div v-if="saveError" role="alert" class="error">{{ saveError }}</div>
            <div v-if="saveSuccess" role="status" class="success-msg">{{ saveSuccess }}</div>

            <div class="name-fields">
              <div v-for="(_, i) in editableMembers" :key="i" class="name-field-row">
                <label :for="`member-${i}`">
                  {{ i === 0 ? 'Dein Name (Vor- & Nachname)' : `Mitfahrer:in ${i + 1} (Vor- & Nachname)` }}
                </label>
                <div class="name-field-input">
                  <input
                    :id="`member-${i}`"
                    v-model="editableMembers[i]"
                    type="text"
                    :placeholder="i === 0 ? 'z.B. Lena Schmidt' : `z.B. Jan Hansen`"
                    required
                  />
                  <button
                    v-if="i > 0 && editableMembers.length > 1"
                    @click="handleRemoveMember(i)"
                    :disabled="saving"
                    class="remove-btn outline"
                    title="Person entfernen"
                    type="button"
                  >✕</button>
                </div>
              </div>
            </div>

            <p v-if="editableMembers.length < originalGroupSize" class="hint-text hint-warning">
              Entfernte Personen können nicht wieder hinzugefügt werden — der Platz geht zurück an die Warteliste.
            </p>

            <button
              v-if="hasUnsavedChanges"
              @click="handleSaveNames"
              :disabled="saving"
              :aria-busy="saving"
              class="save-btn"
            >
              {{ saving ? 'Wird gespeichert...' : 'Speichern' }}
            </button>
          </div>
        </template>

        <div class="secondary-actions">
          <button @click="showCancelDialog = true" class="outline secondary cancel-btn">
            Doch nicht dabei
          </button>
        </div>
      </template>

      <!-- Cancel confirmation dialog -->
      <dialog :open="showCancelDialog || undefined">
        <article style="max-width: 500px;">
          <header>
            <button
              @click="showCancelDialog = false"
              aria-label="Schließen"
              rel="prev"
            ></button>
            <h3>Wirklich stornieren?</h3>
          </header>

          <!-- Festival guests never went through a lottery — their own copy (spec 019). -->
          <p v-if="isFestival" class="warning-box">
            Deine Anmeldung wird storniert — auch für deine Begleitungen. Das lässt sich
            nicht rückgängig machen. Falls du es dir anders überlegst, schreib
            uns<template v-if="eventInfo?.contact_hint"> an {{ eventInfo.contact_hint }}</template>.
          </p>
          <p v-else-if="registration?.status === 'PARTICIPATING'" class="warning-box">
            Du hast deinen Platz über die Verlosung bekommen. Wenn du jetzt stornierst,
            ist der Platz weg — das lässt sich nicht rückgängig machen.
          </p>
          <p v-else class="warning-box">
            Das lässt sich nicht rückgängig machen. Wenn du doch mitfahren willst,
            musst du dich neu anmelden.
          </p>

          <div v-if="cancelError" role="alert" class="error">{{ cancelError }}</div>

          <footer>
            <button @click="showCancelDialog = false" class="secondary">
              Nee, doch nicht
            </button>
            <button
              @click="handleCancel"
              :disabled="cancelling"
              :aria-busy="cancelling"
              class="cancel-confirm-btn"
            >
              {{ cancelling ? 'Wird storniert...' : 'Ja, stornieren' }}
            </button>
          </footer>
        </article>
      </dialog>
    </template>
  </article>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import QRCode from 'qrcode'
import { publicApi } from '../../services/api'
import { formatDate } from '../../utils/formatters.js'
import { linkify } from '../../utils/linkify.js'
import { OVERNIGHT_ENABLED } from '../../config/festival.js'
import HelpButton from '../../components/help/HelpButton.vue'
import HelpPanel from '../../components/help/HelpPanel.vue'
import { useHelp } from '../../components/help/useHelp.js'

const route = useRoute()
const help = useHelp()
const helpPanelRef = ref(null)
watch(helpPanelRef, (el) => { help.panelRef.value = el?.$el || el })

const currentHelpKey = computed(() => {
  // Festival branch (spec 019): one flow-story entry for active festival
  // guests — the SINGLE status texts talk about Verlosung/Warteliste, which
  // festival guests never see. The generic cancelled text fits both worlds.
  if (isFestival.value && registration.value?.status !== 'CANCELLED') return 'manage-festival'
  if (!registration.value?.status) return 'manage-registered'
  return `manage-${registration.value.status.toLowerCase()}`
})

// State
const loading = ref(true)
const error = ref(null)
const registration = ref(null)
const eventInfo = ref(null)
const groupMembers = ref([])
const originalGroupSize = ref(0)
const statusMessage = ref('')
const editableMembers = ref([])
const lastSavedMembers = ref([])

// Action states
const confirming = ref(false)
const confirmError = ref(null)
const saving = ref(false)
const saveError = ref(null)
const saveSuccess = ref(null)
const cancelling = ref(false)
const cancelError = ref(null)
const showCancelDialog = ref(false)

// Festival branch state (spec 019) — additive, only populated when eventInfo.event_type === 'FESTIVAL'
const attendanceSlots = ref([])
const tentCount = ref(null)
const camperCount = ref(null)
const phone = ref(null)
const overnightApproved = ref(false)
const editableUntil = ref(null)
const editingFestival = ref(false)
const editSlots = ref({})
const editTentCount = ref(0)
const editCamperCount = ref(0)
const editPhone = ref('')
const memberEntries = ref([])
const nextMemberIndex = ref(0)
// Spec 020 — index-aligned with `group_members`: entry i is the address of
// group_members[i] (person_index i+1). Drives the per-companion "Code
// geschickt" line and is round-tripped on save.
const groupMemberEmails = ref([])

// Group size while editing = contact + filled companion rows; caps each
// tent/camper count (a group can't bring more units than it has people).
const editGroupSize = computed(
  () => 1 + memberEntries.value.filter((e) => e.index > 0 && (e.value || '').trim()).length,
)

// Ä21: any overnight wish = at least one tent or camper.
const editWantsOvernight = computed(
  () => Number(editTentCount.value) > 0 || Number(editCamperCount.value) > 0,
)

// Entry-code QR cards (spec 019 §P3, T309) — freshly signed on every GET,
// never cached; re-drawn whenever qrPayloads changes (initial load, or
// after a slot/group edit reload).
const qrPayloads = ref([])
const qrCanvasEls = {}

function setQrCanvasRef(personIndex, el) {
  if (el) qrCanvasEls[personIndex] = el
}

async function renderQrCodes() {
  await nextTick()
  for (const payload of qrPayloads.value) {
    const canvas = qrCanvasEls[payload.person_index]
    if (!canvas) continue
    try {
      await QRCode.toCanvas(canvas, payload.code, { width: 240, margin: 2 })
    } catch {
      // Non-critical — the card just shows a blank canvas.
    }
  }
}

watch(qrPayloads, renderQrCodes)

const isFestival = computed(() => eventInfo.value?.event_type === 'FESTIVAL')

const isEditable = computed(() => {
  if (!isFestival.value) return false
  if (!editableUntil.value) return false
  if (registration.value?.status === 'CANCELLED') return false
  return new Date() < new Date(editableUntil.value)
})

// Chosen slot labels, in festival (config) order — never in attendance_slots' own order.
const chosenSlotLabels = computed(() => {
  const slots = eventInfo.value?.festival_slots || []
  return slots.filter((s) => attendanceSlots.value.includes(s.key)).map((s) => s.label)
})

const overnightStatusLine = computed(() => {
  const parts = []
  if (tentCount.value) parts.push(`${tentCount.value} ${tentCount.value === 1 ? 'Zelt' : 'Zelte'}`)
  if (camperCount.value) parts.push(`${camperCount.value} Camper`)
  if (parts.length === 0) return 'Übernachtung: Nein'
  return `Übernachtung: ${parts.join(', ')} — ${overnightApproved.value ? 'zugesagt' : 'angefragt'}`
})

// Festival group_members are EXCLUSIVE of the contact person (spec §QR
// payload: person_index 0 = contact, 1.. = group_members) and may contain
// `null` tombstones for removed members (T109) — prepend the contact and
// skip tombstones in the display.
const visibleGroupMembers = computed(() => {
  if (!registration.value) return []
  const companions = (registration.value.group_members || []).filter(
    (m) => m !== null && m !== undefined,
  )
  return [registration.value.name, ...companions]
})

// Group the editable festival slots by day, weekday heading via Intl (duplicated from
// FestivalRegistrationPage.vue per T117 — do not touch the SINGLE branches with a shared import).
const editSlotsByDate = computed(() => {
  const slots = eventInfo.value?.festival_slots || []
  const groups = new Map()
  for (const slot of slots) {
    if (!groups.has(slot.date)) groups.set(slot.date, [])
    groups.get(slot.date).push(slot)
  }
  return Array.from(groups.entries()).map(([date, daySlots]) => ({ date, slots: daySlots }))
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

// Shape check only — the backend's EmailStr is the authority. Catches a typo
// before the round trip; a missing address is always fine (spec 020 D4).
function looksLikeEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((value || '').trim())
}

// Masked for display: the contact typed it, but this page can be open on a
// shared screen, and they only need to recognise WHICH address it was.
function maskEmail(value) {
  const raw = (value || '').trim()
  const at = raw.indexOf('@')
  if (at < 1) return raw
  return `${raw[0]}…@${raw.slice(at + 1)}`
}

// Companions paired with their stored address, for the summary list. Index i of
// group_members is person_index i+1; tombstones are dropped for display but
// never renumbered.
// person_index values that already received their own mail — badges the QR cards.
const emailedPersonIndices = computed(
  () =>
    new Set(
      (groupMemberEmails.value || [])
        .map((email, idx) => (email ? idx + 1 : null))
        .filter((v) => v !== null),
    ),
)

const companionStatuses = computed(() => {
  const members = registration.value?.group_members || []
  const emails = groupMemberEmails.value || []
  return members
    .map((name, idx) => ({ name, email: emails[idx] || null, personIndex: idx + 1 }))
    .filter((entry) => entry.name)
})

const hasUnsavedChanges = computed(() => {
  if (editableMembers.value.length !== lastSavedMembers.value.length) return true
  return editableMembers.value.some((name, i) => name !== lastSavedMembers.value[i])
})

async function loadRegistration() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  if (!registrationId || !token) {
    error.value = 'Ungültiger Link. Schau nochmal in deiner E-Mail nach.'
    loading.value = false
    return
  }

  try {
    const result = await publicApi.getRegistrationManage(registrationId, token)
    registration.value = result.registration
    eventInfo.value = result.event
    groupMembers.value = result.group_members
    originalGroupSize.value = result.original_group_size
    statusMessage.value = result.message
    editableMembers.value = [...result.group_members]
    lastSavedMembers.value = [...result.group_members]
    attendanceSlots.value = result.attendance_slots || []
    tentCount.value = result.tent_count || null
    camperCount.value = result.camper_count || null
    phone.value = result.phone || null
    overnightApproved.value = result.overnight_approved || false
    editableUntil.value = result.editable_until || null
    editingFestival.value = false
    qrPayloads.value = result.qr_payloads || []
    groupMemberEmails.value = result.group_member_emails || []
  } catch (err) {
    if (err.message?.includes('404')) {
      error.value = 'Anmeldung nicht gefunden. Schau nochmal in deiner E-Mail nach.'
    } else {
      error.value = err.message || 'Da ist was schiefgelaufen. Versuch es nochmal.'
    }
  } finally {
    loading.value = false
  }
}

function removeMember(index) {
  if (editableMembers.value.length > 1 && index > 0) {
    editableMembers.value.splice(index, 1)
  }
}

async function handleConfirmWithNames() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  // Validate all names filled
  const names = editableMembers.value.map(n => n.trim())
  if (names.some(n => !n)) {
    confirmError.value = 'Bitte trag alle Namen ein (Vor- und Nachname).'
    return
  }

  confirming.value = true
  confirmError.value = null

  try {
    const result = await publicApi.confirmWithNames(registrationId, token, names)
    registration.value = result.registration
    eventInfo.value = result.event || eventInfo.value
    groupMembers.value = result.group_members
    originalGroupSize.value = result.original_group_size
    editableMembers.value = [...result.group_members]
    lastSavedMembers.value = [...result.group_members]
    statusMessage.value = result.message
  } catch (err) {
    confirmError.value = err.message || 'Das hat leider nicht geklappt. Versuch es nochmal.'
  } finally {
    confirming.value = false
  }
}

async function handleRemoveMember(index) {
  if (editableMembers.value.length <= 1 || index === 0) return

  // Build the new list without the removed member
  const newMembers = editableMembers.value.filter((_, i) => i !== index).map(n => n.trim())
  if (newMembers.some(n => !n)) {
    saveError.value = 'Bitte erst alle Namen ausfüllen, bevor du jemanden entfernst.'
    return
  }

  saving.value = true
  saveError.value = null
  saveSuccess.value = null

  const registrationId = route.params.registrationId
  const token = route.query.token

  try {
    const result = await publicApi.updateGroupMembers(registrationId, token, newMembers)
    // Only update local state after API success
    registration.value = result.registration
    groupMembers.value = result.group_members
    editableMembers.value = [...result.group_members]
    lastSavedMembers.value = [...result.group_members]
    saveSuccess.value = 'Person entfernt. Schade!'
    setTimeout(() => { saveSuccess.value = null }, 3000)
  } catch (err) {
    // API failed — do NOT remove locally, state stays as-is
    saveError.value = err.message || 'Das hat leider nicht geklappt.'
  } finally {
    saving.value = false
  }
}

async function handleSaveNames() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  const names = editableMembers.value.map(n => n.trim())
  if (names.some(n => !n)) {
    saveError.value = 'Bitte alle Namen ausfüllen (Vor- und Nachname).'
    return
  }

  saving.value = true
  saveError.value = null
  saveSuccess.value = null

  try {
    const result = await publicApi.updateGroupMembers(registrationId, token, names)
    registration.value = result.registration
    groupMembers.value = result.group_members
    editableMembers.value = [...result.group_members]
    lastSavedMembers.value = [...result.group_members]
    saveSuccess.value = 'Gespeichert!'
    setTimeout(() => { saveSuccess.value = null }, 3000)
  } catch (err) {
    saveError.value = err.message || 'Speichern hat nicht geklappt. Versuch es nochmal.'
  } finally {
    saving.value = false
  }
}

function startEditingFestival() {
  const slotMap = {}
  for (const slot of (eventInfo.value?.festival_slots || [])) {
    slotMap[slot.key] = attendanceSlots.value.includes(slot.key)
  }
  editSlots.value = slotMap
  editTentCount.value = tentCount.value || 0
  editCamperCount.value = camperCount.value || 0
  editPhone.value = phone.value || ''

  // Entry index 0 is the contact person (read-only, not part of
  // group_members); companions live at entry index i+1 for
  // group_members[i] — the EXCLUSIVE convention (spec §QR payload).
  const companions = registration.value?.group_members || []
  const companionEmails = groupMemberEmails.value || []
  memberEntries.value = [
    { index: 0, value: registration.value?.name || '', email: '' },
    ...companions
      .map((name, idx) => ({
        index: idx + 1,
        value: name,
        // Same index on purpose — the two arrays are read in lockstep.
        email: companionEmails[idx] || '',
      }))
      .filter((entry) => entry.value !== null && entry.value !== undefined),
  ]
  nextMemberIndex.value = companions.length + 1

  saveError.value = null
  saveSuccess.value = null
  editingFestival.value = true
}

function addFestivalMember() {
  memberEntries.value.push({ index: nextMemberIndex.value, value: '', email: '' })
  nextMemberIndex.value += 1
}

function removeFestivalMember(i) {
  if (memberEntries.value[i]?.index === 0) return
  memberEntries.value.splice(i, 1)
}

async function handleSaveFestival() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  saveError.value = null
  saveSuccess.value = null

  const selectedSlotKeys = Object.keys(editSlots.value).filter((key) => editSlots.value[key])
  if (selectedSlotKeys.length === 0) {
    saveError.value = 'Bitte wähle mindestens einen Zeitraum aus.'
    return
  }

  // Entry index 0 is the read-only contact row — only companions are
  // validated and sent (group_members is EXCLUSIVE of the contact).
  const companionEntries = memberEntries.value
    .filter((entry) => entry.index > 0)
    .map((entry) => ({
      index: entry.index,
      value: entry.value.trim(),
      email: (entry.email || '').trim().toLowerCase(),
    }))
  if (companionEntries.some((entry) => !entry.value || !hasTwoWords(entry.value))) {
    saveError.value = 'Bitte Vor- und Nachnamen angeben'
    return
  }

  const badEmailEntry = companionEntries.find(
    (entry) => entry.email && !looksLikeEmail(entry.email),
  )
  if (badEmailEntry) {
    saveError.value = `Die E-Mail-Adresse von ${badEmailEntry.value} sieht nicht richtig aus.`
    return
  }

  // OVERNIGHT_ENABLED gate (Stellplatz ungeklärt, 19.7.): while disabled,
  // overnight counts never leave this form. Phone is required independently
  // of overnight/OVERNIGHT_ENABLED. Counts clamped to 0..group_size.
  const nextGroupSize = 1 + companionEntries.filter((entry) => entry.value).length
  const clampCount = (v) => Math.min(Math.max(0, Number(v) || 0), nextGroupSize)
  const nextTentCount = OVERNIGHT_ENABLED ? clampCount(editTentCount.value) : 0
  const nextCamperCount = OVERNIGHT_ENABLED ? clampCount(editCamperCount.value) : 0
  const trimmedPhone = editPhone.value.trim()
  if (!trimmedPhone) {
    saveError.value = 'Bitte gib deine Telefonnummer an.'
    return
  }

  // group_members is APPEND-ONLY with tombstones (T109) — never shrink below
  // the current raw length; indices not present here stay/become `null`
  // tombstones. Companion entry index i maps to group_members[i - 1] (the
  // contact is index 0 and never part of the patch).
  const rawLen = registration.value?.group_members?.length || 0
  const total = Math.max(rawLen, ...companionEntries.map((entry) => entry.index), 0)
  const groupMembersPatch = new Array(total).fill(null)
  const groupMemberEmailsPatch = new Array(total).fill(null)
  for (const entry of companionEntries) {
    // One loop, both arrays — filling them separately is how they drift apart.
    groupMembersPatch[entry.index - 1] = entry.value
    groupMemberEmailsPatch[entry.index - 1] = entry.email || null
  }

  saving.value = true

  try {
    await publicApi.updateFestivalAttendance(registrationId, token, {
      attendance_slots: selectedSlotKeys,
      tent_count: nextTentCount || null,
      camper_count: nextCamperCount || null,
      phone: trimmedPhone,
      group_members: groupMembersPatch,
      group_member_emails: groupMemberEmailsPatch,
    })
    editingFestival.value = false
    saveSuccess.value = 'Alles klar — deine Änderung ist gespeichert!'
    await loadRegistration()
    setTimeout(() => { saveSuccess.value = null }, 3000)
  } catch (err) {
    saveError.value = err.message || 'Speichern hat nicht geklappt. Versuch es nochmal.'
  } finally {
    saving.value = false
  }
}

async function handleCancel() {
  const registrationId = route.params.registrationId
  const token = route.query.token

  cancelling.value = true
  cancelError.value = null

  try {
    await publicApi.cancelRegistration(registrationId, token)
    // Reload to show cancelled state
    showCancelDialog.value = false
    await loadRegistration()
  } catch (err) {
    cancelError.value = err.message || 'Stornierung hat nicht geklappt. Versuch es nochmal.'
  } finally {
    cancelling.value = false
  }
}

onMounted(loadRegistration)
</script>

<style scoped>
.event-info-bar {
  background: var(--color-bg-subtle);
  border: 1px solid var(--color-border);
  border-radius: var(--pico-border-radius);
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
  display: flex;
  gap: 0.5rem;
  align-items: center;
  justify-content: space-between;
}

.event-info-text {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
}

.event-meta {
  color: var(--color-text-muted);
  font-size: 0.9em;
}

.status-banner {
  text-align: center;
  padding: 2rem;
  border-radius: var(--pico-border-radius);
  margin-bottom: 1.5rem;
}

.status-banner.success {
  background: var(--color-success-bg);
}
.status-banner.success h2 {
  color: var(--color-success-text);
}

.status-banner.action-needed {
  background: var(--color-warning-bg);
  border: 2px solid var(--color-warning-text);
}
.status-banner.action-needed h2 {
  color: var(--color-warning-text);
}
.status-banner.action-needed p {
  color: var(--color-warning-text);
}

.status-banner.cancelled {
  background: var(--color-danger-bg);
}
.status-banner.cancelled h2 {
  color: var(--color-danger-text);
}

.status-banner.neutral {
  background: var(--color-surface-sunken);
}

.status-banner.info {
  background: var(--color-info-bg);
}
.status-banner.info h2 {
  color: var(--color-info-text);
}

.waitlist-hint {
  font-size: var(--text-sm);
  color: var(--color-neutral-text);
  font-style: italic;
}

.status-icon {
  font-size: 3rem;
  margin-bottom: 0.5rem;
}

.status-banner.success .status-icon {
  color: var(--color-success-text);
}

.registration-details {
  background: var(--color-surface-raised);
  padding: 1rem;
  border-radius: var(--pico-border-radius);
  margin-bottom: 1.5rem;
}

.registration-details dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  margin: 0;
}

.registration-details dt {
  font-weight: bold;
}

.primary-action {
  margin-bottom: 2rem;
}

.hint-text {
  font-size: 0.875rem;
  color: var(--color-text-muted);
  margin-bottom: 1rem;
}

.hint-warning {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  padding: 0.5rem 0.75rem;
  border-radius: var(--pico-border-radius);
}

/* Mitmach-Hinweis (Ä16) — mirrors the registration page's .callout-warm look. */
.mitmach-box {
  background: var(--color-accent-subtle);
  border-left: 4px solid var(--color-accent);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-5);
}

.mitmach-title {
  font-weight: 700;
  color: var(--color-accent-hover);
  margin: 0 0 var(--space-1);
}

.mitmach-text {
  margin: 0;
}

.name-fields {
  margin-bottom: 1rem;
}

.name-field-row {
  margin-bottom: 0.75rem;
}

.name-field-row label {
  font-size: 0.875rem;
  font-weight: 500;
  margin-bottom: 0.25rem;
}

.name-field-input {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}

.name-field-input input {
  flex: 1;
  margin-bottom: 0;
}

.remove-btn {
  padding: 0.5rem 0.75rem;
  color: var(--color-danger-text);
  border-color: var(--color-danger-text);
  flex-shrink: 0;
  margin-bottom: 0;
}

.confirm-btn {
  --pico-primary: #16a34a;
  --pico-primary-hover: #15803d;
  --pico-primary-focus: rgba(22, 163, 74, 0.25);
  width: 100%;
  padding: 0.75rem;
  font-size: 1.1rem;
}

.save-btn {
  width: 100%;
  padding: 0.75rem;
}

.secondary-actions {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--color-border);
}

.cancel-btn {
  --pico-primary: #dc2626;
  --pico-primary-hover: #b91c1c;
  --pico-primary-focus: rgba(220, 38, 38, 0.25);
}

.cancel-confirm-btn {
  --pico-primary: #dc2626;
  --pico-primary-hover: #b91c1c;
  --pico-primary-focus: rgba(220, 38, 38, 0.25);
}

.warning-box {
  background: var(--color-warning-bg);
  padding: 0.75rem;
  border-radius: var(--pico-border-radius);
  color: var(--color-warning-text);
  font-size: 0.9em;
}

.error {
  color: var(--color-danger-text);
  padding: 0.75rem;
  background: var(--color-danger-bg);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.success-msg {
  color: var(--color-success-text);
  padding: 0.75rem;
  background: var(--color-success-bg);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.group-list {
  list-style: none;
  padding: 0;
}

.group-list li {
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--color-border);
}

.group-list li:last-child {
  border-bottom: none;
}

/* Spec 020 — per-companion code status, secondary to the name itself. */
.member-note {
  display: block;
  font-size: 0.85rem;
  color: var(--pico-muted-color, #6b7280);
}

.member-note-sent {
  color: var(--pico-ins-color, #16a34a);
}

.member-email-input {
  margin-top: 0.5rem;
  margin-bottom: 0;
}

.qr-card-sent {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  color: var(--pico-muted-color, #6b7280);
}

.button.secondary {
  display: inline-block;
  text-decoration: none;
  padding: 0.5rem 1rem;
  border-radius: var(--pico-border-radius);
}

/* Festival branch (spec 019) — additive */
.festival-summary p {
  margin-bottom: var(--space-2);
}

.festival-summary .group-list {
  margin: 0;
}

.qr-codes-section {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  margin-bottom: 1.5rem;
}

.qr-codes-section h3 {
  margin-bottom: 0.25rem;
}

.qr-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}

.qr-card {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--pico-border-radius);
  padding: 0.75rem;
  text-align: center;
}

.qr-card canvas {
  max-width: 100%;
  height: auto;
}

.qr-card-name {
  margin: 0.5rem 0 0;
  font-weight: 500;
  word-break: break-word;
}

.festival-edit-controls {
  margin: 1rem 0;
}

.festival-edit-btn {
  width: 100%;
  min-height: 44px;
}

.festival-edit-form {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--color-border);
}

.extra-members {
  border: none;
  padding: 0;
  margin: 0 0 var(--pico-spacing);
}

.extra-members legend {
  padding: 0;
  font-weight: bold;
  font-size: var(--text-sm);
  margin-bottom: 0.25rem;
}

.slot-grid,
.overnight-fieldset {
  border: none;
  padding: 0;
  margin: 0 0 var(--pico-spacing);
}

.slot-grid legend,
.overnight-fieldset legend {
  padding: 0;
  font-weight: bold;
  margin-bottom: 0.5rem;
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

/* Slot options as thumb-sized tap cards — same recipe as the public
   registration form (FestivalRegistrationPage.vue). */
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

.request-copy {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border-left: 4px solid var(--color-warning-text);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  margin: 0.5rem 0 1rem;
}
</style>

<template>
  <article>
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
        <strong>{{ eventInfo.name }}</strong>
        <span class="event-meta">{{ eventInfo.start_at }}<template v-if="eventInfo.location"> · {{ eventInfo.location }}</template></span>
      </div>

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
        <section class="status-banner neutral">
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
          <div class="status-icon">⏳</div>
          <h2>Du stehst auf der Warteliste</h2>
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

      <!-- CONFIRMED (lottery winner, needs to confirm + enter names) -->
      <template v-else-if="registration?.status === 'CONFIRMED'">
        <section class="status-banner success">
          <h2>Du hast einen Platz bekommen!</h2>
          <p v-if="originalGroupSize > 1">
            Bitte bestätige, dass du dabei bist und trag die Namen aller Mitfahrenden ein.
          </p>
          <p v-else>
            Bitte bestätige kurz, dass du dabei bist.
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

        <div class="secondary-actions">
          <button @click="showCancelDialog = true" class="outline secondary cancel-btn">
            Doch nicht dabei
          </button>
        </div>
      </template>

      <!-- Cancel confirmation dialog -->
      <dialog ref="cancelDialog" :open="showCancelDialog || undefined">
        <article style="max-width: 500px;">
          <header>
            <button
              @click="showCancelDialog = false"
              aria-label="Schließen"
              rel="prev"
            ></button>
            <h3>Wirklich stornieren?</h3>
          </header>

          <p v-if="registration?.status === 'PARTICIPATING'" class="warning-box">
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
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { publicApi } from '../../services/api'

const route = useRoute()

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
const cancelDialog = ref(null)

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
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: var(--pico-border-radius);
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
}

.event-meta {
  color: #64748b;
  font-size: 0.9em;
}

.status-banner {
  text-align: center;
  padding: 2rem;
  border-radius: var(--pico-border-radius);
  margin-bottom: 1.5rem;
}

.status-banner.success {
  background: var(--pico-color-green-50, #f0fff4);
}
.status-banner.success h2 {
  color: var(--pico-color-green-600, #2f855a);
}

.status-banner.cancelled {
  background: #fef2f2;
}
.status-banner.cancelled h2 {
  color: #dc2626;
}

.status-banner.neutral {
  background: #f5f5f5;
}

.status-icon {
  font-size: 3rem;
  margin-bottom: 0.5rem;
}

.status-banner.success .status-icon {
  color: var(--pico-color-green-600, #2f855a);
}

.registration-details {
  background: white;
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
  color: #64748b;
  margin-bottom: 1rem;
}

.hint-warning {
  color: #92400e;
  background: #fef3c7;
  padding: 0.5rem 0.75rem;
  border-radius: var(--pico-border-radius);
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
  color: #dc2626;
  border-color: #dc2626;
  flex-shrink: 0;
  margin-bottom: 0;
}

.confirm-btn {
  background: #16a34a !important;
  border-color: #16a34a !important;
  color: white !important;
  width: 100%;
  padding: 0.75rem;
  font-size: 1.1rem;
}

.confirm-btn:hover:not(:disabled) {
  background: #15803d !important;
  border-color: #15803d !important;
}

.save-btn {
  width: 100%;
  padding: 0.75rem;
}

.secondary-actions {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
}

.cancel-btn {
  color: #dc2626 !important;
  border-color: #dc2626 !important;
}

.cancel-confirm-btn {
  background: #dc2626 !important;
  border-color: #dc2626 !important;
  color: white !important;
}

.warning-box {
  background: #fef3c7;
  padding: 0.75rem;
  border-radius: var(--pico-border-radius);
  color: #92400e;
  font-size: 0.9em;
}

.error {
  color: var(--pico-color-red-500, #dc3545);
  padding: 0.75rem;
  background: var(--pico-color-red-50, #fff5f5);
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.success-msg {
  color: #16a34a;
  padding: 0.75rem;
  background: #f0fff4;
  border-radius: var(--pico-border-radius);
  margin-bottom: 1rem;
}

.group-list {
  list-style: none;
  padding: 0;
}

.group-list li {
  padding: 0.5rem 0;
  border-bottom: 1px solid #e2e8f0;
}

.group-list li:last-child {
  border-bottom: none;
}

.button.secondary {
  display: inline-block;
  text-decoration: none;
  padding: 0.5rem 1rem;
  border-radius: var(--pico-border-radius);
}
</style>

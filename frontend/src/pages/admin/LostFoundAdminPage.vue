<template>
  <article class="lostfound-admin">
    <PageHeader back back-label="Zurück" :subtitle="eventName">
      <template #title>Fundsachen</template>
    </PageHeader>

    <div v-if="loading" aria-busy="true">Fundsachen-Seite wird geladen ...</div>

    <div v-else-if="loadError" role="alert" class="error">{{ loadError }}</div>

    <template v-else>
      <p v-if="!configured" class="hint-box">
        Noch keine Fundsachen-Seite. Trag die Adresse ein, unter der sich Gäste melden können —
        damit entsteht die Seite und ihr Link. Öffentlich sichtbar wird sie erst, wenn du sie
        veröffentlichst.
      </p>

      <!-- Konfiguration -->
      <div class="section-heading">
        <h3>Koordination</h3>
      </div>
      <section class="surface surface-padded">
        <form @submit.prevent="saveConfig">
          <label for="lnfEmail">
            E-Mail für Fundsachen
            <input
              id="lnfEmail"
              v-model.trim="form.coordinator_email"
              type="email"
              placeholder="fundsachen@schaluppe.de"
              :disabled="saving"
            />
            <small>Hier landen alle Mails — von Suchenden und von Findern.</small>
          </label>

          <label for="lnfTelegram">
            Telegram (Alternative zur E-Mail)
            <input
              id="lnfTelegram"
              v-model.trim="form.coordinator_telegram_url"
              type="text"
              placeholder="@fundsachen oder https://t.me/+Einladungslink"
              :disabled="saving"
            />
            <small>
              Handle oder Einladungslink zu einer Gruppe. Eines von beiden — E-Mail oder Telegram —
              muss gesetzt sein; beides zusammen geht auch.
            </small>
          </label>

          <label for="lnfName">
            Name (optional)
            <input
              id="lnfName"
              v-model.trim="form.coordinator_name"
              type="text"
              placeholder="Micha"
              :disabled="saving"
            />
            <small>Steht auf der Seite statt der nackten Adresse.</small>
          </label>

          <label for="lnfIntro">
            Eigener Einleitungstext (optional)
            <textarea
              id="lnfIntro"
              v-model="form.intro_text"
              rows="3"
              placeholder="Nach dem Festival ist eine ganze Kiste liegengeblieben ..."
              :disabled="saving"
            ></textarea>
            <small>
              Ersetzt nur den ersten Absatz. Was Gäste tun sollen, steht immer darunter.
            </small>
          </label>

          <label for="lnfRetention">
            Aufbewahrung in Tagen
            <input
              id="lnfRetention"
              v-model="form.retention_days"
              type="number"
              min="7"
              max="365"
              :placeholder="retentionPlaceholder"
              :disabled="saving"
              @input="retentionTouched = true"
            />
            <small>
              7 bis 365 Tage. Leer heißt: der Standardwert der Anlage gilt. Danach löscht sich die
              Seite mit allen Fotos selbst.
              <template v-if="expiresAt"> Aktuell: bis {{ formatDateOnly(expiresAt) }}.</template>
            </small>
          </label>

          <label for="lnfPublished" class="publish-toggle">
            <input
              id="lnfPublished"
              v-model="form.published"
              type="checkbox"
              role="switch"
              :disabled="saving"
            />
            Seite veröffentlichen
          </label>
          <p class="publish-hint">
            Solange der Schalter aus ist, läuft der Link ins Leere — Fotos hochladen und Text
            schreiben geht trotzdem.
          </p>

          <div v-if="saveError" role="alert" class="error">{{ saveError }}</div>

          <button type="submit" :disabled="saving" :aria-busy="saving">
            {{ saving ? 'Wird gespeichert ...' : 'Speichern' }}
          </button>
        </form>
      </section>

      <!-- Öffentlicher Link -->
      <template v-if="configured">
        <div class="section-heading">
          <h3>Öffentlicher Link</h3>
        </div>
        <section class="surface surface-padded">
          <code class="public-url">{{ publicUrl }}</code>
          <div class="link-actions">
            <button type="button" class="outline" @click="copyLink">Link kopieren</button>
            <!-- Unveröffentlicht antwortet der Link mit demselben 404 wie ein
                 falscher Token — das sieht wie ein Defekt aus, wenn man gerade
                 die Seite angelegt hat. Also sagen wir es hier. -->
            <a
              v-if="publishedSaved"
              role="button"
              class="outline"
              :href="publicUrl"
              target="_blank"
              rel="noopener"
            >
              Seite ansehen
            </a>
            <button v-else type="button" class="outline" disabled>
              Seite ansehen (erst nach Veröffentlichen)
            </button>
            <button
              type="button"
              class="outline secondary"
              :disabled="rotating"
              :aria-busy="rotating"
              @click="rotateToken"
            >
              Link neu erzeugen
            </button>
            <button
              type="button"
              class="outline btn-danger"
              :disabled="upload.uploading.value"
              @click="deleteDialogOpen = true"
            >
              Seite löschen
            </button>
          </div>
          <p class="hint-text">
            Der Link ist ungelistet — wer ihn hat, kommt rein. „Link neu erzeugen" ist die
            Notbremse, falls er in einer Facebook-Gruppe landet.
            <template v-if="upload.uploading.value">
              Löschen geht erst, wenn der Upload fertig ist.
            </template>
          </p>
        </section>

        <!-- Upload -->
        <div class="section-heading">
          <h3>Fotos hochladen</h3>
        </div>
        <section
          class="surface drop-zone"
          :class="{ 'drop-zone--over': dragOver }"
          @dragover.prevent="dragOver = true"
          @dragenter.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="handleDrop"
        >
          <p><strong>Fotos hierher ziehen</strong> oder auswählen.</p>
          <input
            type="file"
            multiple
            accept="image/*"
            :disabled="upload.uploading.value"
            @change="handlePick"
          />
          <p class="hint-text">
            Die Fotos werden im Browser verkleinert, bevor sie hochgehen — das spart Datenvolumen
            und entfernt alle EXIF-Daten samt GPS-Koordinaten. Es laufen höchstens
            {{ MAX_CONCURRENT }} Uploads gleichzeitig.
          </p>
        </section>

        <ul v-if="upload.items.value.length" class="upload-list">
          <li v-for="item in upload.items.value" :key="item.key" class="upload-row">
            <img v-if="item.preview" :src="item.preview" alt="" class="upload-preview" />
            <div class="upload-body">
              <span class="upload-name">{{ item.name }}</span>
              <small v-if="item.status === 'error'" class="upload-error">{{ item.error }}</small>
              <small v-else class="upload-state">
                {{ uploadStateLabel(item) }}
              </small>
              <progress
                v-if="!['error', 'done'].includes(item.status)"
                :value="item.progress"
                max="100"
              />
            </div>
          </li>
        </ul>
        <button
          v-if="upload.items.value.length && !upload.uploading.value"
          type="button"
          class="outline clear-uploads"
          @click="upload.clearDone()"
        >
          Liste aufräumen
        </button>

        <!-- Foto-Raster -->
        <div class="section-heading">
          <h3>Fotos ({{ photos.length }})</h3>
        </div>
        <p v-if="photos.length === 0" class="hint-text">Noch keine Fotos auf der Seite.</p>
        <div v-else class="photo-grid">
          <article v-for="photo in photos" :key="photo.photo_id" class="photo-card surface">
            <div class="photo-frame">
              <img
                v-if="photo.thumb_url"
                :src="photo.thumb_url"
                :alt="`Fundsache Nr. ${photo.number}`"
                loading="lazy"
                @error="handleImageError(photo)"
              />
              <span class="photo-number">{{ photo.number }}</span>
              <span v-if="photo.state !== 'READY'" class="status-badge status-draft photo-state">
                Upload offen
              </span>
            </div>
            <input
              type="text"
              maxlength="200"
              placeholder="Beschriftung (optional)"
              :value="captionDrafts[photo.photo_id] ?? ''"
              @input="onCaptionInput(photo, $event.target.value)"
              @blur="flushCaption(photo)"
              @keyup.enter="flushCaption(photo)"
            />
            <div class="photo-footer">
              <small v-if="captionState[photo.photo_id]" class="caption-state">
                {{ captionState[photo.photo_id] }}
              </small>
              <button
                type="button"
                class="outline secondary photo-delete"
                :disabled="deletingPhotoId === photo.photo_id"
                :aria-busy="deletingPhotoId === photo.photo_id"
                @click="deletePhoto(photo)"
              >
                Löschen
              </button>
            </div>
          </article>
        </div>
      </template>
    </template>

    <!-- Seite löschen -->
    <dialog :open="deleteDialogOpen">
      <article style="max-width: 500px">
        <header>
          <button aria-label="Schließen" rel="prev" @click="closeDeleteDialog"></button>
          <h3>Fundsachen-Seite löschen?</h3>
        </header>
        <p class="warning-box">
          Konfiguration, alle {{ photos.length }} Fotos und die Bilddateien werden endgültig
          entfernt. Der Link ist danach tot. Das lässt sich nicht rückgängig machen.
        </p>
        <p v-if="deleting" aria-busy="true">{{ deleteProgress }} Fotos entfernt ...</p>
        <div v-if="deleteError" role="alert" class="error">{{ deleteError }}</div>
        <footer>
          <button type="button" class="secondary" :disabled="deleting" @click="closeDeleteDialog">
            Abbrechen
          </button>
          <button
            type="button"
            class="btn-danger"
            :disabled="deleting"
            :aria-busy="deleting"
            @click="confirmDeletePage"
          >
            {{ deleting ? 'Wird gelöscht ...' : 'Endgültig löschen' }}
          </button>
        </footer>
      </article>
    </dialog>
  </article>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { adminApi } from '../../services/api'
import PageHeader from '../../components/PageHeader.vue'
import { formatDateOnly } from '../../utils/formatters.js'
import { showToast } from '../../composables/useToast.js'
import { MAX_CONCURRENT, useLostFoundUpload } from '../../composables/useLostFoundUpload.js'

// Captions are typed, not submitted: save shortly after the last keystroke, and
// immediately on blur or Enter.
const CAPTION_DEBOUNCE_MS = 900
// Presigned view URLs live 15 minutes. A dead <img> triggers one reload, not a
// storm of them.
const URL_REFRESH_COOLDOWN_MS = 30000
// And a photo whose object is genuinely gone errors again after every reload,
// so the reloads are counted as well as spaced. The count is forgiven once the
// grid has been quiet for a while — then it is expiry, not a loop.
const MAX_ERROR_REFRESHES = 3
const ERROR_BUDGET_RESET_MS = 10 * 60 * 1000

const props = defineProps({
  eventId: { type: String, required: true },
})

const upload = useLostFoundUpload(props.eventId)

const loading = ref(true)
const loadError = ref(null)
const eventName = ref('')

const configured = ref(false)
// The publish state as *saved*, which is what the public link answers to —
// `form.published` may already carry an unsaved change.
const publishedSaved = ref(false)
const publicUrl = ref('')
const expiresAt = ref(null)
const photos = ref([])

const form = reactive({
  coordinator_email: '',
  coordinator_telegram_url: '',
  coordinator_name: '',
  intro_text: '',
  retention_days: '',
  published: false,
})

const saving = ref(false)
const saveError = ref(null)
const rotating = ref(false)
const dragOver = ref(false)

const deleteDialogOpen = ref(false)
const deleting = ref(false)
const deleteError = ref(null)
const deleteProgress = ref(0)
const deletingPhotoId = ref(null)

const captionState = reactive({})
// What stands in the caption fields. Deliberately separate from `photo.caption`:
// a debounced save that returns mid-typing must not reset the field under the
// cursor.
const captionDrafts = reactive({})
const captionTimers = new Map()
let lastUrlRefresh = 0
let errorRefreshes = 0

const retentionPlaceholder = ref('90')
// Whether the organiser edited the retention field since the last load or save.
const retentionTouched = ref(false)

function syncCaptionDrafts(list) {
  for (const photo of list) {
    if (captionDrafts[photo.photo_id] === undefined) {
      captionDrafts[photo.photo_id] = photo.caption || ''
    }
  }
}

function applyPayload(payload) {
  configured.value = payload.configured
  publishedSaved.value = Boolean(payload.published)
  publicUrl.value = payload.public_url || ''
  expiresAt.value = payload.expires_at || null
  photos.value = payload.photos || []
  syncCaptionDrafts(photos.value)
  if (payload.retention_days) retentionPlaceholder.value = String(payload.retention_days)
}

function applyForm(payload) {
  form.coordinator_email = payload.coordinator_email || ''
  form.coordinator_telegram_url = payload.coordinator_telegram_url || ''
  form.coordinator_name = payload.coordinator_name || ''
  form.intro_text = payload.intro_text || ''
  form.published = Boolean(payload.published)
  // An unconfigured page reports the server default in `retention_days`; that
  // belongs in the placeholder, not in the field — an empty field is what keeps
  // the page following the setting.
  form.retention_days =
    payload.configured && payload.retention_days ? String(payload.retention_days) : ''
  // The response only carries the value *in force*, so a page that follows the
  // setting is indistinguishable from one with the same value as an override.
  // Sending it back on every save would silently turn the first into the
  // second, and a later change to LOST_AND_FOUND_RETENTION_DAYS would then miss
  // every page that was ever saved twice. So the field is only ever sent after
  // somebody actually typed in it.
  retentionTouched.value = false
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [payload, event] = await Promise.all([
      adminApi.lostFound.get(props.eventId),
      // Only for the header — a missing event name is not worth failing over.
      adminApi.getEvent(props.eventId).catch(() => null),
    ])
    eventName.value = event?.name || ''
    applyPayload(payload)
    applyForm(payload)
  } catch (err) {
    loadError.value = err.message || 'Fundsachen-Seite konnte nicht geladen werden'
  } finally {
    loading.value = false
  }
}

async function refreshPhotos() {
  try {
    const payload = await adminApi.lostFound.get(props.eventId)
    applyPayload(payload)
  } catch (err) {
    showToast(err.message || 'Fotos konnten nicht neu geladen werden', 'error')
  }
}

async function saveConfig() {
  // The backend enforces this too (400 `contact_required`), but a guest-facing
  // page whose only purpose is „write to this person" should not need a round
  // trip to say that nobody has been named.
  if (!form.coordinator_email && !form.coordinator_telegram_url) {
    saveError.value = 'Bitte gib eine E-Mail-Adresse oder einen Telegram-Link an.'
    return
  }

  saving.value = true
  saveError.value = null
  try {
    const body = {
      // Empty means „no such contact" — send null so the backend clears it,
      // which it refuses if it would leave the page with no contact at all.
      coordinator_email: form.coordinator_email || null,
      coordinator_telegram_url: form.coordinator_telegram_url || null,
      coordinator_name: form.coordinator_name || null,
      intro_text: form.intro_text || null,
      published: form.published,
    }
    // Omitted means „leave it as it is" (the backend patches on
    // `exclude_unset`); null means „follow the setting again".
    if (retentionTouched.value) {
      body.retention_days = form.retention_days === '' ? null : Number(form.retention_days)
    }
    const payload = await adminApi.lostFound.save(props.eventId, body)
    applyPayload(payload)
    applyForm(payload)
    showToast(form.published ? 'Gespeichert — Seite ist online' : 'Gespeichert', 'success')
  } catch (err) {
    saveError.value = err.message || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

function copyLink() {
  navigator.clipboard.writeText(publicUrl.value).then(
    () => showToast('Link kopiert!', 'success'),
    () => prompt('Kopiere diesen Link:', publicUrl.value),
  )
}

async function rotateToken() {
  const ok = window.confirm(
    'Neuen Link erzeugen? Jeder bereits verschickte Fundsachen-Link funktioniert danach ' +
      'nicht mehr — du musst den neuen Link erneut verteilen.',
  )
  if (!ok) return
  rotating.value = true
  try {
    const payload = await adminApi.lostFound.rotateToken(props.eventId)
    applyPayload(payload)
    showToast('Neuer Link erzeugt — der alte ist tot', 'success')
  } catch (err) {
    showToast(err.message || 'Link konnte nicht erneuert werden', 'error')
  } finally {
    rotating.value = false
  }
}

function closeDeleteDialog() {
  if (deleting.value) return
  deleteDialogOpen.value = false
  deleteError.value = null
  deleteProgress.value = 0
}

async function confirmDeletePage() {
  // The presigned POSTs of a running batch stay valid for 15 minutes. Deleting
  // the rows now would leave those objects in the bucket with nothing pointing
  // at them — neither the sweep nor a later delete builds its key list from
  // anything but the rows, so only the 400-day lifecycle rule would ever catch
  // them.
  if (upload.uploading.value) {
    deleteError.value = 'Warte, bis der Upload fertig ist — sonst bleiben Bilddateien liegen.'
    return
  }

  deleting.value = true
  deleteError.value = null
  deleteProgress.value = 0
  try {
    const result = await adminApi.lostFound.deletePage(props.eventId, {
      onProgress: ({ photos: done }) => {
        deleteProgress.value = done
      },
    })
    deleteDialogOpen.value = false
    upload.reset()
    showToast(`Seite gelöscht — ${result.deleted_photos} Fotos entfernt`, 'success')
    await load()
  } catch (err) {
    deleteError.value = err.message || 'Löschen fehlgeschlagen'
  } finally {
    deleting.value = false
  }
}

function handlePick(event) {
  const files = event.target.files
  startUpload(files)
  // Let the same selection be picked again after a failed batch.
  event.target.value = ''
}

function handleDrop(event) {
  dragOver.value = false
  startUpload(event.dataTransfer?.files)
}

async function startUpload(files) {
  // The file input is disabled while a batch runs, the drop zone cannot be.
  // A second batch would start its own pool of four workers — eight parallel
  // POSTs on a saturated festival AP is what the cap exists to avoid — and
  // would flip `uploading` back to false while it is still running.
  if (upload.uploading.value) {
    showToast('Der laufende Upload ist noch nicht fertig', 'error')
    return
  }
  const confirmed = await upload.uploadFiles(files)
  if (confirmed.length > 0) {
    // The backend answers with the finished rows including fresh view URLs, so
    // the grid grows without a second round-trip. Merged by id rather than
    // appended: a refresh during the upload window (a dead thumbnail, a save)
    // already put the freshly minted rows in the list, and appending them a
    // second time gives two tiles and two caption fields for one photo.
    const byId = new Map(photos.value.map((photo) => [photo.photo_id, photo]))
    for (const photo of confirmed) byId.set(photo.photo_id, photo)
    photos.value = [...byId.values()].sort((a, b) => a.number - b.number)
    syncCaptionDrafts(confirmed)
    showToast(
      confirmed.length === 1 ? '1 Foto hochgeladen' : `${confirmed.length} Fotos hochgeladen`,
      'success',
    )
  }
}

const UPLOAD_STATE_LABELS = {
  queued: 'wartet',
  scaling: 'wird verkleinert ...',
  ready: 'bereit',
  uploading: 'lädt hoch ...',
  uploaded: 'wird bestätigt ...',
  done: 'fertig',
}

function uploadStateLabel(item) {
  const label = UPLOAD_STATE_LABELS[item.status] || item.status
  return item.number ? `Nr. ${item.number} — ${label}` : label
}

function onCaptionInput(photo, value) {
  const existing = captionTimers.get(photo.photo_id)
  if (existing) clearTimeout(existing)
  captionTimers.set(
    photo.photo_id,
    setTimeout(() => saveCaption(photo, value), CAPTION_DEBOUNCE_MS),
  )
  // Kept locally so a debounced save that lands later still sends the last
  // keystroke, and so blur has something to flush.
  captionDrafts[photo.photo_id] = value
}

function flushCaption(photo) {
  const existing = captionTimers.get(photo.photo_id)
  if (!existing) return
  clearTimeout(existing)
  captionTimers.delete(photo.photo_id)
  saveCaption(photo, captionDrafts[photo.photo_id] ?? '')
}

async function saveCaption(photo, value) {
  captionTimers.delete(photo.photo_id)
  const next = value.trim() === '' ? null : value.trim()
  if (next === (photo.caption ?? null)) {
    captionState[photo.photo_id] = ''
    return
  }
  captionState[photo.photo_id] = 'wird gespeichert ...'
  try {
    const updated = await adminApi.lostFound.updatePhoto(props.eventId, photo.photo_id, next)
    photo.caption = updated.caption
    captionState[photo.photo_id] = 'gespeichert'
  } catch (err) {
    captionState[photo.photo_id] = err.message || 'nicht gespeichert'
  }
}

async function deletePhoto(photo) {
  const ok = window.confirm(
    `Foto Nr. ${photo.number} löschen? Die Nummer bleibt danach leer und wird nicht neu vergeben.`,
  )
  if (!ok) return
  deletingPhotoId.value = photo.photo_id
  try {
    await adminApi.lostFound.deletePhoto(props.eventId, photo.photo_id)
    photos.value = photos.value.filter((p) => p.photo_id !== photo.photo_id)
    delete captionDrafts[photo.photo_id]
    showToast(`Foto Nr. ${photo.number} gelöscht`, 'success')
  } catch (err) {
    showToast(err.message || 'Foto konnte nicht gelöscht werden', 'error')
  } finally {
    deletingPhotoId.value = null
  }
}

// View URLs expire after 15 minutes, so a page left open shows broken images.
// One reload per cooldown window fetches a fresh set for the whole grid.
function handleImageError(photo) {
  // A PENDING row has no object behind its URL yet — that error is expected and
  // no amount of reloading fixes it.
  if (photo.state !== 'READY') return
  const now = Date.now()
  if (now - lastUrlRefresh < URL_REFRESH_COOLDOWN_MS) return
  if (lastUrlRefresh && now - lastUrlRefresh > ERROR_BUDGET_RESET_MS) errorRefreshes = 0
  if (errorRefreshes >= MAX_ERROR_REFRESHES) return
  lastUrlRefresh = now
  errorRefreshes += 1
  refreshPhotos()
}

// A file dropped anywhere but on the drop zone would otherwise navigate the tab
// to the JPEG, taking every unsaved word of the form with it.
function swallowDrag(event) {
  event.preventDefault()
}

onMounted(() => {
  window.addEventListener('dragover', swallowDrag)
  window.addEventListener('drop', swallowDrag)
  load()
})

onBeforeUnmount(() => {
  window.removeEventListener('dragover', swallowDrag)
  window.removeEventListener('drop', swallowDrag)
  for (const timer of captionTimers.values()) clearTimeout(timer)
  captionTimers.clear()
  upload.reset()
})
</script>

<style scoped>
.error {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: 1rem;
}

.hint-box {
  background: var(--color-info-subtle-bg);
  color: var(--color-info-subtle-text);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
}

.hint-text {
  font-size: 0.875rem;
  color: var(--color-text-muted);
  margin-bottom: 0;
}

.publish-toggle {
  margin-bottom: 0.25rem;
}

.publish-hint {
  font-size: 0.875rem;
  color: var(--color-text-muted);
}

.public-url {
  display: block;
  word-break: break-all;
  margin-bottom: var(--space-3);
}

.link-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: var(--space-3);
}

.link-actions button,
.link-actions a[role='button'] {
  width: auto;
  margin: 0;
  min-height: 44px;
}

.drop-zone {
  padding: var(--space-5) var(--space-4);
  text-align: center;
  border-style: dashed;
  border-width: 2px;
}

.drop-zone--over {
  border-color: var(--color-brand);
  background: var(--color-brand-subtle);
}

.drop-zone input[type='file'] {
  margin: 0 auto var(--space-3);
  max-width: 24rem;
}

.upload-list {
  list-style: none;
  padding: 0;
  margin: var(--space-4) 0 0;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
}

.upload-preview {
  width: 44px;
  height: 44px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.upload-body {
  flex: 1;
  min-width: 0;
}

.upload-name {
  display: block;
  font-size: var(--text-base);
  overflow-wrap: anywhere;
}

.upload-state {
  color: var(--color-text-muted);
}

.upload-error {
  color: var(--color-danger-text);
}

.upload-body progress {
  margin: 0.25rem 0 0;
  height: 0.4rem;
}

.clear-uploads {
  width: auto;
  margin-top: var(--space-3);
  min-height: 44px;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-3);
}

.photo-card {
  padding: var(--space-2);
  margin: 0;
}

.photo-frame {
  position: relative;
  aspect-ratio: 4 / 3;
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.photo-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.photo-number {
  position: absolute;
  top: var(--space-1);
  left: var(--space-1);
  min-width: 1.75rem;
  padding: 0.1rem 0.4rem;
  text-align: center;
  font-weight: 700;
  font-size: var(--text-lg);
  color: #fff;
  background: rgba(12, 30, 60, 0.78);
  border-radius: var(--radius-sm);
}

.photo-state {
  position: absolute;
  bottom: var(--space-1);
  left: var(--space-1);
}

.photo-card input[type='text'] {
  margin-bottom: var(--space-2);
  font-size: var(--text-base);
}

.photo-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.caption-state {
  color: var(--color-text-muted);
}

.photo-delete {
  width: auto;
  margin: 0;
  min-height: 36px;
  padding: 0.25rem 0.6rem;
  font-size: var(--text-sm);
}

.warning-box {
  background: var(--color-warning-bg);
  padding: 0.75rem;
  border-radius: var(--pico-border-radius);
  color: var(--color-warning-text);
  font-size: 0.9em;
}
</style>

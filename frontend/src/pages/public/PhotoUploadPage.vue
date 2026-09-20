<template>
  <article class="photo-upload">
    <!-- Loading state -->
    <div v-if="loading" aria-busy="true" class="loading-state">
      Einen Moment — die Seite wird geladen ...
    </div>

    <!-- Gone state: the backend answers one bare 404 to every rejection that
         falls before or on the token comparison (falscher Token, Nicht-ASCII,
         unbekanntes Event, keine Sammlung), so this page cannot be used to
         probe which events exist. We say just as little — and there is nothing
         to retry, so we offer nothing. -->
    <div v-else-if="gone" role="alert" class="gone-state">
      <h2>Diese Seite gibt es nicht (mehr).</h2>
      <p>Prüf am besten den Link — oder frag die Leute, von denen du ihn bekommen hast.</p>
    </div>

    <div v-else-if="loadError" role="alert" class="error-state">
      <h2>Das hat gerade nicht geklappt</h2>
      <p>Die Seite konnte nicht geladen werden. Versuch es in einem Moment nochmal.</p>
      <button type="button" class="outline" @click="load()">Nochmal versuchen</button>
    </div>

    <template v-else-if="page">
      <header class="page-header">
        <p class="eyebrow">Eventfotos</p>
        <h2>Fotos vom {{ page.event_name }}</h2>
        <p v-if="eventDate" class="event-line">{{ eventDate }}</p>
        <!-- „Ob offen ist UND bis wann" (spec 024 §Die Einbahnstraße). Without
             this line a guest who opens the link on Friday has no way to know
             the window shuts on Sunday, comes back on Monday and meets the
             closed page instead — on a printed slip that is exactly the dead
             end the closed copy was written to avoid. The backend pins the
             offset on `closes_at` for this one line, so the hour shown here is
             the hour the backend will enforce. -->
        <p v-if="page.upload_open && closesAt" class="event-line closes-line">
          Du kannst noch bis {{ closesAt }} Fotos abgeben.
        </p>
      </header>

      <!-- Closed: the switch, `closes_at` or the retention window — the payload
           reports the computed state, so this branch does not have to know
           which of the three it was. -->
      <section v-if="!page.upload_open" class="surface surface-padded closed-state">
        <h3>Der Upload für das {{ page.event_name }} ist zu.</h3>
        <p>
          Wenn du noch Fotos hast, schreib an
          <template v-for="(contact, i) in contacts" :key="contact.href"
            ><span v-if="i > 0"> oder </span
            ><a :href="contact.href" target="_blank" rel="noopener noreferrer">{{
              contact.label
            }}</a></template
          >.
        </p>
      </section>

      <template v-else>
        <section class="intro">
          <!-- ONLY paragraph (1) is overridable (spec 024 §Der Text auf der
               Upload-Seite). `intro_text` belongs to the organisers; everything
               below it does not. The promise that nobody browses these photos is
               the reason somebody uploads at all, the three facts are what a
               distrustful reader is looking for, and the consent line is what
               makes the page lawful — none of it may be configured away, so all
               of it is always rendered from the template. The one-way rule is
               restated above the upload button too, where no custom text can
               displace it. -->
          <p v-if="page.intro_text" class="intro-lead intro-custom">{{ page.intro_text }}</p>
          <p v-else class="intro-lead">
            Du hast Fotos vom {{ page.event_name }}? Her damit. Wir sammeln sie ein, damit nicht
            alles auf vierzig Handys liegen bleibt.
          </p>

          <p>
            Aus allem, was zusammenkommt, wollen wir eine richtige Fotostrecke bauen — eine, die
            man sich in zwei Jahren nochmal anschaut. Dafür brauchen wir euer Bildmaterial, und
            zwar möglichst viel davon.
          </p>

          <p>
            <strong>Warum du hier nichts zu sehen bekommst:</strong> Auf Eventfotos sind Leute
            drauf, die nie gefragt wurden, ob sie irgendwo auftauchen. Das Recht am eigenen Bild
            und der Datenschutz sind für uns keine Formalie — deshalb sieht die gemeinsame
            Sammlung vorerst nur das Orga-Team. Wir sortieren, machen Gesichter unkenntlich, wo es
            nötig ist, und stellen daraus später eine kuratierte Auswahl bereit. Diese Seite ist
            wirklich nur ein Zwischenschritt: hier entsteht die Sammlung, mehr passiert hier
            nicht. Auch deine eigenen Fotos sind hier weg, sobald sie hochgeladen sind.
          </p>

          <!-- A list, not a paragraph: these are the three things a distrustful
               reader looks for — where does it live, who gets at it, when is it
               gone. As bullets with icons they are read in two seconds; the same
               content as prose looks like fine print and gets skipped. -->
          <ul class="privacy-facts">
            <li>
              <Lock :size="17" aria-hidden="true" />
              <span><strong>Verschlüsselt gespeichert</strong>, nicht öffentlich abrufbar.</span>
            </li>
            <li>
              <EyeOff :size="17" aria-hidden="true" />
              <span><strong>Sichtbar nur für das Orga-Team.</strong></span>
            </li>
            <li>
              <Trash2 :size="17" aria-hidden="true" />
              <span>
                <strong
                  >Spätestens nach {{ page.retention_days }} Tagen automatisch gelöscht.</strong
                >
              </span>
            </li>
          </ul>

          <p>
            Lade bitte nur Fotos hoch, mit denen die Abgebildeten einverstanden sind. Wenn ein
            Foto von dir raus soll oder du eines aus Versehen hochgeladen hast:
            <template v-for="(contact, i) in contacts" :key="contact.href"
              ><span v-if="i > 0"> oder </span
              ><a :href="contact.href" target="_blank" rel="noopener noreferrer">{{
                contact.label
              }}</a></template
            > — dann nehmen wir es raus.
          </p>

          <!-- The single aggregate the public payload carries. „ca." because it
               counts reservations that may never be confirmed. -->
          <p v-if="page.photo_count > 0" class="count-line">
            Bisher sind ca. {{ page.photo_count }} Fotos zusammengekommen.
          </p>
        </section>

        <!-- Success: replaces the picker, not the text above it, so the
             retention and contact lines stay on screen in every state. -->
        <section v-if="celebrating" class="surface surface-padded success-panel">
          <p class="success-headline">
            <CheckCircle2 :size="22" aria-hidden="true" />
            {{ sessionTotal === 1 ? '1 Foto angekommen' : `${sessionTotal} Fotos angekommen` }}.
            Danke!
          </p>
          <p>
            Sie liegen jetzt beim Orga-Team und tauchen hier nicht mehr auf — auch nicht für
            dich. Daraus wird die kuratierte Strecke.
          </p>
          <p v-if="notice" class="notice-line">{{ notice }}</p>
          <button type="button" class="outline" @click="celebrating = false">
            Weitere Fotos schicken
          </button>
        </section>

        <form v-else class="upload-form" @submit.prevent="startUpload">
          <!-- Partly successful batch: the thanks panel below would hide the
               retry button, so what already arrived is acknowledged here
               instead of nowhere. -->
          <p v-if="sessionTotal > 0" class="success-inline" aria-live="polite">
            <CheckCircle2 :size="18" aria-hidden="true" />
            {{ sessionTotal === 1 ? '1 Foto ist' : `${sessionTotal} Fotos sind` }} schon angekommen
            — danke!
          </p>

          <!-- accept="image/*" and no `capture`: a guest picks from their
               gallery, they do not take a new photo of the event three weeks
               later. `capture` would open the camera instead on Android. -->
          <div
            class="surface drop-zone"
            :class="{ 'drop-zone--over': dragOver }"
            @dragover.prevent="dragOver = true"
            @dragenter.prevent="dragOver = true"
            @dragleave.prevent="dragOver = false"
            @drop.prevent="handleDrop"
          >
            <p class="drop-lead">
              <Images :size="20" aria-hidden="true" />
              <strong>Fotos auswählen</strong> — oder hierher ziehen.
            </p>
            <input
              id="photoFiles"
              type="file"
              accept="image/*"
              multiple
              :disabled="uploading"
              @change="handlePick"
            />
            <p class="hint-text">
              Die Fotos werden auf deinem Gerät verkleinert, bevor sie hochgehen — das spart
              Datenvolumen und entfernt alle EXIF-Daten samt GPS-Koordinaten. Es laufen höchstens
              {{ MAX_CONCURRENT }} Uploads gleichzeitig. Mehr als
              {{ page.max_files_per_batch }} Fotos gehen auch: die schicken wir dann in mehreren
              Stapeln hintereinander los.
            </p>
          </div>

          <template v-if="rows.length">
            <p class="selection-line" aria-live="polite">
              {{ rows.length === 1 ? '1 Foto ausgewählt' : `${rows.length} Fotos ausgewählt` }}
              <template v-if="batchCount > 1">
                — werden in {{ batchCount }} Stapeln hochgeladen.
              </template>
            </p>

            <ul class="preview-grid">
              <li v-for="row in rows" :key="row.key" class="preview-card">
                <div
                  class="preview-frame"
                  :class="{ 'preview-frame--failed': row.status === 'error' }"
                >
                  <img :src="row.preview" :alt="row.name" loading="lazy" decoding="async" />
                  <!-- Removable only before the upload: once a photo is up it
                       is out of this page's reach by design, so there is no
                       delete button that could pretend otherwise. -->
                  <button
                    v-if="!uploading"
                    type="button"
                    class="preview-remove"
                    :aria-label="`${row.name} abwählen`"
                    @click="removeRow(row)"
                  >
                    <X :size="18" aria-hidden="true" />
                  </button>
                  <progress
                    v-if="row.status !== 'queued' && row.status !== 'error'"
                    class="preview-progress"
                    :value="row.progress"
                    max="100"
                  />
                </div>
                <!-- The name, not just the tile: „bitte als JPEG teilen" is only
                     actionable if the guest can tell which file it is about. -->
                <small class="preview-name" :title="row.name">{{ row.name }}</small>
                <small v-if="row.status === 'error'" class="preview-error">{{ row.error }}</small>
                <small v-else class="preview-state">{{ STATE_LABELS[row.status] }}</small>
              </li>
            </ul>

            <button
              v-if="failedCount && !uploading"
              type="button"
              class="outline retry-button"
              @click="retryFailed"
            >
              {{
                failedCount === 1 ? 'Fehlgeschlagenes Foto' : `${failedCount} fehlgeschlagene Fotos`
              }}
              nochmal versuchen
            </button>
          </template>

          <label for="uploaderName">
            Von wem sind die Fotos? (optional)
            <input
              id="uploaderName"
              v-model.trim="uploaderName"
              type="text"
              maxlength="80"
              placeholder="Vorname reicht"
              :disabled="uploading"
            />
            <small>Sieht nur die Orga — damit sie weiß, bei wem sie sich bedanken muss.</small>
          </label>

          <label for="uploadNote">
            Notiz an die Orga (optional)
            <textarea
              id="uploadNote"
              v-model.trim="note"
              rows="2"
              maxlength="300"
              placeholder="z. B. „die vom Lagerfeuer sind von Sonntagnacht“"
              :disabled="uploading"
            ></textarea>
            <small>Gilt für den ganzen Stapel.</small>
          </label>

          <label for="photoConsent" class="consent">
            <input id="photoConsent" v-model="consent" type="checkbox" :disabled="uploading" />
            Ich habe das gelesen und lade nur Fotos hoch, mit denen die Abgebildeten einverstanden
            sind.
          </label>

          <p class="oneway-note">
            Nach dem Hochladen sind die Fotos aus dieser Vorschau weg und du kommst nicht mehr an
            sie heran. Das ist Absicht — wähl also vorher aus, was du abgeben willst.
          </p>

          <div v-if="notice" role="alert" class="notice-box">{{ notice }}</div>

          <button type="submit" :disabled="!canUpload" :aria-busy="uploading">
            <Upload v-if="!uploading" :size="18" aria-hidden="true" />
            {{ submitLabel }}
          </button>
        </form>

        <footer class="page-footer">
          <p>
            Fragen, oder ein Foto soll raus?
            <template v-for="(contact, i) in contacts" :key="contact.href"
              ><span v-if="i > 0"> oder </span
              ><a :href="contact.href" target="_blank" rel="noopener noreferrer">{{
                contact.label
              }}</a></template
            >
          </p>
        </footer>
      </template>
    </template>
  </article>
</template>

<script setup>
/**
 * Public photo upload page (spec 024) — the write-only counterpart of the
 * Fundsachen page.
 *
 * Everything a guest can see here comes out of their own phone: the payload
 * carries no photo id, no S3 key and no image URL, and the preview tiles are
 * `URL.createObjectURL(file)`. That is why a page with no read path still feels
 * like a page and not a broken form.
 *
 * Every byte goes browser → S3 directly. One batch of 30 photos costs exactly
 * two Lambda calls (`uploads` to mint the presigned POSTs, `confirm` to flip
 * the rows), so neither the 10 MB request limit nor the 29 s timeout of API
 * Gateway is anywhere near the picture.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, EyeOff, Images, Lock, Trash2, Upload, X } from 'lucide-vue-next'
import { postPresignedForm, publicApi } from '../../services/api'
import { formatDateOnly, formatDateTime } from '../../utils/formatters'

const props = defineProps({
  eventId: { type: String, default: '' },
  token: { type: String, default: '' },
})

/* -------------------------------------------------------------------------
 * Scaling and upload constants (spec 024, § Skalieren im Browser)
 * ---------------------------------------------------------------------- */

// The `thumb` variant exists so the admin grid does not pull 30 full-size
// JPEGs; 400 px at 0.7 lands around 30 kB.
const THUMB_EDGE = 400
const THUMB_QUALITY = 0.7

// `full` is deliberately not the camera original: 12-MP phone photos over
// festival wifi are the fastest way to a batch nobody finishes, and 2560 px
// covers screen, beamer and anything short of large-format print.
//
// A ladder rather than one setting, because the presigned POST policy is a
// hard wall at `max_bytes` and S3 answers a policy violation — not something a
// guest could read as „too big". A wide panorama at 2560 px/0.85 can pass
// 6 MB, so the encoder walks down until the blob fits.
const FULL_LADDER = [
  { edge: 2560, quality: 0.85 },
  { edge: 2560, quality: 0.7 },
  { edge: 1800, quality: 0.7 },
]

// More parallel uploads send rows of requests into timeouts on a saturated
// festival AP — the same four as spec 023, for the same reason. Named in the
// copy, so the number the page promises and the number it runs are one.
const MAX_CONCURRENT = 4

// Fallbacks for the limits the payload normally carries; only relevant if an
// older backend answers without them.
const DEFAULT_BATCH = 30
const DEFAULT_MAX_BYTES = 6 * 1024 * 1024

// The public payload carries only the `full` ceiling — the thumb policy is the
// backend's business and a 400 px JPEG lands two orders of magnitude below it.
// The number is here so the encoder has something to check against at all.
const THUMB_BYTE_CEILING = 400 * 1024

const DECODE_MESSAGE = 'Dieses Format kann dein Browser nicht lesen — bitte als JPEG teilen'

const STATE_LABELS = {
  queued: 'wartet',
  scaling: 'wird verkleinert ...',
  ready: 'bereit',
  uploading: 'lädt hoch ...',
  uploaded: 'wird bestätigt ...',
  done: 'angekommen',
}

/* -------------------------------------------------------------------------
 * Page state
 * ---------------------------------------------------------------------- */

const loading = ref(true)
const gone = ref(false)
const loadError = ref(false)
const page = ref(null)

// One row per picked file, in pick order — this is what the grid renders.
const rows = ref([])
const uploading = ref(false)
const dragOver = ref(false)
const consent = ref(false)
const uploaderName = ref('')
const note = ref('')
// Batch-level problem or aside: a closed window, the hourly quota, a partial
// confirm. Per-file trouble lives on the row instead.
const notice = ref('')
const sessionTotal = ref(0)
const celebrating = ref(false)

const eventDate = computed(() => formatDateOnly(page.value?.event_date, ''))

// Europe/Berlin, like every other timestamp we show — the backend hands
// `closes_at` over with an offset precisely so this renders the same instant
// the window check uses, whatever zone the guest's phone is set to.
const closesAt = computed(() => formatDateTime(page.value?.closes_at, ''))
const batchSize = computed(() => Number(page.value?.max_files_per_batch) || DEFAULT_BATCH)
const maxFullBytes = computed(() => Number(page.value?.max_bytes) || DEFAULT_MAX_BYTES)
const pendingRows = computed(() => rows.value.filter((row) => row.status !== 'error'))
const failedCount = computed(() => rows.value.filter((row) => row.status === 'error').length)
const batchCount = computed(() => Math.ceil(pendingRows.value.length / batchSize.value) || 0)
const canUpload = computed(() => consent.value && !uploading.value && pendingRows.value.length > 0)

const doneCount = computed(
  () => rows.value.filter((row) => row.status === 'done' || row.status === 'uploaded').length,
)

const submitLabel = computed(() => {
  if (uploading.value) return `Lädt hoch — ${doneCount.value} von ${pendingRows.value.length} ...`
  const count = pendingRows.value.length
  if (!count) return 'Fotos hochladen'
  return count === 1 ? '1 Foto hochladen' : `${count} Fotos hochladen`
})

/**
 * The ways a guest can reach a human, in the order they are offered. Either
 * form may be missing, never both — the backend refuses to save a collection
 * with no contact at all, and without a saved collection there is no valid
 * token — so this list always has at least one entry.
 */
const contacts = computed(() => {
  const p = page.value
  if (!p) return []

  const list = []
  if (p.contact_email) {
    list.push({ href: mailtoUrl(), label: p.contact_name || p.contact_email })
  }
  if (p.contact_telegram_url) {
    list.push({
      href: p.contact_telegram_url,
      // Next to a mail address the word „Telegram" is the useful half; on its
      // own the label has to name *who* is being written to.
      label: list.length ? 'Telegram' : telegramLabel(p),
    })
  }
  return list
})

function telegramLabel(p) {
  if (p.contact_name) return `${p.contact_name} auf Telegram`
  // A public handle can be shown as @name; an invite link is a group hash that
  // means nothing to a reader, so that gets a generic label.
  const handle = /^https:\/\/(?:t\.me|telegram\.me)\/([A-Za-z0-9_]+)$/.exec(
    p.contact_telegram_url || '',
  )
  return handle ? `@${handle[1]} auf Telegram` : 'die Telegram-Gruppe'
}

function mailtoUrl() {
  const subject = `Fotos vom ${page.value?.event_name || 'Event'}`
  return `mailto:${page.value?.contact_email}?subject=${encodeURIComponent(subject)}`
}

/* -------------------------------------------------------------------------
 * Loading
 *
 * No refresh timer, unlike the Fundsachen page: this payload contains no
 * presigned URL that could expire, because it contains no image at all. The
 * one-way street pays for itself here.
 * ---------------------------------------------------------------------- */

async function load() {
  loading.value = true
  loadError.value = false
  gone.value = false
  try {
    page.value = await publicApi.getPhotoUploadPage(props.eventId, props.token)
  } catch (err) {
    // 404 is the backend's single answer to every rejection at the gate, so it
    // is the one status this page branches on — and it is a dead end, not a
    // retry: nothing about the link is going to get better.
    if (err.status === 404) {
      gone.value = true
      page.value = null
    } else {
      loadError.value = true
    }
  } finally {
    loading.value = false
  }
}

/* -------------------------------------------------------------------------
 * Selection
 * ---------------------------------------------------------------------- */

function handlePick(event) {
  addFiles(event.target.files)
  // Let the same selection be picked again after a failed batch.
  event.target.value = ''
}

function handleDrop(event) {
  dragOver.value = false
  addFiles(event.dataTransfer?.files)
}

function addFiles(fileList) {
  const files = Array.from(fileList || [])
  if (!files.length) return
  notice.value = ''
  celebrating.value = false

  const fresh = files.map((file) => {
    // A declared non-image type is worth saying immediately — decoding it to
    // find out costs a full bitmap and tells the guest nothing new.
    const wrongType = Boolean(file.type) && !file.type.startsWith('image/')
    return {
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
      name: file.name,
      file,
      // The preview is the picked file itself, straight out of the phone's
      // storage. No server is asked, so a page that never shows a photo back
      // still shows the guest what they are about to hand over.
      preview: URL.createObjectURL(file),
      status: wrongType ? 'error' : 'queued',
      error: wrongType ? 'Das ist keine Bilddatei' : null,
      progress: 0,
    }
  })
  rows.value = [...rows.value, ...fresh]
}

function removeRow(row) {
  URL.revokeObjectURL(row.preview)
  rows.value = rows.value.filter((candidate) => candidate.key !== row.key)
}

/** Put the failed rows back in the queue — the files are still in hand. */
function retryFailed() {
  notice.value = ''
  for (const row of rows.value) {
    if (row.status !== 'error') continue
    row.status = 'queued'
    row.error = null
    row.progress = 0
  }
}

/** Drop the finished rows and free their previews — 40 phone photos are tens
 *  of MB of object URLs, and on a phone that is not a rounding error. */
function dropDoneRows() {
  const kept = []
  for (const row of rows.value) {
    if (row.status === 'done') URL.revokeObjectURL(row.preview)
    else kept.push(row)
  }
  rows.value = kept
}

function revokeAllPreviews() {
  for (const row of rows.value) URL.revokeObjectURL(row.preview)
}

/* -------------------------------------------------------------------------
 * Scaling
 * ---------------------------------------------------------------------- */

/**
 * Draw a decoded bitmap into a canvas at the target edge length and encode it
 * as JPEG. Images already smaller than the target are never upscaled — that
 * would only cost bytes.
 * @param {ImageBitmap} bitmap - Decoded source image
 * @param {number} maxEdge - Target length of the longest edge in px
 * @param {number} quality - JPEG quality 0..1
 * @returns {Promise<{blob: Blob, width: number, height: number}>}
 */
function drawVariant(bitmap, maxEdge, quality) {
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height))
  const width = Math.max(1, Math.round(bitmap.width * scale))
  const height = Math.max(1, Math.round(bitmap.height * scale))

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  // JPEG has no alpha: a transparent PNG would otherwise land on black.
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  ctx.drawImage(bitmap, 0, 0, width, height)

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        // Freed explicitly rather than left to the GC: 30 photos means dozens
        // of these at ~26 MB of backing store each, and iOS Safari caps the
        // total canvas memory of a page. Past that ceiling `toBlob` starts
        // handing back null, so the tail of a big batch would fail while the
        // head went up.
        canvas.width = 0
        canvas.height = 0
        if (blob) resolve({ blob, width, height })
        else reject(new Error('encode_failed'))
      },
      'image/jpeg',
      quality,
    )
  })
}

/**
 * Encode along a ladder of (edge, quality) steps and return the first result
 * that fits under `limit`. The last step is returned even when it does not fit
 * — the caller decides what to say about that.
 * @param {ImageBitmap} bitmap - Decoded source image
 * @param {Array<{edge: number, quality: number}>} ladder - Steps to try in order
 * @param {number} limit - Byte ceiling from the presigned POST policy
 * @returns {Promise<{blob: Blob, width: number, height: number}>}
 */
async function encodeWithin(bitmap, ladder, limit) {
  let attempt = null
  for (const step of ladder) {
    attempt = await drawVariant(bitmap, step.edge, step.quality)
    if (attempt.blob.size <= limit) break
  }
  return attempt
}

/**
 * Decode one file and encode both variants. Returns null and marks the row on
 * failure — a file the browser cannot read is this row's problem and nobody
 * else's.
 * @param {object} row - Reactive row from `rows`
 * @returns {Promise<object|null>} `{full, thumb}` or null
 */
async function prepare(row) {
  row.status = 'scaling'
  row.progress = 8

  let bitmap
  try {
    // `imageOrientation: 'from-image'` bakes the EXIF rotation into the pixels;
    // the re-encode then drops the rest of the EXIF block, GPS included. For
    // photos out of a tent camp that is the point, not a side effect — the
    // price is the capture time, which comes back as `captured_at_hint`.
    bitmap = await createImageBitmap(row.file, { imageOrientation: 'from-image' })
  } catch {
    // In practice: HEIC on Chrome and Firefox. Safari and iOS decode it via the
    // system, so the same file works from a phone.
    row.status = 'error'
    row.error = DECODE_MESSAGE
    row.progress = 0
    return null
  }

  try {
    const full = await encodeWithin(bitmap, FULL_LADDER, maxFullBytes.value)
    if (full.blob.size > maxFullBytes.value) {
      row.status = 'error'
      row.error = 'Dieses Foto wird auch verkleinert nicht klein genug — bitte direkt an die Orga'
      row.progress = 0
      return null
    }
    const thumb = await encodeWithin(
      bitmap,
      [{ edge: THUMB_EDGE, quality: THUMB_QUALITY }],
      THUMB_BYTE_CEILING,
    )
    row.status = 'ready'
    row.progress = 22
    return { full, thumb }
  } catch {
    row.status = 'error'
    row.error = 'Das Foto konnte nicht umgerechnet werden'
    row.progress = 0
    return null
  } finally {
    bitmap.close()
  }
}

/* -------------------------------------------------------------------------
 * Uploading
 * ---------------------------------------------------------------------- */

/**
 * Run tasks with a fixed number of workers. Tasks must swallow their own
 * errors — one broken photo may not stop the rest of the batch.
 * @param {Array<() => Promise<void>>} tasks - Task factories
 * @param {number} limit - Maximum workers
 */
async function runPool(tasks, limit) {
  let cursor = 0
  const workers = Array.from({ length: Math.min(limit, tasks.length) }, async () => {
    while (cursor < tasks.length) {
      await tasks[cursor++]()
    }
  })
  await Promise.all(workers)
}

/**
 * The only capture time left after the canvas detour. On a phone
 * `lastModified` is when the photo was taken; on a forwarded file it is when
 * it was saved. The backend treats it as a hint and falls back to the upload
 * time whenever it is implausible, which is why sending the weaker value is
 * still worth more than sending nothing.
 * @param {File} file - Picked file
 * @returns {string|null} ISO timestamp or null
 */
function capturedHint(file) {
  const ms = Number(file.lastModified)
  if (!ms || !Number.isFinite(ms)) return null
  return new Date(ms).toISOString()
}

/**
 * Turn a failed `uploads` call into one German sentence. Every one of these
 * lands *after* the token matched, so being specific reveals nothing.
 * @param {Error & {status?: number}} err - Error from the API helper
 * @returns {string} Message for the row and the notice line
 */
function mintMessage(err) {
  if (err.status === 429) {
    return 'Gerade laden zu viele Leute hoch — bitte in ein paar Minuten nochmal.'
  }
  // Two different 409s (geschlossen, Sammlung voll) and the backend already
  // says which in German, so its wording wins over a guess here.
  if (err.status === 409) return err.message || 'Der Upload für dieses Event ist geschlossen.'
  if (err.status === 404) return 'Diese Seite gibt es nicht (mehr).'
  return err.message || 'Die Upload-Erlaubnis konnte gerade nicht geholt werden.'
}

/**
 * Scale, upload and confirm one batch of at most `max_files_per_batch` files.
 * Never throws: every failure lands on a row, and `stop` is set only for the
 * kind of refusal that would hit the next batch just as hard.
 * @param {Array<object>} batchRows - Reactive rows to process
 * @returns {Promise<{confirmed: number, missed?: number, stop?: string}>}
 */
async function processBatch(batchRows) {
  // Scaling is CPU-bound and holds a full-size bitmap per file, so it runs one
  // at a time — 30 phone photos decoded in parallel is how a tab dies.
  const prepared = []
  for (const row of batchRows) {
    const variants = await prepare(row)
    if (variants) prepared.push({ row, variants })
  }
  if (!prepared.length) return { confirmed: 0 }

  let uploads
  try {
    const result = await publicApi.createPhotoUploads(props.eventId, props.token, {
      count: prepared.length,
      uploader_name: uploaderName.value || null,
      note: note.value || null,
    })
    uploads = result.uploads || []
  } catch (err) {
    const message = mintMessage(err)
    for (const { row } of prepared) {
      row.status = 'error'
      row.error = message
      row.progress = 0
    }
    if (err.status === 404) {
      gone.value = true
      page.value = null
    }
    return { confirmed: 0, stop: message }
  }

  const succeeded = []
  const tasks = prepared.map(({ row, variants }, index) => async () => {
    const slot = uploads[index]
    row.status = 'uploading'
    row.progress = 30
    try {
      await postPresignedForm(slot.full, variants.full.blob)
      row.progress = 75
      await postPresignedForm(slot.thumb, variants.thumb.blob)
      row.progress = 95
      row.status = 'uploaded'
      // Only a photo whose *both* variants are up may be confirmed: a tile
      // with a missing thumbnail is worse for the organiser than one photo
      // fewer, and the unconfirmed pair is swept after 24 h.
      succeeded.push({
        photo_id: slot.photo_id,
        width: variants.full.width,
        height: variants.full.height,
        bytes: variants.full.blob.size,
        captured_at_hint: capturedHint(row.file),
      })
    } catch {
      row.status = 'error'
      row.error = 'Upload fehlgeschlagen — bitte nochmal versuchen'
      row.progress = 0
    }
  })
  await runPool(tasks, MAX_CONCURRENT)
  if (!succeeded.length) return { confirmed: 0 }

  try {
    const result = await publicApi.confirmPhotoUploads(props.eventId, props.token, succeeded)
    const confirmed = Number(result?.confirmed) || 0
    for (const { row } of prepared) {
      if (row.status !== 'uploaded') continue
      row.status = 'done'
      row.progress = 100
    }
    // A partial confirm says nothing about *which* entries fell through, so
    // there is no row to blame. It is reported as a count and nothing else.
    return { confirmed, missed: succeeded.length - confirmed }
  } catch (err) {
    // The objects are on S3 but their rows never flipped, so the sweep takes
    // them within 24 h. Retrying is therefore safe and creates no duplicate:
    // a second attempt mints fresh ids and the abandoned pair disappears.
    const message =
      err.status === 404
        ? 'Die Fotos sind angekommen, konnten aber nicht mehr zugeordnet werden — bitte lade die Seite neu.'
        : 'Das Bestätigen hat nicht geklappt. Bitte nochmal versuchen — doppelt landet nichts.'
    for (const { row } of prepared) {
      if (row.status !== 'uploaded') continue
      row.status = 'error'
      row.error = message
      row.progress = 0
    }
    return { confirmed: 0, stop: message }
  }
}

async function startUpload() {
  if (!canUpload.value) return
  notice.value = ''

  // The window can have closed while this page sat open on somebody's phone,
  // and finding that out after 30 photos went through the canvas is the worst
  // possible moment. One cheap GET first — it also refreshes the count.
  try {
    const fresh = await publicApi.getPhotoUploadPage(props.eventId, props.token)
    page.value = fresh
    // The closed panel replaces the form, so it says everything needed here.
    if (!fresh.upload_open) return
  } catch (err) {
    if (err.status === 404) {
      gone.value = true
      page.value = null
      return
    }
    notice.value =
      'Die Seite konnte gerade nicht geprüft werden. Versuch es in einem Moment nochmal.'
    return
  }

  // Read the rows back out of the ref. `rows.value` is the reactive array, so
  // its members come out as proxies — mutating the raw objects that were
  // pushed into it would never reach the render effect and the progress bars
  // would sit still for the whole upload.
  const queue = rows.value.filter((row) => row.status !== 'error')
  if (!queue.length) return

  uploading.value = true
  let confirmedTotal = 0
  let missedTotal = 0
  let stopped = ''
  try {
    // A drop larger than one batch is the normal case, not an error: chunked
    // rather than rejected, and each chunk is its own pair of Lambda calls.
    for (let start = 0; start < queue.length; start += batchSize.value) {
      const result = await processBatch(queue.slice(start, start + batchSize.value))
      confirmedTotal += result.confirmed
      missedTotal += result.missed || 0
      if (result.stop) {
        stopped = result.stop
        break
      }
    }
  } finally {
    uploading.value = false
  }

  if (confirmedTotal > 0) {
    sessionTotal.value += confirmedTotal
    if (page.value) {
      page.value = {
        ...page.value,
        photo_count: (Number(page.value.photo_count) || 0) + confirmedTotal,
      }
    }
    // The one-way rule, made real: what is up leaves this page.
    dropDoneRows()
  }

  if (stopped) {
    notice.value = stopped
  } else if (missedTotal > 0) {
    notice.value =
      missedTotal === 1
        ? 'Ein Foto ist unterwegs verloren gegangen. Wenn es dir wichtig ist, schick es nochmal.'
        : `${missedTotal} Fotos sind unterwegs verloren gegangen. Wenn sie dir wichtig sind, schick sie nochmal.`
  }

  // The thanks screen only takes over once nothing is left to look at — with
  // failed rows still on screen it would hide the retry button.
  celebrating.value = sessionTotal.value > 0 && rows.value.length === 0
}

/* -------------------------------------------------------------------------
 * Lifecycle
 * ---------------------------------------------------------------------- */

// A file dropped anywhere but on the drop zone would otherwise navigate the
// tab to the JPEG, taking the whole selection with it.
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
  revokeAllPreviews()
})
</script>

<style scoped>
.photo-upload {
  overflow-x: hidden;
}

.loading-state {
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.gone-state,
.error-state {
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.gone-state h2,
.error-state h2 {
  font-size: var(--text-xl);
  margin-bottom: var(--space-2);
}

.gone-state p,
.error-state p {
  color: var(--color-text-muted);
  margin-bottom: var(--space-3);
}

.page-header {
  margin-bottom: var(--space-4);
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: 0.15rem;
}

.page-header h2 {
  margin-bottom: 0.25rem;
}

.event-line {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

/* The deadline is the one line on this page with a consequence, so it does not
   sit at the same weight as the event date above it. */
.closes-line {
  margin-top: 0.25rem;
  color: var(--color-text);
  font-weight: 600;
}

.closed-state h3 {
  font-size: var(--text-xl);
  margin-bottom: var(--space-2);
}

.closed-state p {
  margin: 0;
  color: var(--color-text-muted);
}

.intro {
  margin-bottom: var(--space-5);
}

.intro p {
  margin-bottom: var(--space-3);
}

.intro-lead {
  font-size: var(--text-lg);
}

/* Organiser text arrives as typed, line breaks included. */
.privacy-facts {
  list-style: none;
  margin: 0 0 1rem;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--pico-muted-border-color);
  border-radius: var(--pico-border-radius);
  /* Quieter than the prose around it: these are reassurances, not the pitch. */
  font-size: 0.9rem;
}

.privacy-facts li {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  margin: 0;
  padding: 0.2rem 0;
}

.privacy-facts svg {
  flex: 0 0 auto;
  margin-top: 0.15rem;
  color: var(--pico-muted-color);
}

.intro-custom {
  white-space: pre-line;
}

.count-line {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.success-panel {
  margin-bottom: var(--space-5);
}

.success-headline {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--color-success-text);
  margin-bottom: var(--space-2);
}

.success-panel p {
  margin-bottom: var(--space-3);
}

.success-panel button {
  width: auto;
  margin: 0;
  min-height: 48px;
}

.notice-line {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.drop-zone {
  padding: var(--space-5) var(--space-4);
  text-align: center;
  border-style: dashed;
  border-width: 2px;
  margin-bottom: var(--space-4);
}

.drop-zone--over {
  border-color: var(--color-brand);
  background: var(--color-brand-subtle);
}

.drop-lead {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

/* The one tap that matters on this page, so it gets a full-width target rather
   than the browser's default button-plus-filename line. */
.drop-zone input[type='file'] {
  margin: 0 auto var(--space-3);
  max-width: 24rem;
  min-height: 48px;
}

.hint-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: 0;
}

.selection-line {
  font-size: var(--text-base);
  margin-bottom: var(--space-2);
}

.preview-grid {
  list-style: none;
  padding: 0;
  /* Small tiles on purpose: 40 of them have to be scannable with a thumb, and
     the picked file is the source, so nothing here costs a request. */
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: var(--space-2);
  margin: 0 0 var(--space-4);
}

.preview-card {
  margin: 0;
  min-width: 0;
}

.preview-frame {
  position: relative;
  aspect-ratio: 1 / 1;
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.preview-frame--failed {
  border-color: var(--color-danger-text);
}

.preview-frame--failed img {
  opacity: 0.4;
}

.preview-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* 40 px on a ~96 px tile: big enough for a thumb, small enough to leave the
   photo recognisable while choosing. */
.preview-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  margin: 0;
  border: none;
  border-radius: var(--radius-pill);
  /* Fixed colours: this sits on the photo, not on a themed surface. */
  background: rgba(12, 30, 60, 0.72);
  color: #fff;
  cursor: pointer;
}

.preview-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 0.35rem;
  margin: 0;
  border-radius: 0;
}

.preview-name {
  display: block;
  margin-top: 0.15rem;
  /* One line, clipped: a phone gallery hands out names like
     „IMG_20260712_014233_HDR.jpg" and 40 of them wrapped to three lines each
     would bury the grid. */
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--color-text);
}

.success-inline {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-success-bg);
  color: var(--color-success-text);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  font-size: var(--text-base);
}

.preview-state {
  display: block;
  margin-top: 0.15rem;
  color: var(--color-text-muted);
  overflow-wrap: anywhere;
}

.preview-error {
  display: block;
  margin-top: 0.15rem;
  color: var(--color-danger-text);
  overflow-wrap: anywhere;
}

.retry-button {
  width: auto;
  margin-bottom: var(--space-4);
  min-height: 48px;
}

.consent {
  /* The one checkbox on the page and the thing that unlocks the button, so it
     gets a box of its own rather than a line of small print. */
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--color-brand-subtle);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
  font-size: var(--text-lg);
}

.consent input[type='checkbox'] {
  width: 1.5rem;
  height: 1.5rem;
  margin: 0;
  flex-shrink: 0;
}

.oneway-note {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-3);
}

.notice-box {
  color: var(--color-danger-text);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-bg);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
}

.upload-form button[type='submit'] {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 52px;
  font-size: var(--text-lg);
}

.page-footer {
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.page-footer p {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}
</style>

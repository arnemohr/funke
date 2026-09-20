<template>
  <Teleport to="body">
    <div
      class="editor-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Foto unkenntlich machen"
    >
      <div class="editor-sheet">
        <header class="editor-head">
          <h3>Unkenntlich machen</h3>
          <button
            type="button"
            class="editor-close"
            aria-label="Schließen"
            :disabled="busy"
            @click="requestCancel"
          >
            <X :size="22" aria-hidden="true" />
          </button>
        </header>

        <div v-if="loading" class="editor-state" aria-busy="true">Foto wird geladen ...</div>

        <div v-else-if="loadError" role="alert" class="editor-error">
          <p><strong>Das Foto lässt sich hier nicht bearbeiten.</strong></p>
          <p>{{ loadError }}</p>
        </div>

        <template v-else>
          <p class="editor-hint">
            Zieh ein Rechteck über jedes Gesicht, das raus soll — mit der Maus oder dem Finger. Die
            Vorschau zeigt schon, wie es danach aussieht.
          </p>

          <!-- The canvas is the whole interaction surface, so it must not scroll
               or zoom under the finger: `touch-action: none` in the styles below
               hands every gesture to the pointer handlers. -->
          <div ref="stageEl" class="editor-stage">
            <canvas
              ref="canvasEl"
              class="editor-canvas"
              @pointerdown="onPointerDown"
              @pointermove="onPointerMove"
              @pointerup="onPointerUp"
              @pointercancel="onPointerUp"
            ></canvas>
          </div>

          <div class="editor-detect">
            <button
              type="button"
              class="outline"
              :disabled="busy || detecting"
              :aria-busy="detecting"
              @click="runDetection"
            >
              <ScanFace :size="17" aria-hidden="true" />
              {{ detecting ? 'Sucht Gesichter ...' : 'Gesichter suchen' }}
            </button>
            <small v-if="!scanned && !detecting">
              Schlägt Bereiche vor, die du einzeln bestätigst. Beim ersten Mal lädt der Browser
              dafür einmalig ein paar Megabyte.
            </small>
            <small v-else-if="detecting">Das kann ein paar Sekunden dauern.</small>
            <small v-else-if="detectError" class="detect-error" role="alert">
              {{ detectError }}
            </small>
            <small v-else-if="!suggestions.length">
              Nichts gefunden. Das heißt nicht, dass keins drauf ist — zieh die Bereiche von Hand.
            </small>
            <small v-else>
              {{ suggestions.length }}
              {{ suggestions.length === 1 ? 'Vorschlag' : 'Vorschläge' }} — sieh sie durch. Das
              Modell übersieht Profile, Halbdunkel und alles Kleine.
            </small>
          </div>

          <div v-if="suggestions.length" class="editor-rects editor-suggestions">
            <div class="suggest-head">
              <strong>Vorschläge</strong>
              <button
                type="button"
                class="outline secondary"
                :disabled="busy"
                @click="acceptAllSuggestions"
              >
                Alle übernehmen
              </button>
            </div>
            <ul>
              <li v-for="(rect, index) in suggestions" :key="rect.id">
                <span>
                  Vorschlag {{ index + 1 }} — {{ Math.round(rect.w) }} × {{ Math.round(rect.h) }} px
                </span>
                <span class="rect-buttons">
                  <button
                    type="button"
                    class="outline rect-accept"
                    :disabled="busy"
                    @click="acceptSuggestion(rect.id)"
                  >
                    <Check :size="15" aria-hidden="true" />
                    Übernehmen
                  </button>
                  <button
                    type="button"
                    class="outline secondary rect-remove"
                    :disabled="busy"
                    @click="removeRect(rect.id)"
                  >
                    Verwerfen
                  </button>
                </span>
              </li>
            </ul>
          </div>

          <div class="editor-rects">
            <p v-if="!confirmed.length" class="editor-muted">
              Noch kein Bereich markiert. Ohne Markierung gibt es nichts zu ersetzen.
            </p>
            <ul v-else>
              <li v-for="(rect, index) in confirmed" :key="rect.id">
                <span>
                  Bereich {{ index + 1 }} — {{ Math.round(rect.w) }} × {{ Math.round(rect.h) }} px
                </span>
                <button
                  type="button"
                  class="outline secondary rect-remove"
                  :disabled="busy"
                  @click="removeRect(rect.id)"
                >
                  Entfernen
                </button>
              </li>
            </ul>
          </div>

          <div v-if="saveError" role="alert" class="editor-error">{{ saveError }}</div>

          <!-- The confirm step is a panel rather than a nested <dialog>: this
               component is already a modal, and the sentence that has to be read
               is longer than a window.confirm line. -->
          <div v-if="confirming" class="editor-warning">
            <p>
              <strong>Das ist endgültig.</strong> Das Original wird auf S3 überschrieben — großes
              Bild und Vorschau. Es gibt keine Kopie, auch keine alte Version im Speicher, und was
              vorher schon heruntergeladen wurde, holt das nicht zurück.
            </p>
            <p v-if="progress" aria-busy="true">{{ progress }}</p>
          </div>

          <footer class="editor-actions">
            <template v-if="confirming">
              <button type="button" class="secondary" :disabled="busy" @click="confirming = false">
                Zurück
              </button>
              <button
                type="button"
                class="btn-danger"
                :disabled="busy"
                :aria-busy="busy"
                @click="applyEdit"
              >
                {{ busy ? 'Wird ersetzt ...' : 'Ja, Original ersetzen' }}
              </button>
            </template>
            <template v-else>
              <button type="button" class="secondary" @click="requestCancel">Abbrechen</button>
              <div class="action-with-hint">
                <!-- „N Bereiche", never „Foto anonymisiert": the button states
                     what it does, not that the job is done. An unaccepted
                     suggestion is counted out loud right below it, because
                     leaving one behind is the one mistake this screen invites. -->
                <button
                  type="button"
                  class="btn-danger"
                  :disabled="!confirmed.length"
                  @click="confirming = true"
                >
                  {{ confirmed.length }}
                  {{ confirmed.length === 1 ? 'Bereich' : 'Bereiche' }} unkenntlich machen — das
                  Original wird ersetzt
                </button>
                <small v-if="suggestions.length" class="pending-hint">
                  {{ suggestions.length }}
                  {{ suggestions.length === 1 ? 'Vorschlag ist' : 'Vorschläge sind' }} noch nicht
                  übernommen und {{ suggestions.length === 1 ? 'bleibt' : 'bleiben' }} sichtbar.
                </small>
              </div>
            </template>
          </footer>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
/**
 * „Unkenntlich machen" für ein Eventfoto (Spec 024).
 *
 * The organiser drags rectangles over faces, and on save every region is
 * **pixelated, not blurred**: the region is scaled far down and drawn back up
 * with `imageSmoothingEnabled = false`. Spec 024 § Unkenntlich machen is
 * explicit about why there is only this one mode — a coarse mosaic throws the
 * pixels away, while a Gaussian blur is a reversible convolution that can under
 * some circumstances be deconvolved back into a recognisable face. A mode that
 * only looks like anonymisation is worse than none, because it gets trusted.
 *
 * No byte passes through the Lambda: the browser pulls `full` from S3, redraws
 * it and puts the result back over the same two keys with fresh presigned
 * POSTs. The bucket is unversioned precisely so that this overwrite is real.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ScanFace, X } from 'lucide-vue-next'
import { adminApi, postPresignedForm } from '../services/api'
import { detectFaces } from '../composables/useFaceDetection'

// Export targets, same as the guest upload path (spec 024, „Skalieren im
// Browser"): the pixelated version replaces the original, so it has to land in
// the same shape the rest of the collection has.
const FULL_EDGE = 2560
const FULL_QUALITY = 0.85
const THUMB_EDGE = 400
const THUMB_QUALITY = 0.7

// Mosaic block size as a share of the shorter side of the region, with a floor.
// Relative, because a block that is fixed in pixels is a heavy mosaic on a face
// in the background and a light one on a face filling the frame. The floor is
// what keeps a small selection from staying readable.
const BLOCK_SHARE = 0.08
const MIN_BLOCK_PX = 8

// A drag shorter than this (on screen, not in source pixels) is a tap that
// missed the „Entfernen" button, not a rectangle.
const MIN_DRAG_PX = 6

// How tall the preview may get. Everything below it — the region list and the
// two buttons — has to stay reachable without scrolling past the photo.
const STAGE_MAX_VH = 0.58

const props = defineProps({
  /** The photo row from the admin list: needs `photo_id` and `full_url`. */
  photo: { type: Object, required: true },
  eventId: { type: String, required: true },
  /**
   * The presigned POST policies cap each variant, and an oversized POST fails
   * with a bare S3 400. Defaults mirror spec 024; the page passes the values
   * the backend actually reported in `limits`.
   */
  maxBytesFull: { type: Number, default: 6291456 },
  maxBytesThumb: { type: Number, default: 409600 },
})

const emit = defineEmits(['saved', 'cancelled'])

const stageEl = ref(null)
const canvasEl = ref(null)

const loading = ref(true)
const loadError = ref(null)
const saveError = ref(null)
const confirming = ref(false)
const busy = ref(false)
const progress = ref('')

/**
 * Regions in **source pixel coordinates**, never in preview coordinates. The
 * preview is refitted whenever the window changes size (a tablet turned
 * sideways mid-edit is the normal case), and rectangles stored against the old
 * fit would then sit next to the faces instead of on them.
 */
const rects = ref([])

/**
 * A region carries `suggested: true` until a human accepts it, and **only
 * accepted regions are ever pixelated** — in the preview and in the export
 * alike. That is the whole safety property of the detection layer: the model
 * proposes, a person decides, and a photo nobody looked at cannot be touched.
 */
const confirmed = computed(() => rects.value.filter((rect) => !rect.suggested))
const suggestions = computed(() => rects.value.filter((rect) => rect.suggested))

const detecting = ref(false)
const detectError = ref(null)
// Whether a scan has run at all — „nichts gefunden" and „noch nicht gesucht"
// are different things and must not share a sentence.
const scanned = ref(false)

let bitmap = null
// Source px -> preview px. The one number that maps between the two spaces.
let previewScale = 1
let drag = null
let rafHandle = 0
let resizeObserver = null
let nextRectId = 1

/* -------------------------------------------------------------------------
 * Loading the image without tainting the canvas
 *
 * The photo comes from a presigned GET on a bucket in another origin. An
 * `<img crossorigin="anonymous">` would need a CORS rule that allows GET, and
 * without one the image loads but the canvas is *tainted* — `toBlob()` then
 * throws a SecurityError, which is exactly the wrong moment to find out.
 *
 * So the bytes are fetched instead and decoded from the Blob: a Blob has no
 * origin, so `createImageBitmap` on it produces an untainted bitmap. The fetch
 * needs the bucket's CORS rule to allow GET, and it does — but a correct rule is
 * not sufficient on its own; see `fetchFull` for the cache trap that defeats it
 * and reports itself as a CORS failure.
 * ---------------------------------------------------------------------- */

/** One fetch of the `full` variant, with the HTTP status carried in the error. */
async function fetchFull(url) {
  // `cache: 'reload'` is not about freshness — it is about a poisoned cache
  // entry, and without it this function fails every time.
  //
  // The lightbox has already displayed this exact URL through an `<img>`. That
  // is a no-cors request, and the response Chrome stored for it carries no
  // `Access-Control-Allow-Origin` that script may use. The editor's `fetch()`
  // of the same URL is a cors-mode request, hits that entry, and is rejected —
  // with a bare `TypeError: Failed to fetch` that is indistinguishable from a
  // bucket missing its CORS rule. It is not: reproduced in Chrome against a
  // bucket whose rule allows GET from `*`, where the same fetch succeeds when
  // nothing loaded the URL as an image first (0 kB in 7 ms in the network tab
  // is the tell — the request never left the browser).
  //
  // Forcing the request past the cache costs one extra download of the full
  // variant and removes the whole class of failure. The alternative — putting
  // `crossorigin="anonymous"` on the lightbox `<img>` so both requests share a
  // CORS-clean entry — would save that download but makes every displayed photo
  // depend on the bucket's origin list being right for the host the app is
  // served from. A broken editor is better than a grid of broken images.
  const response = await fetch(url, { cache: 'reload' })
  if (!response.ok) {
    const err = new Error(`http_${response.status}`)
    err.httpStatus = response.status
    throw err
  }
  return response.blob()
}

/** The status of a failed `fetchFull`, or 0 when the request never got one. */
function httpStatusOf(err) {
  return typeof err?.httpStatus === 'number' ? err.httpStatus : 0
}

async function loadImage() {
  loading.value = true
  loadError.value = null

  if (!props.photo.full_url) {
    loading.value = false
    loadError.value =
      'Für dieses Foto gibt es gerade keine gültige Bild-Adresse. Lade die Seite neu und ' +
      'versuch es nochmal.'
    return
  }

  let blob
  try {
    blob = await fetchFull(props.photo.full_url)
  } catch (err) {
    const status = httpStatusOf(err)

    // A presigned GET lives 15 minutes. The grid may have been open far longer
    // than that before somebody clicked into this photo, which makes an expired
    // signature the single most likely failure here — and it is one we can
    // repair without the user doing anything. A no-op PATCH answers with the
    // row *and* freshly signed URLs, so it is the cheapest way to mint one.
    if (status === 403 || status === 404) {
      try {
        const fresh = await adminApi.eventPhotos.patchPhoto(props.eventId, props.photo.photo_id, {})
        if (fresh?.full_url) blob = await fetchFull(fresh.full_url)
      } catch {
        // Fall through to the message below — the retry is a courtesy, not a
        // second place to report errors from.
      }
    }

    if (!blob) {
      loading.value = false
      // Say what actually happened. The previous version blamed the bucket's
      // CORS rule for *every* failure that was not an HTTP status, which sent
      // the reader hunting a correctly configured bucket while the real cause
      // — an expired signature, a dropped connection, a blocker in the browser
      // — went unmentioned. A wrong diagnosis in an error message costs more
      // than no diagnosis.
      loadError.value = status
        ? `Das Bild ist auf S3 nicht erreichbar (HTTP ${status}), auch nicht mit einer frisch ` +
          'signierten Adresse. Lade die Seite neu; bleibt es dabei, bitte melden.'
        : 'Der Browser hat die Anfrage an S3 abgebrochen ' +
          `(${err?.name || 'Fehler'}: ${err?.message || 'unbekannt'}). Das ist keine Verbindung, ` +
          'ein Blocker im Browser oder eine Einstellung an der Anlage — im Netzwerk-Tab steht ' +
          'bei der Anfrage an s3.eu-central-1.amazonaws.com, welche davon.'
      return
    }
  }

  try {
    // `from-image` for consistency with the upload path; the stored variant
    // already has its rotation baked into the pixels, so this is a no-op that
    // stays correct if that ever changes.
    bitmap = await createImageBitmap(blob, { imageOrientation: 'from-image' })
  } catch {
    loadError.value = 'Der Browser kann diese Bilddatei nicht dekodieren.'
    return
  } finally {
    loading.value = false
  }

  // The canvas only exists once `loading` is false and the template swapped —
  // measuring the stage before that flush gives a scale of zero.
  await nextTick()
  fitStage()
  observeStage()
}

/* -------------------------------------------------------------------------
 * Preview
 * ---------------------------------------------------------------------- */

function fitStage() {
  if (!bitmap || !canvasEl.value || !stageEl.value) return
  const maxW = Math.max(160, stageEl.value.clientWidth)
  const maxH = Math.max(160, Math.round(window.innerHeight * STAGE_MAX_VH))
  // Never upscale: a blown-up 400 px photo would invite rectangles drawn more
  // precisely than the pixels underneath them.
  previewScale = Math.min(1, maxW / bitmap.width, maxH / bitmap.height)
  // Backing store in CSS pixels, not device pixels. A devicePixelRatio canvas
  // would be crisper, but every pointer coordinate would then need a second
  // conversion — and this canvas is a working surface, not the deliverable.
  canvasEl.value.width = Math.max(1, Math.round(bitmap.width * previewScale))
  canvasEl.value.height = Math.max(1, Math.round(bitmap.height * previewScale))
  scheduleRedraw()
}

function observeStage() {
  if (!stageEl.value || typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(() => fitStage())
  resizeObserver.observe(stageEl.value)
}

/** Coalesce redraws to one per frame — a pointermove fires far more often. */
function scheduleRedraw() {
  if (rafHandle) return
  rafHandle = requestAnimationFrame(() => {
    rafHandle = 0
    redraw()
  })
}

function redraw() {
  const canvas = canvasEl.value
  if (!canvas || !bitmap) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)

  // The preview applies the same mosaic the export will, at preview scale, so
  // „ist das Gesicht wirklich weg" is answered before anything is overwritten.
  for (const rect of confirmed.value) {
    const preview = toPreview(rect)
    pixelateRegion(ctx, preview, blockSizeFor(rect) * previewScale)
    outline(ctx, preview, 'rgba(232, 114, 42, 0.95)')
  }

  // A suggestion is drawn as an empty frame in a different colour and is
  // deliberately NOT mosaicked: the mosaic is the signal for „this will be
  // applied". If a proposal looked the same as an accepted region, the screen
  // would be telling the organiser the work is done before they did it.
  for (const rect of suggestions.value) {
    outline(ctx, toPreview(rect), 'rgba(86, 156, 214, 0.95)')
  }

  if (drag) {
    outline(ctx, toPreview(normalise(drag)), 'rgba(255, 255, 255, 0.95)')
  }
}

function outline(ctx, rect, colour) {
  ctx.save()
  ctx.lineWidth = 2
  ctx.setLineDash([6, 4])
  ctx.strokeStyle = colour
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h)
  ctx.restore()
}

function toPreview(rect) {
  return {
    x: rect.x * previewScale,
    y: rect.y * previewScale,
    w: rect.w * previewScale,
    h: rect.h * previewScale,
  }
}

function blockSizeFor(rect) {
  return Math.max(MIN_BLOCK_PX, Math.round(Math.min(rect.w, rect.h) * BLOCK_SHARE))
}

/**
 * Replace one region with a mosaic, in place.
 *
 * Down into a tiny scratch canvas, back up with smoothing off. The information
 * is destroyed by the downscale, not by the way it is drawn back — which is
 * what makes this irreversible and a blur not.
 * @param {CanvasRenderingContext2D} ctx - Target context, drawn in its own coordinates
 * @param {{x: number, y: number, w: number, h: number}} rect - Region in that space
 * @param {number} block - Edge length of one mosaic block, in that space
 */
function pixelateRegion(ctx, rect, block) {
  const x = Math.max(0, Math.round(rect.x))
  const y = Math.max(0, Math.round(rect.y))
  const w = Math.max(1, Math.min(Math.round(rect.w), ctx.canvas.width - x))
  const h = Math.max(1, Math.min(Math.round(rect.h), ctx.canvas.height - y))
  const cols = Math.max(1, Math.round(w / Math.max(1, block)))
  const rows = Math.max(1, Math.round(h / Math.max(1, block)))

  const scratch = document.createElement('canvas')
  scratch.width = cols
  scratch.height = rows
  const sctx = scratch.getContext('2d')
  sctx.imageSmoothingEnabled = true
  sctx.imageSmoothingQuality = 'high'
  sctx.drawImage(ctx.canvas, x, y, w, h, 0, 0, cols, rows)

  ctx.save()
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(scratch, 0, 0, cols, rows, x, y, w, h)
  ctx.restore()

  // iOS Safari caps the total canvas backing store of a page, and a dozen
  // regions on a 2560 px export allocate a dozen of these.
  scratch.width = 0
  scratch.height = 0
}

/* -------------------------------------------------------------------------
 * Drawing rectangles (pointer events cover mouse, touch and pen in one path —
 * this gets used on a tablet at a kitchen table)
 * ---------------------------------------------------------------------- */

function toSource(event) {
  const box = canvasEl.value.getBoundingClientRect()
  // Mapped from the *displayed* box rather than from the backing store, so a
  // canvas that CSS shrank to fit still yields correct source coordinates.
  const x = ((event.clientX - box.left) / box.width) * bitmap.width
  const y = ((event.clientY - box.top) / box.height) * bitmap.height
  return {
    x: Math.min(Math.max(x, 0), bitmap.width),
    y: Math.min(Math.max(y, 0), bitmap.height),
  }
}

function normalise(state) {
  return {
    x: Math.min(state.x0, state.x1),
    y: Math.min(state.y0, state.y1),
    w: Math.abs(state.x1 - state.x0),
    h: Math.abs(state.y1 - state.y0),
  }
}

function onPointerDown(event) {
  if (busy.value || !bitmap) return
  const point = toSource(event)
  drag = { x0: point.x, y0: point.y, x1: point.x, y1: point.y, id: event.pointerId }
  // Capture, so a drag that runs off the canvas — over a face at the edge of
  // the frame — keeps being tracked instead of stopping at the border.
  canvasEl.value.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function onPointerMove(event) {
  if (!drag || event.pointerId !== drag.id) return
  const point = toSource(event)
  drag.x1 = point.x
  drag.y1 = point.y
  scheduleRedraw()
}

function onPointerUp(event) {
  if (!drag || event.pointerId !== drag.id) return
  const rect = normalise(drag)
  drag = null
  if (rect.w * previewScale >= MIN_DRAG_PX && rect.h * previewScale >= MIN_DRAG_PX) {
    rects.value = [...rects.value, { id: nextRectId++, ...rect }]
  }
  scheduleRedraw()
}

function removeRect(id) {
  rects.value = rects.value.filter((rect) => rect.id !== id)
  scheduleRedraw()
}

/* -------------------------------------------------------------------------
 * Detection — a proposal layer over the manual one
 * ---------------------------------------------------------------------- */

/** Does this candidate already sit on a region the organiser has in hand? */
function overlapsExisting(candidate) {
  return rects.value.some((rect) => {
    const overlapW =
      Math.min(rect.x + rect.w, candidate.x + candidate.w) - Math.max(rect.x, candidate.x)
    const overlapH =
      Math.min(rect.y + rect.h, candidate.y + candidate.h) - Math.max(rect.y, candidate.y)
    if (overlapW <= 0 || overlapH <= 0) return false
    // Half the candidate's area is enough to call it a duplicate: a second
    // frame over a face already marked is noise the organiser has to clear.
    return overlapW * overlapH >= 0.5 * candidate.w * candidate.h
  })
}

async function runDetection() {
  if (detecting.value || busy.value || !bitmap) return
  detecting.value = true
  detectError.value = null

  try {
    const found = await detectFaces(bitmap)
    const fresh = found.filter((candidate) => !overlapsExisting(candidate))
    rects.value = [
      ...rects.value,
      ...fresh.map((candidate) => ({
        id: nextRectId++,
        x: candidate.x,
        y: candidate.y,
        w: candidate.w,
        h: candidate.h,
        suggested: true,
      })),
    ]
    scanned.value = true
  } catch (err) {
    // Two failures worth telling apart: the runtime is not there (a deploy or
    // network problem, nothing to do with this photo) versus inference broke.
    detectError.value =
      err?.message === 'no_runtime'
        ? 'Die Gesichtserkennung konnte nicht geladen werden. Markiere die Bereiche von Hand — ' +
          'das Ergebnis ist dasselbe.'
        : 'Die Gesichtserkennung ist an diesem Foto gescheitert. Markiere die Bereiche von Hand.'
  } finally {
    detecting.value = false
    scheduleRedraw()
  }
}

function acceptSuggestion(id) {
  rects.value = rects.value.map((rect) => (rect.id === id ? { ...rect, suggested: false } : rect))
  scheduleRedraw()
}

function acceptAllSuggestions() {
  rects.value = rects.value.map((rect) => (rect.suggested ? { ...rect, suggested: false } : rect))
  scheduleRedraw()
}

/* -------------------------------------------------------------------------
 * Export and upload
 * ---------------------------------------------------------------------- */

/**
 * Encode a canvas as JPEG at a target edge length, staying under a byte cap.
 *
 * The cap is not cosmetic: it is a `content-length-range` condition in the
 * presigned POST policy, and exceeding it fails the upload with an S3 400 that
 * carries no usable message. Quality is given up first, resolution second.
 * @param {HTMLCanvasElement} source - Fully rendered canvas
 * @param {number} maxEdge - Longest edge of the output
 * @param {number} quality - Preferred JPEG quality
 * @param {number} maxBytes - Hard ceiling from the upload policy
 * @returns {Promise<{blob: Blob, width: number, height: number}>}
 */
async function encodeVariant(source, maxEdge, quality, maxBytes) {
  const attempts = [
    { edge: maxEdge, quality },
    { edge: maxEdge, quality: Math.max(0.5, quality - 0.15) },
    { edge: maxEdge, quality: Math.max(0.4, quality - 0.3) },
    { edge: Math.round(maxEdge * 0.7), quality: Math.max(0.5, quality - 0.1) },
    { edge: Math.round(maxEdge * 0.5), quality: Math.max(0.5, quality - 0.1) },
  ]

  let last = null
  for (const attempt of attempts) {
    last = await encodeOnce(source, attempt.edge, attempt.quality)
    if (last.blob.size <= maxBytes) return last
  }
  throw new Error('Das bearbeitete Bild bleibt zu groß für den Upload.')
}

function encodeOnce(source, maxEdge, quality) {
  const scale = Math.min(1, maxEdge / Math.max(source.width, source.height))
  const width = Math.max(1, Math.round(source.width * scale))
  const height = Math.max(1, Math.round(source.height * scale))

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  // JPEG has no alpha channel; without this a transparent edge lands on black.
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(source, 0, 0, width, height)

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        canvas.width = 0
        canvas.height = 0
        if (blob) resolve({ blob, width, height })
        // The one likely cause is a tainted canvas — see the CORS note above.
        else reject(new Error('Das Bild konnte nicht umgerechnet werden.'))
      },
      'image/jpeg',
      quality,
    )
  })
}

/**
 * Render the pixelated version at **full source resolution**.
 *
 * Not from the preview canvas: that one is a few hundred pixels wide, and
 * exporting it would replace the photo with a thumbnail. The rectangles are
 * kept in source coordinates precisely so they can be applied here directly.
 * @returns {HTMLCanvasElement}
 */
function renderFullResolution() {
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  const ctx = canvas.getContext('2d')
  ctx.drawImage(bitmap, 0, 0)
  // `confirmed`, not `rects`: an unaccepted suggestion must never reach the
  // export. See the comment on the computed.
  for (const rect of confirmed.value) {
    pixelateRegion(ctx, rect, blockSizeFor(rect))
  }
  return canvas
}

async function applyEdit() {
  if (busy.value || !confirmed.value.length) return
  busy.value = true
  saveError.value = null
  progress.value = 'Bild wird neu gerechnet ...'

  let full
  let thumb
  let master = null
  try {
    master = renderFullResolution()
    full = await encodeVariant(master, FULL_EDGE, FULL_QUALITY, props.maxBytesFull)
    thumb = await encodeVariant(master, THUMB_EDGE, THUMB_QUALITY, props.maxBytesThumb)
  } catch (err) {
    saveError.value = err.message || 'Das Bild konnte nicht umgerechnet werden.'
    busy.value = false
    progress.value = ''
    return
  } finally {
    if (master) {
      master.width = 0
      master.height = 0
    }
  }

  try {
    progress.value = 'Upload-Erlaubnis wird geholt ...'
    const upload = await adminApi.eventPhotos.createEditUploads(props.eventId, props.photo.photo_id)

    // `full` first, deliberately. If the second POST fails, one of the two
    // objects still carries the face — and the one that must not is `full`:
    // that is what the download list hands out and what leaves our reach. A
    // thumbnail left behind is visible only in this admin grid, and the retry
    // below fixes it. `edit-confirm` is not called in that case, so the row is
    // never marked as edited while a variant is still the original.
    progress.value = 'Großes Bild wird ersetzt ...'
    await postPresignedForm(upload.full, full.blob)
    progress.value = 'Vorschaubild wird ersetzt ...'
    await postPresignedForm(upload.thumb, thumb.blob)

    progress.value = 'Wird eingetragen ...'
    const updated = await adminApi.eventPhotos.confirmEdit(props.eventId, props.photo.photo_id, {
      width: full.width,
      height: full.height,
      bytes: full.blob.size,
    })
    emit('saved', updated)
  } catch (err) {
    // A 409 is the one refusal that will not go away by trying again right
    // now: the uploader's own presigned POST is still valid for a few minutes
    // and would overwrite the pixelated version with the original. Its own
    // sentence already says what to do, so „nochmal drücken" is not appended
    // to it — that would read as a contradiction.
    if (err.status === 409) {
      saveError.value = err.message || 'Das Speichern ist fehlgeschlagen.'
    } else {
      // Otherwise retrying is safe: both POSTs write the same two keys, and
      // re-pixelating an already-pixelated region changes nothing that matters.
      saveError.value =
        (err.message || 'Das Speichern ist fehlgeschlagen.') +
        ' Bitte nochmal „Ja, Original ersetzen" — der Vorgang lässt sich gefahrlos wiederholen.'
    }
  } finally {
    busy.value = false
    progress.value = ''
  }
}

/* -------------------------------------------------------------------------
 * Lifecycle
 * ---------------------------------------------------------------------- */

function requestCancel() {
  if (busy.value) return
  // Only confirmed regions are worth a warning: discarding suggestions costs
  // nothing, the scan can be run again in a second.
  if (
    confirmed.value.length &&
    !window.confirm('Bearbeitung verwerfen? Die Markierungen sind weg.')
  ) {
    return
  }
  emit('cancelled')
}

function onKeydown(event) {
  if (event.key !== 'Escape' || busy.value) return
  event.preventDefault()
  requestCancel()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // The editor covers the page; letting the page scroll behind it is how a
  // dragged rectangle turns into a scrolled document.
  document.body.style.overflow = 'hidden'
  loadImage()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
  if (rafHandle) cancelAnimationFrame(rafHandle)
  if (resizeObserver) resizeObserver.disconnect()
  if (bitmap) bitmap.close()
})
</script>

<style scoped>
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  overflow-y: auto;
  padding: var(--space-3);
  background: rgba(8, 14, 26, 0.94);
  overscroll-behavior: contain;
}

.editor-sheet {
  width: 100%;
  max-width: 900px;
  margin: auto 0;
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border-radius: var(--radius-lg);
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.editor-head h3 {
  margin: 0;
}

.editor-close {
  width: 44px;
  height: 44px;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
}

.editor-state {
  padding: var(--space-5) 0;
  text-align: center;
  color: var(--color-text-muted);
}

.editor-hint {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  margin-bottom: var(--space-3);
}

.editor-stage {
  display: flex;
  justify-content: center;
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
  padding: var(--space-2);
  margin-bottom: var(--space-3);
}

.editor-canvas {
  display: block;
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-sm);
  cursor: crosshair;
  /* Every gesture belongs to the rectangle being drawn, not to the scroller. */
  touch-action: none;
}

.editor-detect {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.editor-detect button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  width: auto;
  margin: 0;
  align-self: flex-start;
}

.editor-detect small {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.detect-error {
  color: var(--pico-del-color, #b3261e);
}

/* Suggestions are visually a different pile from the accepted regions, in the
   same blue the canvas outlines them in — so the list and the photo agree at a
   glance about what is a proposal and what is a decision. */
.editor-suggestions {
  border-left: 3px solid rgba(86, 156, 214, 0.95);
  padding-left: var(--space-3);
  margin-bottom: var(--space-3);
}

.suggest-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-1, 0.25rem);
}

.suggest-head button {
  width: auto;
  margin: 0;
  min-height: 36px;
  padding: 0.25rem 0.6rem;
  font-size: var(--text-sm);
}

.rect-buttons {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.rect-accept {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  width: auto;
  margin: 0;
  min-height: 36px;
  padding: 0.25rem 0.6rem;
  font-size: var(--text-sm);
}

.action-with-hint {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex: 1;
}

.pending-hint {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.editor-rects ul {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--space-3);
}

.editor-rects li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-base);
}

.rect-remove {
  width: auto;
  margin: 0;
  min-height: 36px;
  padding: 0.25rem 0.6rem;
  font-size: var(--text-sm);
}

.editor-muted {
  color: var(--color-text-muted);
  font-size: var(--text-base);
  margin-bottom: var(--space-3);
}

.editor-error {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
}

.editor-error p {
  margin-bottom: var(--space-2);
}

.editor-error p:last-child {
  margin-bottom: 0;
}

.editor-warning {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
}

.editor-warning p:last-child {
  margin-bottom: 0;
}

.editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: flex-end;
}

.editor-actions button {
  width: auto;
  margin: 0;
  min-height: 44px;
}
</style>

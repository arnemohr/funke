/**
 * Bulk photo upload for the Fundsachen page (spec 023).
 *
 * Every byte goes browser → S3 directly; the Lambda only mints presigned POSTs
 * and records metadata afterwards. A batch of 50 photos therefore costs exactly
 * two API calls, and neither the 10 MB request limit nor the 29 s timeout of
 * API Gateway is in the picture.
 *
 * The canvas detour is not only about size: `imageOrientation: 'from-image'`
 * bakes the EXIF rotation into the pixels, and re-encoding drops the rest of
 * the EXIF block — GPS coordinates included. For a photo of somebody else's
 * jacket in somebody else's tent that is the point, not a side effect.
 */
import { ref } from 'vue'
import { adminApi, postPresignedForm } from '../services/api'

// Longest edge / JPEG quality per variant (spec 023, "Skalieren im Browser").
const DISPLAY_EDGE = 1600
const DISPLAY_QUALITY = 0.82
const THUMB_EDGE = 400
const THUMB_QUALITY = 0.7

// Handy uploads over festival wifi go down in rows of timeouts if more run at
// once. Four is what one phone on a saturated AP manages reliably. Exported so
// the page can name the number it promises the organiser.
export const MAX_CONCURRENT = 4

// The backend caps a single `uploads` call at 50. A larger drop is split into
// chunks of 50 rather than rejected — dragging a whole camera folder in is the
// normal case, not an error.
const CHUNK_SIZE = 50

const DECODE_MESSAGE = 'Dieses Format kann der Browser nicht lesen — bitte als JPEG exportieren'

/**
 * Draw a decoded bitmap into a canvas at the target edge length and encode it
 * as JPEG. Images already smaller than the target are never upscaled — that
 * would only cost bytes.
 * @param {ImageBitmap} bitmap
 * @param {number} maxEdge - Target length of the longest edge in px
 * @param {number} quality - JPEG quality 0..1
 * @returns {Promise<{blob: Blob, width: number, height: number}>}
 */
function encodeVariant(bitmap, maxEdge, quality) {
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
        // Freed explicitly rather than left to the GC: 50 photos means 100 of
        // these, ~7.7 MB of backing store each, and iOS Safari caps the total
        // canvas memory of a page. Once that ceiling is hit `toBlob` starts
        // handing back null, so the second half of a big drop would fail with
        // „Bild konnte nicht umgerechnet werden" while the first half went up.
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
 * Run tasks with a fixed number of workers. Tasks must swallow their own
 * errors — one broken photo may not stop the rest of the batch.
 * @param {Array<() => Promise<void>>} tasks
 * @param {number} limit
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
 * Upload queue for one event's Fundsachen page.
 * @param {string} eventId - Event ID
 */
export function useLostFoundUpload(eventId) {
  // One row per picked file, in pick order — this is what the UI renders.
  const items = ref([])
  const uploading = ref(false)

  function revokePreviews() {
    for (const item of items.value) {
      if (item.preview) URL.revokeObjectURL(item.preview)
    }
  }

  function reset() {
    revokePreviews()
    items.value = []
  }

  /** Drop the finished rows, keep the failed ones so their message stays readable. */
  function clearDone() {
    const kept = []
    for (const item of items.value) {
      if (item.status === 'done') {
        if (item.preview) URL.revokeObjectURL(item.preview)
      } else {
        kept.push(item)
      }
    }
    items.value = kept
  }

  /**
   * Decode and re-encode one file. Returns null and marks the row on failure.
   * @param {object} row - Reactive row from `items`
   * @returns {Promise<object|null>} Encoded variants plus display dimensions
   */
  async function prepare(row) {
    row.status = 'scaling'
    row.progress = 10

    if (row.file.type && !row.file.type.startsWith('image/')) {
      row.status = 'error'
      row.error = 'Das ist keine Bilddatei'
      return null
    }

    let bitmap
    try {
      bitmap = await createImageBitmap(row.file, { imageOrientation: 'from-image' })
    } catch {
      // In practice: HEIC on Chrome/Firefox. Safari and iOS decode it via the
      // system, so the same file works from a phone.
      row.status = 'error'
      row.error = DECODE_MESSAGE
      return null
    }

    try {
      const display = await encodeVariant(bitmap, DISPLAY_EDGE, DISPLAY_QUALITY)
      const thumb = await encodeVariant(bitmap, THUMB_EDGE, THUMB_QUALITY)
      row.preview = URL.createObjectURL(thumb.blob)
      row.status = 'ready'
      row.progress = 25
      return { display, thumb }
    } catch {
      row.status = 'error'
      row.error = 'Bild konnte nicht umgerechnet werden'
      return null
    } finally {
      bitmap.close()
    }
  }

  /**
   * Scale, upload and confirm one chunk of at most CHUNK_SIZE files.
   * @param {Array<object>} rows - Rows to process
   * @returns {Promise<Array<object>>} Confirmed photo objects from the backend
   */
  async function processChunk(rows) {
    // Scaling is CPU-bound and holds a full-size bitmap per file, so it runs
    // one at a time — 50 phone photos decoded in parallel is how a tab dies.
    const prepared = []
    for (const row of rows) {
      const variants = await prepare(row)
      if (variants) prepared.push({ row, variants })
    }
    if (prepared.length === 0) return []

    let uploads
    try {
      const result = await adminApi.lostFound.createUploads(eventId, prepared.length)
      uploads = result.uploads
    } catch (err) {
      const message = err.message || 'Upload-Erlaubnis konnte nicht geholt werden'
      for (const { row } of prepared) {
        row.status = 'error'
        row.error = message
      }
      return []
    }

    const succeeded = []
    const tasks = prepared.map(({ row, variants }, index) => async () => {
      const slot = uploads[index]
      row.number = slot.number
      row.status = 'uploading'
      row.progress = 30
      try {
        await postPresignedForm(slot.display, variants.display.blob)
        row.progress = 70
        await postPresignedForm(slot.thumb, variants.thumb.blob)
        row.progress = 95
        // Only a file whose BOTH variants are up may be confirmed — a page
        // with a broken thumbnail is worse than a missing photo.
        succeeded.push({
          photo_id: slot.photo_id,
          width: variants.display.width,
          height: variants.display.height,
          caption: null,
        })
        row.status = 'uploaded'
      } catch {
        row.status = 'error'
        row.error = 'Upload fehlgeschlagen — bitte erneut versuchen'
        row.progress = 0
      }
    })
    await runPool(tasks, MAX_CONCURRENT)

    if (succeeded.length === 0) return []

    try {
      const result = await adminApi.lostFound.confirmPhotos(eventId, succeeded)
      // Ein Stapel kann teilweise durchgehen: eine Zeile, die zwischen Upload
      // und Bestätigung verschwunden ist (parallel gelöscht, oder nach 24 h
      // weggeräumt), kommt in `not_confirmed` zurück. Alles andere ist live —
      // wer den ganzen Stapel als Fehler markiert, lädt Fotos erneut hoch, die
      // schon unter einer Nummer öffentlich sind, und die Seite zeigt dieselbe
      // Jacke zweimal unter zwei Nummern.
      const failedIds = new Set(result.not_confirmed || [])
      // `prepared[i]` gehört zu `uploads[i]` — der Upload-Pool läuft parallel,
      // die Reihenfolge von `succeeded` ist also nicht die der Zeilen.
      prepared.forEach(({ row }, index) => {
        if (row.status !== 'uploaded') return
        if (failedIds.has(uploads[index].photo_id)) {
          row.status = 'error'
          row.error = 'Dieses Foto gibt es nicht mehr — bitte neu hochladen'
          row.progress = 0
          return
        }
        row.status = 'done'
        row.progress = 100
      })
      return result.photos
    } catch (err) {
      const message = err.message || 'Bestätigen fehlgeschlagen'
      for (const { row } of prepared) {
        if (row.status === 'uploaded') {
          row.status = 'error'
          row.error = message
        }
      }
      return []
    }
  }

  /**
   * Scale and upload a list of files. Never rejects for a single bad file:
   * every failure lands on its own row and the rest of the batch runs through.
   * @param {FileList|Array<File>} fileList
   * @returns {Promise<Array<object>>} Confirmed photo objects, in upload order
   */
  async function uploadFiles(fileList) {
    const files = Array.from(fileList || [])
    if (files.length === 0) return []

    const rows = files.map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
      name: file.name,
      file,
      status: 'queued',
      progress: 0,
      error: null,
      preview: null,
      number: null,
    }))
    const firstNew = items.value.length
    items.value = [...items.value, ...rows]
    // Vue wraps array members lazily, so `rows` still holds the raw objects:
    // writing status and progress on those would never reach the render effect.
    // Read them back through the ref and mutate the proxies instead.
    const liveRows = items.value.slice(firstNew)

    uploading.value = true
    const confirmed = []
    try {
      for (let start = 0; start < liveRows.length; start += CHUNK_SIZE) {
        confirmed.push(...(await processChunk(liveRows.slice(start, start + CHUNK_SIZE))))
      }
    } finally {
      uploading.value = false
    }
    return confirmed
  }

  return { items, uploading, uploadFiles, reset, clearDone }
}

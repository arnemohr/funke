/**
 * Face detection for the pixelate editor (spec 024 § Unkenntlich machen).
 *
 * Runs MediaPipe's BlazeFace (full-range) over an already-decoded `ImageBitmap`
 * and returns candidate rectangles in **source pixel coordinates** — the same
 * space the editor stores its hand-drawn regions in, so a suggestion and a
 * manual rectangle are interchangeable from there on.
 *
 * Three things about this are deliberate and load-bearing:
 *
 * 1. **It suggests, it never applies.** Detection accelerates review; it does
 *    not replace looking at the photo. A model that finds 12 of 14 faces and is
 *    trusted is worse than no model, because the two it missed are exactly the
 *    harm the feature exists to prevent. The editor therefore pixelates only
 *    regions a human confirmed, and there is no batch path that touches a photo
 *    nobody opened.
 * 2. **Nothing leaves the browser.** Runtime and weights are served from our own
 *    origin, the bitmap is already in memory, and inference is WASM-local. The
 *    alternative — a cloud vision API — would ship guests' faces to a third
 *    party to decide whether they should be hidden, which is an odd trade.
 * 3. **The threshold is low and the padding generous.** For anonymisation the
 *    errors are not symmetric: a false positive costs one click to remove, a
 *    missed face is the actual damage. Both numbers are the first things to
 *    turn when calibrating against real photos.
 */

// Served from `public/` — see scripts/copy-mediapipe-wasm.mjs for the runtime
// and public/models/ for the weights. Both are excluded from the PWA precache.
const WASM_BASE = '/mediapipe/wasm'
const MODEL_URL = '/models/blaze_face_full_range.tflite'

// Full-range, not short-range: short-range is trained on selfie distances, and
// on an event photo the faces are five metres away in a group.
//
// 0.3 rather than MediaPipe's 0.5 default — see the asymmetry above.
const MIN_CONFIDENCE = 0.3

// Each detected box is grown by this share of its own width/height on every
// side. BlazeFace brackets the facial landmarks, so a raw box cuts off at the
// hairline and the jaw — and those are enough to recognise somebody.
const PAD_SHARE = 0.25

// A single shared detector: creating one costs the WASM download plus a few
// hundred milliseconds of setup, and the editor is opened once per photo.
let detectorPromise = null

async function getDetector() {
  if (!detectorPromise) {
    detectorPromise = (async () => {
      // Dynamic import so neither the guest upload page nor the gallery pays
      // for the bundle; this chunk is only fetched when somebody asks for it.
      const { FaceDetector, FilesetResolver } = await import('@mediapipe/tasks-vision')
      const fileset = await FilesetResolver.forVisionTasks(WASM_BASE)
      return FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL },
        runningMode: 'IMAGE',
        minDetectionConfidence: MIN_CONFIDENCE,
      })
    })().catch((err) => {
      // Do not cache a failed setup — a reload of the page is a fair retry, and
      // so is pressing the button again after the network came back.
      detectorPromise = null
      throw err
    })
  }
  return detectorPromise
}

/** Grow a box by PAD_SHARE on each side and clamp it to the image. */
function padToFace(box, width, height) {
  const padX = box.width * PAD_SHARE
  const padY = box.height * PAD_SHARE
  const x = Math.max(0, box.originX - padX)
  const y = Math.max(0, box.originY - padY)
  return {
    x,
    y,
    w: Math.min(width - x, box.width + 2 * padX),
    h: Math.min(height - y, box.height + 2 * padY),
  }
}

/**
 * Detect faces in a decoded bitmap.
 *
 * @param {ImageBitmap} bitmap - Source image, full resolution.
 * @returns {Promise<Array<{x: number, y: number, w: number, h: number, score: number}>>}
 *   Candidate regions in source pixels, largest first so the list reads
 *   foreground-to-background.
 * @throws {Error} With `message` set to a machine-readable reason: `no_runtime`
 *   when the WASM or the model could not be loaded (the deploy is incomplete or
 *   the network is down), `failed` when inference itself broke.
 */
export async function detectFaces(bitmap) {
  let detector
  try {
    detector = await getDetector()
  } catch (err) {
    throw new Error('no_runtime', { cause: err })
  }

  let result
  try {
    result = detector.detect(bitmap)
  } catch (err) {
    throw new Error('failed', { cause: err })
  }

  return (result?.detections ?? [])
    .filter((detection) => detection.boundingBox)
    .map((detection) => ({
      ...padToFace(detection.boundingBox, bitmap.width, bitmap.height),
      score: detection.categories?.[0]?.score ?? 0,
    }))
    .sort((a, b) => b.w * b.h - a.w * a.h)
}

/** Exposed for the UI copy and for calibration — not for branching on. */
export const detectionSettings = { MIN_CONFIDENCE, PAD_SHARE, MODEL_URL }

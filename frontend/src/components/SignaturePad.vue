<template>
  <div class="signature-pad">
    <canvas
      ref="canvasRef"
      class="pad"
      :aria-label="label"
      role="img"
      @pointerdown="start"
      @pointermove="move"
      @pointerup="end"
      @pointercancel="end"
      @pointerleave="end"
    />
    <div class="pad-actions">
      <span class="pad-hint">
        <small>{{ isEmpty ? 'Mit Finger oder Maus unterschreiben' : 'Unterschrift erfasst' }}</small>
      </span>
      <button type="button" class="outline pad-clear" :disabled="isEmpty" @click="clear">
        Nochmal
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

defineProps({
  label: { type: String, default: 'Unterschriftfeld' },
})

const emit = defineEmits(['change'])

const canvasRef = ref(null)
const isEmpty = ref(true)

let ctx = null
let drawing = false
// Device pixel ratio is baked into the backing store so the stroke is not a
// blurry mess on a phone, while the CSS box stays in layout pixels.
let ratio = 1

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  // Preserve what is already drawn across an orientation change — losing a
  // signature because someone tilted their phone would be maddening.
  const previous = isEmpty.value ? null : canvas.toDataURL('image/png')
  ratio = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = Math.round(rect.width * ratio)
  canvas.height = Math.round(rect.height * ratio)
  ctx = canvas.getContext('2d')
  ctx.scale(ratio, ratio)
  ctx.lineWidth = 2.2
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = '#0c1e3c'
  if (previous) {
    const img = new Image()
    img.onload = () => ctx.drawImage(img, 0, 0, rect.width, rect.height)
    img.src = previous
  }
}

function pointAt(event) {
  const rect = canvasRef.value.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function start(event) {
  if (!ctx) return
  // Capture the pointer so a stroke that wanders outside the canvas still
  // ends cleanly instead of leaving the pad stuck in drawing mode.
  canvasRef.value.setPointerCapture?.(event.pointerId)
  drawing = true
  const { x, y } = pointAt(event)
  ctx.beginPath()
  ctx.moveTo(x, y)
  // A single tap should leave a dot, not nothing.
  ctx.lineTo(x, y)
  ctx.stroke()
  if (isEmpty.value) {
    isEmpty.value = false
    emitChange()
  }
}

function move(event) {
  if (!drawing || !ctx) return
  // Prevent the page scrolling under the finger mid-signature.
  event.preventDefault()
  const { x, y } = pointAt(event)
  ctx.lineTo(x, y)
  ctx.stroke()
}

function end() {
  if (!drawing) return
  drawing = false
  emitChange()
}

function emitChange() {
  emit('change', isEmpty.value ? null : canvasRef.value.toDataURL('image/png'))
}

function clear() {
  const canvas = canvasRef.value
  if (!canvas || !ctx) return
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  isEmpty.value = true
  emit('change', null)
}

defineExpose({ clear, isEmpty })

onMounted(() => {
  resize()
  window.addEventListener('resize', resize)
})

onUnmounted(() => window.removeEventListener('resize', resize))
</script>

<style scoped>
.signature-pad {
  margin-bottom: var(--space-3, 0.75rem);
}

.pad {
  display: block;
  width: 100%;
  height: 160px;
  border: 1px dashed var(--muted-border-color, #94a3b8);
  border-radius: var(--radius-md, 0.375rem);
  background: var(--card-background-color, #fff);
  /* Without this the browser claims the gesture for scrolling and the stroke
     comes out in fragments. */
  touch-action: none;
  cursor: crosshair;
}

.pad-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2, 0.5rem);
  margin-top: var(--space-1, 0.25rem);
}

.pad-hint {
  color: var(--color-text-muted, #64748b);
}

.pad-clear {
  width: auto;
  margin: 0;
  padding: 0.3rem 0.75rem;
  min-height: 36px;
}
</style>

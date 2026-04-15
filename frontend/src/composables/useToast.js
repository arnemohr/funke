import { reactive } from 'vue'

const toasts = reactive([])
let nextId = 0

/**
 * Show a toast notification.
 * @param {string} message
 * @param {'success'|'error'|'info'} type
 */
export function showToast(message, type = 'info') {
  const id = nextId++
  const toast = { id, message, type }
  toasts.push(toast)

  // Auto-dismiss success/info after 4 seconds, errors after 8 seconds
  const timeout = type === 'error' ? 8000 : 4000
  setTimeout(() => dismissToast(id), timeout)
}

export function dismissToast(id) {
  const idx = toasts.findIndex(t => t.id === id)
  if (idx !== -1) toasts.splice(idx, 1)
}

export function useToast() {
  return { toasts, showToast, dismissToast }
}

/**
 * Offline scan retry queue (spec 019 §P3, T311).
 *
 * When `checkinApi.scan` fails with a network error, the scanner still
 * accepts the ticket via local HMAC verification (`ticketVerify.js`) and
 * enqueues the raw code here so it reaches the check-in log once back
 * online. Duplicates from multi-device offline scanning are expected and
 * harmless — the server's check-in log de-duplicates by
 * `(registration_id, person_index)` (T306's distinct counting), so
 * `already_checked_in` responses on flush count as success too.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { checkinApi } from '../services/api'

const STORAGE_PREFIX = 'checkin-queue-'
const FLUSH_INTERVAL_MS = 30 * 1000

function storageKey(gateToken) {
  return `${STORAGE_PREFIX}${gateToken}`
}

function loadQueue(gateToken) {
  try {
    const raw = localStorage.getItem(storageKey(gateToken))
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveQueue(gateToken, entries) {
  try {
    localStorage.setItem(storageKey(gateToken), JSON.stringify(entries))
  } catch {
    // localStorage full/unavailable — the queue still works in-memory for
    // this session, it just won't survive a reload.
  }
}

/**
 * @param {string} gateToken - The scanner gate token (queue is per-token).
 */
export function useCheckinQueue(gateToken) {
  const queue = ref(loadQueue(gateToken))
  const syncing = ref(false)

  const queueCount = computed(() => queue.value.length)

  function persist() {
    saveQueue(gateToken, queue.value)
  }

  /**
   * Enqueue a scanned code for later sync.
   * @param {string} code - The ticket code (as scanned/entered).
   */
  function enqueue(code) {
    queue.value.push({ code, queued_at: new Date().toISOString() })
    persist()
  }

  /**
   * Flush the queue front-to-back. Stops at the first entry that fails to
   * post (still offline, or a real server error) and leaves it — and
   * everything after it — queued for the next attempt. Removes an entry
   * only on HTTP success (an `already_checked_in` body still counts,
   * since the request itself succeeded).
   */
  async function flush() {
    if (syncing.value || queue.value.length === 0) return
    syncing.value = true
    try {
      while (queue.value.length > 0) {
        const entry = queue.value[0]
        try {
          await checkinApi.scan(gateToken, entry.code)
        } catch {
          break
        }
        queue.value.shift()
        persist()
      }
    } finally {
      syncing.value = false
    }
  }

  function handleOnline() {
    flush()
  }

  let intervalId = null

  onMounted(() => {
    window.addEventListener('online', handleOnline)
    intervalId = window.setInterval(flush, FLUSH_INTERVAL_MS)
    // Attempt a flush immediately in case entries survived from a prior session.
    flush()
  })

  onUnmounted(() => {
    window.removeEventListener('online', handleOnline)
    if (intervalId !== null) window.clearInterval(intervalId)
  })

  return { queue, queueCount, syncing, enqueue, flush }
}

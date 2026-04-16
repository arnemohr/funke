import { ref } from 'vue'
import { adminApi } from '../services/api'

const isSubscribed = ref(false)
const isSupported = ref(
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window,
)
const permission = ref(
  typeof Notification !== 'undefined' ? Notification.permission : 'default',
)

function urlBase64ToUint8Array(base64String) {
  // Trim whitespace/newlines that can sneak in via env vars
  const trimmed = (base64String || '').trim()
  const padding = '='.repeat((4 - (trimmed.length % 4)) % 4)
  const base64 = (trimmed + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

/**
 * Verify a decoded VAPID public key is a valid P-256 uncompressed point.
 * Must be exactly 65 bytes with a 0x04 prefix. Throws a diagnostic error otherwise.
 */
function assertValidVapidKey(keyBytes) {
  if (!keyBytes || keyBytes.length === 0) {
    throw new Error(
      'VAPID_PUBLIC_KEY ist leer. Backend-Umgebungsvariable prüfen (VAPID_PUBLIC_KEY).',
    )
  }
  if (keyBytes.length !== 65) {
    throw new Error(
      `VAPID-Schlüssel hat falsche Länge: ${keyBytes.length} Bytes (erwartet: 65). ` +
      'Erzeuge einen gültigen Schlüssel mit py-vapid oder pywebpush.',
    )
  }
  if (keyBytes[0] !== 0x04) {
    throw new Error(
      `VAPID-Schlüssel beginnt nicht mit 0x04 (uncompressed point marker). ` +
      `Erstes Byte: 0x${keyBytes[0].toString(16).padStart(2, '0')}. ` +
      'Schlüssel muss raw P-256 uncompressed point sein (nicht PEM/DER).',
    )
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function usePushNotifications() {
  async function subscribe() {
    if (!isSupported.value) return { ok: false, reason: 'unsupported' }

    // Already denied — browser will silently reject, so surface that to the caller.
    if (Notification.permission === 'denied') {
      permission.value = 'denied'
      return { ok: false, reason: 'denied' }
    }

    const perm = await Notification.requestPermission()
    permission.value = perm
    if (perm !== 'granted') {
      return { ok: false, reason: perm === 'denied' ? 'denied' : 'dismissed' }
    }

    const { public_key } = await adminApi.getVapidKey()
    const keyBytes = urlBase64ToUint8Array(public_key)
    assertValidVapidKey(keyBytes)

    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes,
    })

    await adminApi.subscribePush({
      endpoint: subscription.endpoint,
      keys: {
        p256dh: arrayBufferToBase64(subscription.getKey('p256dh')),
        auth: arrayBufferToBase64(subscription.getKey('auth')),
      },
    })

    isSubscribed.value = true
    return { ok: true }
  }

  async function unsubscribe() {
    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.getSubscription()
    if (subscription) {
      await subscription.unsubscribe()
      await adminApi.unsubscribePush()
    }
    isSubscribed.value = false
  }

  async function checkSubscription() {
    if (!isSupported.value) return
    if (typeof Notification !== 'undefined') {
      permission.value = Notification.permission
    }
    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.getSubscription()
    isSubscribed.value = !!subscription
  }

  return {
    isSubscribed,
    isSupported,
    permission,
    subscribe,
    unsubscribe,
    checkSubscription,
  }
}

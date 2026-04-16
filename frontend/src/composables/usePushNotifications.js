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
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
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

    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
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

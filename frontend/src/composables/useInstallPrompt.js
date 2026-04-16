import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

// Persist dismissal across sessions so admins don't get nagged.
const DISMISS_KEY = 'funke:install-prompt-dismissed-until'

const deferredPrompt = ref(null)
const installed = ref(false)

function isStandalone() {
  if (typeof window === 'undefined') return false
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  )
}

function dismissedUntil() {
  const v = localStorage.getItem(DISMISS_KEY)
  if (!v) return 0
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

export function useInstallPrompt() {
  const now = ref(Date.now())
  const standalone = ref(isStandalone())

  function onBeforeInstall(e) {
    e.preventDefault()
    deferredPrompt.value = e
  }
  function onInstalled() {
    installed.value = true
    deferredPrompt.value = null
  }

  onMounted(() => {
    window.addEventListener('beforeinstallprompt', onBeforeInstall)
    window.addEventListener('appinstalled', onInstalled)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('beforeinstallprompt', onBeforeInstall)
    window.removeEventListener('appinstalled', onInstalled)
  })

  const canInstall = computed(() => !!deferredPrompt.value && !standalone.value && !installed.value)

  const shouldShowBanner = computed(() => {
    if (!canInstall.value) return false
    return now.value >= dismissedUntil()
  })

  async function promptInstall() {
    if (!deferredPrompt.value) return 'unavailable'
    const result = await deferredPrompt.value.prompt()
    const outcome = result?.outcome ?? 'dismissed'
    // Clear — prompt can only be used once.
    deferredPrompt.value = null
    return outcome
  }

  // Snooze 7 days; a fresh beforeinstallprompt event can still re-arm canInstall.
  function dismissBanner() {
    const oneWeek = 7 * 24 * 60 * 60 * 1000
    localStorage.setItem(DISMISS_KEY, String(Date.now() + oneWeek))
    now.value = Date.now()
  }

  return {
    canInstall,
    shouldShowBanner,
    isStandalone: standalone,
    promptInstall,
    dismissBanner,
  }
}

import { ref } from 'vue'
import { useRegisterSW } from 'virtual:pwa-register/vue'

export function useAppUpdate() {
  const dismissed = ref(false)

  const { needRefresh, updateServiceWorker } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      // Poll for SW updates every 60 seconds.
      if (registration) {
        setInterval(() => {
          registration.update()
        }, 60 * 1000)
      }
    },
    onRegisterError(error) {
      console.error('SW registration error:', error)
    },
  })

  // Users explicitly trigger reload — no surprise interruption of in-flight work.
  function applyUpdate() {
    updateServiceWorker(true)
  }

  function dismissUpdate() {
    dismissed.value = true
  }

  return {
    updateAvailable: needRefresh,
    dismissed,
    applyUpdate,
    dismissUpdate,
  }
}

import { ref, watch } from 'vue'
import { useRegisterSW } from 'virtual:pwa-register/vue'

export function useAppUpdate() {
  const showUpdateBanner = ref(false)

  const { needRefresh, updateServiceWorker } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      // Poll for SW updates every 60 seconds
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

  // Auto-reload when update detected
  watch(needRefresh, (val) => {
    if (val) {
      showUpdateBanner.value = true
      setTimeout(() => {
        updateServiceWorker(true)
      }, 2000)
    }
  })

  return { showUpdateBanner }
}

import { ref, onMounted, onUnmounted } from 'vue'

/**
 * Composable for managing help panel state.
 * Handles open/close, ESC key dismissal, and click-outside detection.
 */
export function useHelp(initialKey = null) {
  const isOpen = ref(false)
  const helpKey = ref(initialKey)
  const panelRef = ref(null)

  function open(key) {
    helpKey.value = key
    isOpen.value = true
  }

  function close() {
    isOpen.value = false
  }

  function toggle(key) {
    if (isOpen.value && helpKey.value === key) {
      close()
    } else {
      open(key)
    }
  }

  function onKeydown(e) {
    if (e.key === 'Escape' && isOpen.value) {
      e.stopPropagation()
      close()
    }
  }

  function onClickOutside(e) {
    if (isOpen.value && panelRef.value && !panelRef.value.contains(e.target)) {
      // Don't close if the click was on a help button
      if (e.target.closest('.help-button')) return
      close()
    }
  }

  onMounted(() => {
    document.addEventListener('keydown', onKeydown, true)
    document.addEventListener('mousedown', onClickOutside)
  })

  onUnmounted(() => {
    document.removeEventListener('keydown', onKeydown, true)
    document.removeEventListener('mousedown', onClickOutside)
  })

  return { isOpen, helpKey, panelRef, open, close, toggle }
}

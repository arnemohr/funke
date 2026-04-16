import { ref } from 'vue'

const KEY = 'funke:dev-mode'

function read() {
  return localStorage.getItem(KEY) === '1'
}

const enabled = ref(read())

// Cross-tab sync.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) enabled.value = read()
  })
}

export function useDevMode() {
  function enable() {
    localStorage.setItem(KEY, '1')
    enabled.value = true
  }
  function disable() {
    localStorage.removeItem(KEY)
    enabled.value = false
  }
  function toggle() {
    if (enabled.value) disable()
    else enable()
  }
  return { enabled, enable, disable, toggle }
}
